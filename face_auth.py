import os
import cv2
import face_recognition
import numpy as np
import math
import time
import config

# Module-level cache
KNOWN_ENCODINGS = []
KNOWN_NAMES = []

def load_known_faces():
    global KNOWN_ENCODINGS, KNOWN_NAMES
    KNOWN_ENCODINGS = []
    KNOWN_NAMES = []
    
    print("[KNOWN_FACES] Loading faces from images...")
    for fn in os.listdir(config.KNOWN_FACES_DIR):
        if fn.lower().endswith((".jpg", ".jpeg", ".png")):
            path = os.path.join(config.KNOWN_FACES_DIR, fn)
            try:
                image = face_recognition.load_image_file(path)
                locations = face_recognition.face_locations(image)
                encodings = face_recognition.face_encodings(image, locations)
                
                if not encodings:
                    continue
                    
                base = os.path.splitext(fn)[0]
                KNOWN_ENCODINGS.append(encodings[0])
                KNOWN_NAMES.append(base)
            except Exception as e:
                print(f"Skipped {fn}: {e}")
                continue
    print(f"[KNOWN_FACES] Loaded {len(KNOWN_ENCODINGS)} faces.")

def enroll_face_for_card(card_id, user_name):
    global KNOWN_ENCODINGS, KNOWN_NAMES
    
    filename_base = f"{card_id}_{user_name}"
    image_path = os.path.join(config.KNOWN_FACES_DIR, f"{filename_base}.jpg")

    cam = cv2.VideoCapture(0)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

    if not cam.isOpened():
        print("❌ Camera not available.")
        return False

    print("Look at the camera. Press 'C' to capture or 'Q' to cancel.")
    saved = False
    
    try:
        while True:
            ret, frame = cam.read()
            if not ret: continue

            cv2.imshow("Enrollment - Press C to Capture", frame)
            key = cv2.waitKey(1) & 0xFF

            if key == ord("c"):
                cv2.imwrite(image_path, frame)
                cv2.destroyAllWindows() 
                
                print(f"✔ Image captured. Processing...")
                
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                locations = face_recognition.face_locations(rgb)
                encodings = face_recognition.face_encodings(rgb, locations)
                
                if not encodings:
                    print("❌ No face detected. Try again.")
                    try: os.remove(image_path)
                    except: pass
                    saved = False
                    break
                
                KNOWN_ENCODINGS.append(encodings[0])
                KNOWN_NAMES.append(filename_base)
                print(f"✔ Enrollment Successful for {user_name}")
                saved = True
                break

            elif key == ord("q"):
                print("❌ Enrollment canceled.")
                break
    finally:
        cam.release()
        cv2.destroyAllWindows()
        for i in range(5): cv2.waitKey(1)
        
    return saved

def get_eye_aspect_ratio(eye_points):
    def dist(p1, p2):
        return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

    A = dist(eye_points[1], eye_points[5])
    B = dist(eye_points[2], eye_points[4])
    C = dist(eye_points[0], eye_points[3])

    ear = (A + B) / (2.0 * C)
    return ear

def verify_face_for_card(card_id, socketio=None, camera_instance=None, face_frame_lock=None, current_face_frame=None, camera_lock=None):
    """
    Verify face for card - Web-based version without cv2.imshow
    Uses shared camera instance and updates current_face_frame for video stream overlay
    """
    if not KNOWN_ENCODINGS:
        if socketio:
            socketio.emit('interaction', {'msg': 'No faces registered'})
        return False, "no_known_faces"

    # Use provided camera instance or create a temporary one
    use_shared_camera = camera_instance is not None and camera_lock is not None
    if not use_shared_camera:
        cam = cv2.VideoCapture(0)
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not cam.isOpened():
            if socketio:
                socketio.emit('interaction', {'msg': 'Camera unavailable'})
            return False, "camera_unavailable"
    else:
        cam = camera_instance
    
    if socketio:
        socketio.emit('interaction', {'msg': 'Verifying Face... Please look at camera'})
    
    # [CONFIG] Tuning for Stability - More lenient settings
    BLINK_THRESHOLD = 0.22      # Lower threshold for easier blink detection
    CONSEC_FRAMES = 1           # Reduced from 2 to 1 - only need 1 frame with eyes closed
    MAX_MISSES = 15             # Increased from 8 to 15 - more forgiving for alignment
    MAX_VERIFICATION_TIME = 45  # Increased from 30 to 45 seconds
    
    blink_counter = 0
    blink_detected = False
    
    identity_verified = False
    matched_name = None
    
    frame_count = 0
    miss_count = 0              # Tracks how many frames we lost the face
    start_time = time.time()
    
    last_locations = []
    status_text = "Align Face"
    color = (0, 255, 255)

    try:
        while time.time() - start_time < MAX_VERIFICATION_TIME:
            # Read frame (with lock if shared camera)
            if use_shared_camera and camera_lock:
                with camera_lock:
                    ret, frame = cam.read()
            else:
                ret, frame = cam.read()
            
            if not ret: 
                time.sleep(0.033)
                continue
            
            # Resize for processing if needed
            frame_resized = cv2.resize(frame, (320, 240))
            frame_count += 1
            # Process every other frame for performance
            process_this_frame = (frame_count % 2 == 0)

            if process_this_frame:
                rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
                
                new_locations = face_recognition.face_locations(rgb)
                
                # --- STABILIZATION LOGIC ---
                if new_locations:
                    # Face Found! Update cache and reset miss counter
                    last_locations = new_locations
                    miss_count = 0
                    
                    landmarks = face_recognition.face_landmarks(rgb, new_locations)
                    encodings = face_recognition.face_encodings(rgb, new_locations)

                    # 1. Verify Identity (only if not yet verified)
                    if not identity_verified:
                        face_encoding = encodings[0]
                        distances = face_recognition.face_distance(KNOWN_ENCODINGS, face_encoding)
                        best_idx = np.argmin(distances)
                        # Increased threshold from 0.6 to 0.65 for more lenient matching
                        if distances[best_idx] <= 0.65:
                            name = KNOWN_NAMES[best_idx]
                            if name.startswith(f"{card_id}_"):
                                identity_verified = True
                                matched_name = name
                                if socketio:
                                    socketio.emit('interaction', {'msg': 'Identity verified. Please blink once.'})
                            else:
                                status_text = "Wrong Card!"
                                color = (0, 0, 255)
                        else:
                            status_text = "Align Face Better"
                            color = (0, 165, 255)  # Orange instead of red for less alarming

                    # 2. Check Blink (only if verified)
                    if identity_verified:
                        face_marks = landmarks[0]
                        leftEAR = get_eye_aspect_ratio(face_marks['left_eye'])
                        rightEAR = get_eye_aspect_ratio(face_marks['right_eye'])
                        avgEAR = (leftEAR + rightEAR) / 2.0

                        if avgEAR < BLINK_THRESHOLD:
                            blink_counter += 1
                            status_text = "Blink Detected..."
                            color = (0, 255, 255)  # Yellow when blinking
                        else:
                            if blink_counter >= CONSEC_FRAMES:
                                blink_detected = True
                            if blink_counter > 0:
                                status_text = "Good! Blink detected. Processing..."
                            else:
                                status_text = "Identity OK. Please blink once."
                            blink_counter = 0
                            color = (0, 255, 0)
                
                else:
                    # No Face Found in this frame
                    miss_count += 1
                    if miss_count >= MAX_MISSES:
                        # Only reset if we haven't seen a face for a long time
                        identity_verified = False
                        status_text = "Align Face"
                        color = (0, 255, 255)
                        blink_counter = 0
                    else:
                        # Keep the old status text to prevent flickering
                        pass

            # Draw UI on full resolution frame
            # Scale locations back to original frame size
            scale_x = frame.shape[1] / 320
            scale_y = frame.shape[0] / 240
            
            # Use last known locations to draw the box so it doesn't disappear immediately
            if miss_count < MAX_MISSES and last_locations:
                for (top, right, bottom, left) in last_locations:
                    # Scale coordinates
                    left = int(left * scale_x)
                    top = int(top * scale_y)
                    right = int(right * scale_x)
                    bottom = int(bottom * scale_y)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 3)
            
            # Add status text (larger font for web display)
            cv2.putText(frame, status_text, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
            
            # Update shared frame for video stream overlay
            if use_shared_camera and face_frame_lock is not None and current_face_frame is not None:
                try:
                    with face_frame_lock:
                        # Update the frame array in-place
                        if current_face_frame.shape == frame.shape:
                            current_face_frame[:] = frame
                        else:
                            # If shape mismatch, create new array
                            current_face_frame = frame.copy()
                except Exception as e:
                    print(f"Warning: Could not update face frame: {e}")
            
            if blink_detected:
                print("✔ Liveness Confirmed (Blink Detected)")
                return True, matched_name

            time.sleep(0.033)  # ~30 FPS

    except Exception as e:
        print(f"Face verification error: {e}")
        if socketio:
            socketio.emit('interaction', {'msg': f'Verification error: {str(e)}'})
        return False, "error"
    finally:
        if not use_shared_camera and cam:
            cam.release()
        
        # Note: Clearing the overlay flag is handled by app.py
    
    # Timeout
    if socketio:
        socketio.emit('interaction', {'msg': 'Verification timeout'})
    return False, "timeout"