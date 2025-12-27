# 🚀 Smart IoT Attendance System with Face Recognition

An autonomous, headless IoT appliance built on Raspberry Pi that integrates **RFID authentication**, **Ultrasonic proximity sensing**, and **Real-time Face Recognition**. The system is designed to operate 24/7 as a standalone security terminal, accessible via a secure mobile dashboard from anywhere in the world.

---

## 🛠 Project Architecture
The system follows a multi-threaded "Headless" architecture. It boots directly into the application, connects to a mobile hotspot, and establishes a secure global tunnel without requiring a monitor, keyboard, or manual password entry.

### Core Technology Stack
* **Hardware:** Raspberry Pi 4/5, RC522 RFID Reader, Ultrasonic Sensor (HC-SR04), SG90 Servo Motor, USB Camera.
* **Backend:** Python 3, Flask, Flask-SocketIO.
* **Real-Time:** WebSockets (via SocketIO) for instant mobile updates.
* **Security:** `face_recognition` (dlib), RFID UID validation, and Ngrok Tunneling.
* **Automation:** Linux `systemd` services for auto-boot and recovery.

---

## 📂 File Structure & Responsibilities

### 1. `app.py` (The Central Nervous System)
The main entry point. It manages the Flask web server and coordinates between the hardware threads and the web dashboard.
* **Multi-threading:** Runs the hardware loops, network services, and video streaming in parallel.
* **Video Engine:** Uses OpenCV to capture frames and injects AI verification overlays when a card is scanned.
* **Session Management:** Handles Admin logins via RFID "Token Bypass" for secure headless access.

### 2. `hardware.py` (Peripheral Control)
Contains the low-level logic for all physical components.
* **Ultrasonic Thread:** Constantly monitors for proximity. If a person is within 1.0m, it wakes the system from "Standby".
* **Servo Thread:** Listens for "Unlock" events to physically move the door mechanism.
* **RFID Logic:** Interfaces with the SPI-based RC522 to capture unique card UIDs.

### 3. `face_auth.py` (Biometric Security)
The AI layer of the project.
* **Encoding:** Converts known faces into 128-dimension mathematical vectors.
* **Verification:** Compares the live camera feed against stored encodings using a tolerance threshold to grant or deny access.

### 4. `storage.py` & `cloud_sync.py` (Data Persistence)
* **Local Logging:** Saves attendance logs locally in JSON/CSV format.
* **Active Scans:** Tracks who is currently "Checked In" or "On Break" so the system can resume state after a power failure.

### 5. `config.py` & `state.py`
* **config.py:** Stores adjustable parameters like sensor distances, face match tolerance, and GPIO pin mapping.
* **state.py:** A shared memory module that allows different threads to communicate (e.g., the Ultrasonic thread telling the Camera thread to wake up).
### 6. UI Templates (Frontend)
The user interface is split into three specialized HTML files to manage different system states:
* **`index.html`:** The primary interface for users. It handles the "Active Mode" UI, displaying the live camera feed, greeting users, and providing buttons for "Break" and "Leave" actions.
* **`login.html`:** A secure portal for administrators to manually log in if the RFID token bypass is not used.
* **`dashboard.html`:** The administrative command center. It provides real-time access to attendance logs, registration of new faces, and system configuration settings.

---

## ⚡ Key Features Developed

### 1. Headless Automation
The system is configured to run as a **Systemd Service** (`attendance.service`).
* **Auto-Start:** The app starts before the user logs in.
* **Auto-Connect:** Connects to a pre-defined Hotspot at the system level.
* **Linger Feature:** The user session stays active in the background, keeping the Ngrok tunnel open 24/7.

### 2. Mobile-Optimized Dashboard
The system includes a dedicated mobile dashboard that allows administrators and users to interact with the device remotely. 
* **Seamless Access:** The dashboard is easily accessible by scanning the unique QR code generated on the system's enclosure or standby screen.
* **Real-Time Interaction:** Users can perform actions such as "Break" or "Leave" directly from their smartphones while standing in front of the terminal.
* **Remote Monitoring:** Administrators can view the live camera feed and access attendance logs through a secure global tunnel without being on the same local network.

### 3. Dual-Mode Interface
* **Standby Mode:** Displays a "System Standby" screen with a QR code for Admins to save power and bandwidth.
* **Active Mode:** Automatically triggers the live camera feed and HUD when a person is detected nearby.

---

## 🚀 How to Run
1.  **Hardware Check:** Ensure all GPIO pins are connected as per `config.py`.
2.  **Environment:**
3.  ```bash
    source myenv/bin/activate
    pip install -r requirements.txt
    ```
4.  **Start Service:**
    ```bash
    sudo systemctl start attendance.service
    ```
5.  **Access:** Scan the generated QR code on the device box to open the dashboard on your phone.

---

