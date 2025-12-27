from flask import Flask, render_template, request as flask_request, jsonify, Response, session, redirect, url_for, request
from flask_socketio import SocketIO, emit
import threading
import os
import time
import json
import uuid
import socket
from datetime import datetime
import cv2
import numpy as np
import face_recognition
from pyngrok import ngrok 

# --- BACKEND MODULES ---
import config
import state
import hardware
import face_auth
import storage      
import cloud_sync   

app = Flask(__name__)
app.config['SECRET_KEY'] = 'iot_secret_key_change_this'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# --- GLOBAL STATE ---
camera_lock = threading.Lock()
face_frame_lock = threading.Lock()
camera_instance = None
current_face_frame = None
face_verification_active = False

# Admin Configuration
admin_cards = ['231654949486'] 
ADMIN_PASSWORD = "UGRF" 
admin_auth_pending = False
admin_auth_socket_id = None
valid_login_tokens = {} 

# Enrollment State
enrollment_pending = False

# Ngrok URL
public_url = None

# --- NETWORK HELPER (Moved Logic Here) ---
def start_network_service():
    """Waits for internet and starts Ngrok in the background."""
    global public_url
    print(" * [NETWORK] Network thread started. Waiting for connection...", flush=True)
    
    # 1. Wait for Internet Loop
    while True:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            print(" * [NETWORK] Connected to Internet!", flush=True)
            break
        except OSError:
            time.sleep(2) # Check every 2 seconds silently
            
    # 2. Start Ngrok once connected
    try:
        # Use your specific static domain here
        public_url = ngrok.connect(5000, domain="noncretaceous-nikole-noninstructively.ngrok-free.dev").public_url
        print(f" * 🚀 NGROK PUBLIC URL: {public_url}", flush=True)
    except Exception as e:
        print(f" * Ngrok Warning: {e}", flush=True)

# --- 1. VIDEO STREAMING ---
def init_camera():
    global camera_instance
    if camera_instance is not None:
        if camera_instance.isOpened(): return True
        else: camera_instance.release(); camera_instance = None
    
    for idx in range(3):
        print(f"[CAMERA] Attempting to open index {idx}...")
        test_cam = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if test_cam.isOpened():
            test_cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            test_cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            test_cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            test_cam.set(cv2.CAP_PROP_FPS, 30)
            test_cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            ret, _ = test_cam.read()
            if ret:
                print(f"[CAMERA] Success! Initialized at Index {idx}")
                camera_instance = test_cam
                return True
            test_cam.release()
    return False

def generate_frames():
    global camera_instance
    if not init_camera():
        while True:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "Camera Unavailable", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
            ret, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(1.0)
    
    while True:
        try:
            with camera_lock:
                if camera_instance is None or not camera_instance.isOpened():
                    if not init_camera(): break
                ret, frame = camera_instance.read()
                if not ret: time.sleep(0.03); continue
                
                with face_frame_lock:
                    if face_verification_active and current_face_frame is not None:
                        frame = current_face_frame.copy()
                
                ret, buffer = cv2.imencode('.jpg', frame)
                frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.03)
        except: time.sleep(0.1)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- 2. MAIN LOGIC LOOP ---
def background_loop():
    global admin_auth_pending, admin_auth_socket_id
    print("[SYSTEM] Starting Hardware...", flush=True)
    
    face_auth.load_known_faces()
    storage.load_active_scans()  

    threading.Thread(target=hardware.ultrasonic_thread, daemon=True).start()
    threading.Thread(target=hardware.servo_thread, daemon=True).start()
    
    last_active = False
    
    # Sleep Delay Vars
    sleep_start_time = None
    SLEEP_GRACE_PERIOD = 5.0 

    while True:
        time.sleep(0.1) 
        
        with state.lock: raw_active = state.system_active
        
        final_active_state = False
        if raw_active:
            final_active_state = True
            sleep_start_time = None 
        else:
            if sleep_start_time is None:
                sleep_start_time = time.time()
            
            if time.time() - sleep_start_time > SLEEP_GRACE_PERIOD:
                final_active_state = False
            else:
                final_active_state = True 
        
        if final_active_state != last_active:
            socketio.emit('system_status', {'active': final_active_state})
            last_active = final_active_state
        
        if not final_active_state: continue

        try:
            card_id, text = hardware.reader.read_no_block()
        except: card_id = None

        if card_id:
            print(f"[RFID] Card detected: {card_id}")
            card_uid = str(card_id).strip()
            
            if admin_auth_pending:
                success = card_uid in admin_cards
                token = None
                if success:
                    token = str(uuid.uuid4())
                    valid_login_tokens[token] = time.time()
                
                if admin_auth_socket_id:
                    socketio.emit('admin_authenticated', {'success': success, 'token': token}, room=admin_auth_socket_id)
                
                time.sleep(0.5)
                admin_auth_pending = False
            else:
                handle_scan(card_uid)

def handle_scan(card_text):
    global face_verification_active, current_face_frame
    with state.lock: state.interaction_in_progress = True
    socketio.emit('interaction', {'msg': 'Processing Card...'})

    if not os.path.exists(config.KNOWN_FACES_DIR): os.makedirs(config.KNOWN_FACES_DIR)
    
    try:
        files = [f for f in os.listdir(config.KNOWN_FACES_DIR) if f.startswith(f"{card_text}_")]
    except: files = []

    if not files:
        socketio.emit('enrollment_request', {'card_id': card_text, 'message': 'New card detected!'})
        return

    socketio.emit('interaction', {'msg': 'Verifying Face...'})
    with face_frame_lock:
        face_verification_active = True
        current_face_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    verified, name = face_auth.verify_face_for_card(
        card_text, socketio, camera_instance, face_frame_lock, current_face_frame, camera_lock
    )
    
    with face_frame_lock:
        face_verification_active = False
        current_face_frame = None
    
    if not verified:
        socketio.emit('interaction', {'msg': '❌ Access Denied'}); time.sleep(2); socketio.emit('reset_ui')
        with state.lock: state.interaction_in_progress = False
        return

    user_name = name.replace(f"{card_text}_", "")
    now = datetime.now()
    
    with state.lock:
        if card_text not in state.scan1:
            state.scan1[card_text] = {
                "entry": now, "name": user_name, "on_break": False,
                "current_break_start": None, "total_break_seconds": 0.0, "breaks": []
            }
            storage.save_active_scans_file()
            socketio.emit('user_checked_in', {'name': user_name, 'action': 'entry', 'msg': f'Welcome {user_name}!'})
        else:
            entry_rec = state.scan1[card_text]
            entry_rec["name"] = user_name
            
            if entry_rec.get("on_break", False):
                break_start = entry_rec.get("current_break_start")
                if break_start:
                    duration = (now - break_start).total_seconds()
                    entry_rec["breaks"].append((break_start, now))
                    entry_rec["total_break_seconds"] = entry_rec.get("total_break_seconds", 0.0) + duration
                    entry_rec["current_break_start"] = None
                    entry_rec["on_break"] = False
                    storage.save_active_scans_file()
                    socketio.emit('user_checked_in', {'name': user_name, 'action': 'return', 'msg': f'Welcome back {user_name}!'})
                else:
                    entry_rec["on_break"] = False
                    socketio.emit('ask_user_action', {'name': user_name, 'card_id': card_text})
            else:
                socketio.emit('ask_user_action', {'name': user_name, 'card_id': card_text})
                return 

    time.sleep(5)
    socketio.emit('reset_ui')
    with state.lock: state.interaction_in_progress = False

# --- 3. SOCKET HANDLERS ---
@socketio.on('user_action')
def handle_user_action(data):
    action, card_id = data.get('action'), data.get('card_id')
    if not card_id: return
    now = datetime.now()
    
    with state.lock:
        if card_id not in state.scan1: return
        entry_rec = state.scan1[card_id]
        user_name = entry_rec.get("name", "User")
        
        if action == 'break':
            entry_rec["on_break"] = True
            entry_rec["current_break_start"] = now
            storage.save_active_scans_file()
            socketio.emit('interaction', {'msg': f'Break started for {user_name}'})
            state.unlock_event.set()
            
        elif action == 'leave':
            entry_data = state.scan1.pop(card_id)
            entry_time = entry_data["entry"]
            total_break = entry_data.get("total_break_seconds", 0.0)
            raw_breaks = entry_data.get("breaks", [])
            
            formatted_breaks = [
                {'start': s.isoformat(), 'end': e.isoformat(), 'duration': (e-s).total_seconds()} 
                for s, e in raw_breaks
            ]

            duration = (now - entry_time).total_seconds()
            net_duration = max(0.0, duration - total_break)
            
            storage.save_to_log(card_id, user_name, entry_time, now, net_duration, raw_breaks, total_break)
            cloud_sync.log_attendance(card_id, user_name, entry_time, now, net_duration, breaks=formatted_breaks, total_break=total_break)
            storage.save_active_scans_file()
            
            socketio.emit('interaction', {'msg': f'Goodbye {user_name}! Saved.'})
            state.unlock_event.set()
        
        state.interaction_in_progress = False
    
    time.sleep(5)
    socketio.emit('reset_ui')

# --- 4. ENROLLMENT & ADMIN ---
@socketio.on('admin_login_request')
def handle_admin_request(data):
    global admin_auth_pending, admin_auth_socket_id
    admin_auth_pending = True
    admin_auth_socket_id = flask_request.sid
    socketio.emit('admin_card_scan_request', {'message': 'Scan Admin Card'}, room=flask_request.sid)

@socketio.on('admin_login_cancel')
def cancel_admin(data): 
    global admin_auth_pending
    admin_auth_pending = False

@socketio.on('enrollment_name_submitted')
def handle_enroll_name(data):
    user, card = data.get('name', '').strip(), data.get('card_id', '')
    if user and card:
        socketio.emit('enrollment_capture', {'message': 'Look at camera...', 'card_id': card}, room=flask_request.sid)
        threading.Thread(target=enroll_user_face, args=(card, user, flask_request.sid), daemon=True).start()

def enroll_user_face(card_id, user_name, socket_id):
    global face_verification_active, current_face_frame, camera_instance
    fname = f"{card_id}_{user_name}"
    path = os.path.join(config.KNOWN_FACES_DIR, f"{fname}.jpg")
    
    with face_frame_lock: face_verification_active = True; current_face_frame = np.zeros((480,640,3), dtype=np.uint8)
    socketio.emit('enrollment_status', {'message': 'Aligning Face...'}, room=socket_id)
    
    try:
        for _ in range(150):
            time.sleep(0.05)
            with camera_lock:
                if not camera_instance or not camera_instance.isOpened(): continue
                ret, frame = camera_instance.read()
            if not ret: continue
            
            disp = frame.copy()
            cv2.putText(disp, f"Enroll: {user_name}", (10,50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
            with face_frame_lock: current_face_frame[:] = disp
            
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb)
            if locs:
                encs = face_recognition.face_encodings(rgb, locs)
                if encs:
                    cv2.imwrite(path, frame)
                    face_auth.KNOWN_ENCODINGS.append(encs[0])
                    face_auth.KNOWN_NAMES.append(fname)
                    socketio.emit('enrollment_success', {'message': 'Success!', 'card_id': card_id}, room=socket_id)
                    return
        socketio.emit('enrollment_error', {'message': 'Timeout'}, room=socket_id)
    except: socketio.emit('enrollment_error', {'message': 'Error'}, room=socket_id)
    finally:
        with face_frame_lock: face_verification_active = False; current_face_frame = None
        with state.lock: state.interaction_in_progress = False

@socketio.on('enrollment_cancel')
def cancel_enroll(data): 
    with state.lock: state.interaction_in_progress = False

# --- 5. ROUTES ---
@app.route('/')
def index():
    if public_url:
        server_address = public_url
    else:
        server_address = ""    
    return render_template('index.html', server_ip=server_address)

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = flask_request.json
    password = data.get('password', '').strip()
    
    if password == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({'success': True})
    return jsonify({'success': False})

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))

@app.route('/dashboard')
def dashboard():
    token = request.args.get('token')
    if token and token in valid_login_tokens:
        timestamp = valid_login_tokens[token]
        if time.time() - timestamp < 60:
            session['logged_in'] = True
            del valid_login_tokens[token] 
            return render_template('dashboard.html')
    
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
        
    return render_template('dashboard.html')

@app.route('/api/attendance_logs')
def get_logs(): return jsonify({'logs': cloud_sync.get_attendance_logs(limit=100)})

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    s_file = 'settings.json'
    if flask_request.method == 'POST':
        val = flask_request.json.get('threshold', '09:00')
        with open(s_file, 'w') as f: json.dump({'attendance_threshold': val}, f)
        config.ATTENDANCE_THRESHOLD = val
        return jsonify({'success': True})
    
    val = '09:00'
    if os.path.exists(s_file):
        with open(s_file) as f: val = json.load(f).get('attendance_threshold', '09:00')
    return jsonify({'threshold': val})

if __name__ == '__main__':
    # --- ORDER OF OPERATIONS CHANGED FOR RELIABILITY ---
    
    # 1. Start Hardware INSTANTLY (Do not wait for anything)
    threading.Thread(target=background_loop, daemon=True).start()

    # 2. Start Network/Ngrok in a BACKGROUND thread (So it doesn't block the system)
    threading.Thread(target=start_network_service, daemon=True).start()
    
    # 3. Start Flask Server (Runs locally immediately)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)