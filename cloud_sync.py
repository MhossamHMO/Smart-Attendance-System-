import firebase_admin
from firebase_admin import credentials, db
import os
import config

# Initialize Connection
# Make sure serviceAccountKey.json is in the same folder
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://iot-attendance-42581-default-rtdb.firebaseio.com/'
    })

def log_attendance(card_id, name, entry_time, exit_time, duration, breaks=None, total_break=0.0):
    """Sends attendance record to Cloud Database with Break Details"""
    try:
        ref = db.reference('attendance_logs')
        
        # Push a new record
        ref.push({
            'card_id': card_id,
            'name': name,
            'entry': entry_time.isoformat(),
            'exit': exit_time.isoformat(),
            'duration_seconds': duration,       # This is NET duration (Work only)
            'total_break_seconds': total_break, # NEW: Total break time
            'breaks': breaks if breaks else [], # NEW: List of break details
            'timestamp': {'.sv': 'timestamp'}   # Server time
        })
        print(f"☁️ [CLOUD] Logged {name} to Firebase.")
    except Exception as e:
        print(f"⚠️ Cloud Log Failed: {e}")
        
def get_attendance_logs(limit=100):
    """Fetch attendance logs from Firebase including break details"""
    try:
        ref = db.reference('attendance_logs')
        
        # Get logs, ordered by timestamp (most recent first)
        snapshot = ref.order_by_child('timestamp').limit_to_last(limit).get()
        
        if not snapshot:
            return []
        
        logs = []
        for key, val in snapshot.items():
            # FIX: We now append the WHOLE object 'val'
            # This ensures 'breaks' and 'total_break_seconds' are passed to the dashboard
            val['id'] = key 
            logs.append(val)
        
        # Explicit sort by Entry time (Descending - Newest First)
        logs.sort(key=lambda x: x.get('entry', ''), reverse=True)
        
        return logs

    except Exception as e:
        error_str = str(e)
        if '404' in error_str or 'Not Found' in error_str:
            print(f"⚠️ Firebase database path not found. Check URL/Rules.")
        else:
            print(f"⚠️ Error fetching logs from Firebase: {e}")
        return []