import os

# GPIO Config
TRIG = 23
ECHO = 24
BREAK_SWITCH_PIN = 18        # BCM pin for the break/confirm switch
SERVO_PIN = 17               # Servo Signal Pin
BREAK_CONFIRM_SECONDS = 10   # Seconds to wait for switch press
DOOR_OPEN_SECONDS = 10       # Duration to keep door open

# File Paths
ACTIVE_FILE = "active_scans.txt"
LOG_FILE = "attendance_log.txt"
KNOWN_FACES_DIR = "Known_Faces"

# Ensure directory exists immediately
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)