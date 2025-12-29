import time
import sys
import select
import threading
import RPi.GPIO as GPIO
from mfrc522 import SimpleMFRC522

import config
import state

# Setup GPIO
GPIO.setwarnings(False)
GPIO.cleanup()
GPIO.setmode(GPIO.BCM)

# Ultrasonic pins
GPIO.setup(config.TRIG, GPIO.OUT)
GPIO.setup(config.ECHO, GPIO.IN)

# Break switch
GPIO.setup(config.BREAK_SWITCH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Servo Setup
GPIO.setup(config.SERVO_PIN, GPIO.OUT)
# Set PWM to 50Hz (Standard for Servos)
servo_pwm = GPIO.PWM(config.SERVO_PIN, 50) 
servo_pwm.start(0) # Start with 0 duty cycle (motor off)

# Initialize Reader
reader = SimpleMFRC522()

def cleanup():
    servo_pwm.stop()
    GPIO.cleanup()

def wait_for_break_switch(timeout_seconds):
    """Waits for user input (simulated via keyboard 'B') or switch."""
    print(f"(Press 'B' and ENTER to indicate BREAK)")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        dr, _, _ = select.select([sys.stdin], [], [], 0.1)  
        if dr:
            key = sys.stdin.readline().strip()
            if key.upper() == "B":
                return True
        time.sleep(0.1)
    return False

def ultrasonic_thread():
    """Background thread to handle system wake-up based on distance."""
    while True:
        # [NEW] Check if Door is operating. If so, PAUSE scanning to save CPU for Servo.
        with state.lock:
            if state.door_operation_active:
                time.sleep(0.5) 
                continue

        # 1. Measure Distance
        GPIO.output(config.TRIG, False)
        time.sleep(0.02)

        GPIO.output(config.TRIG, True)
        time.sleep(0.00001)
        GPIO.output(config.TRIG, False)

        pulse_start = pulse_end = None
        start_wait = time.time()
        while GPIO.input(config.ECHO) == 0:
            pulse_start = time.time()
            if time.time() - start_wait > 0.5: break
        start_wait = time.time()
        while GPIO.input(config.ECHO) == 1:
            pulse_end = time.time()
            if time.time() - start_wait > 0.5: break

        if pulse_start is None or pulse_end is None:
            time.sleep(0.2)
            continue

        distance = round((pulse_end - pulse_start) * 17150, 1)

        # 2. Logic to wake up or stay awake
        if distance < 30:
            with state.lock:
                if not state.system_active:
                    state.system_active = True
                    print(f"[ULTRASONIC] Person detected ({distance} cm). System ACTIVE.")
            
            # Initial sleep to keep it on
            time.sleep(10)

            # 3. STAY AWAKE if interaction is happening
            while True:
                with state.lock:
                    busy = state.interaction_in_progress
                
                if busy:
                    time.sleep(1) # Wait and check again
                else:
                    break # Interaction done, proceed to turn off

            with state.lock:
                state.system_active = False
            print("[ULTRASONIC] System DEACTIVATED.")

        time.sleep(0.2)

def servo_thread():
    """ Dedicated thread to handle door locking/unlocking """
    
    # Ensure locked at start
    servo_pwm.ChangeDutyCycle(4.3) 
    time.sleep(0.5)
    servo_pwm.ChangeDutyCycle(0) # Stop signal

    while True:
        # Wait until the main thread signals to open
        state.unlock_event.wait()
        
        # [NEW] Signal that door is moving (Pauses Ultrasonic)
        with state.lock:
            state.door_operation_active = True

        print(f"[SERVO] Unlocking door for {config.DOOR_OPEN_SECONDS} seconds...")
        
        # 1. Unlock: Rotate to 90 degrees (Vertical)
        servo_pwm.ChangeDutyCycle(9.3) 
        time.sleep(0.5) # Wait just enough time for it to move
        
        # 2. STOP SIGNAL immediately to prevent vibration while waiting
        servo_pwm.ChangeDutyCycle(0)
        
        # 3. Wait for the remaining door open duration
        time.sleep(config.DOOR_OPEN_SECONDS - 0.5)
        
        # 4. Lock: Rotate back to 0 degrees (Horizontal)
        print("[SERVO] Locking door.")
        servo_pwm.ChangeDutyCycle(4.3)
        time.sleep(0.5)
        
        # 5. Turn off signal again
        servo_pwm.ChangeDutyCycle(0)
        
        # [NEW] Door done, Ultrasonic can resume
        with state.lock:
            state.door_operation_active = False
        
        # Reset the event flag
        state.unlock_event.clear()