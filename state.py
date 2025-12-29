import threading

# Active entries in RAM: card_text -> dict (entry, name, on_break, etc.)
scan1 = {} 

# Completed cycles list
scansum = [] 

# System flags
system_active = False
interaction_in_progress = False 

# [NEW] Flag to pause ultrasonic while door is moving
door_operation_active = False

# Threading lock
lock = threading.Lock()

# Event to signal the Servo Thread to unlock
unlock_event = threading.Event()