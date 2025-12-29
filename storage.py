import os
import json
from datetime import datetime
import config
import state

def _serialize_scan_entry(entry_dict):
    d = {
        "entry": entry_dict["entry"].isoformat(),
        "name": entry_dict.get("name", "Unknown"),
        "on_break": entry_dict.get("on_break", False),
        "current_break_start": entry_dict["current_break_start"].isoformat() if entry_dict.get("current_break_start") else None,
        "total_break_seconds": entry_dict.get("total_break_seconds", 0.0),
        "breaks": [
            {"start": s.isoformat(), "end": e.isoformat()} for (s, e) in entry_dict.get("breaks", [])
        ],
    }
    return json.dumps(d)

def _deserialize_scan_entry(s):
    d = json.loads(s)
    entry = {
        "entry": datetime.fromisoformat(d["entry"]),
        "name": d.get("name", "Unknown"),
        "on_break": d.get("on_break", False),
        "current_break_start": datetime.fromisoformat(d["current_break_start"]) if d.get("current_break_start") else None,
        "total_break_seconds": float(d.get("total_break_seconds", 0.0)),
        "breaks": [
            (datetime.fromisoformat(x["start"]), datetime.fromisoformat(x["end"])) for x in d.get("breaks", [])
        ],
    }
    return entry

def load_active_scans():
    if not os.path.exists(config.ACTIVE_FILE):
        return

    print("[RECOVERY] Loading active scans...")
    with open(config.ACTIVE_FILE, "r") as f:
        for line in f:
            try:
                line = line.strip()
                if not line: continue
                
                parts = line.split(" | ")
                
                # Format: Name | UID | JSON_Payload
                if len(parts) == 3:
                    name_display, card, payload = parts
                    entry_dict = _deserialize_scan_entry(payload)
                    entry_dict["name"] = name_display 
                
                # Legacy Format: UID | JSON_Payload
                elif len(parts) == 2:
                    card, payload = parts
                    entry_dict = _deserialize_scan_entry(payload)
                else:
                    continue

                state.scan1[card] = entry_dict
                print(f"  -> Restored: {entry_dict['name']} (ID: {card})")
            except Exception as e:
                print(f"[RECOVERY] Skipped invalid line: {line} ({e})")
                continue

def save_active_scans_file():
    with open(config.ACTIVE_FILE, "w") as f:
        for card, entry in state.scan1.items():
            payload = _serialize_scan_entry(entry)
            name_display = entry.get("name", "Unknown")
            f.write(f"{name_display} | {card} | {payload}\n")

def save_to_log(card_text, name, entry, exit_time, total_seconds, breaks, total_break_seconds):
    with open(config.LOG_FILE, "a") as f:
        f.write("========================================\n")
        f.write(f"Name: {name}\n")
        f.write(f"Card ID: {card_text}\n")
        f.write(f"Entry: {entry.isoformat()}\n")
        f.write(f"Exit: {exit_time.isoformat()}\n")
        f.write(f"Total time (net): {total_seconds} seconds\n")
        f.write(f"Total breaks (seconds): {total_break_seconds}\n")
        if breaks:
            f.write("Breaks:\n")
            for (s, e) in breaks:
                dur = (e - s).total_seconds()
                f.write(f"  - {s.isoformat()} to {e.isoformat()} -> {dur} sec\n")
        f.write("\n")

# [NEW FUNCTION HERE]
def check_attendance_threshold(threshold_hours):
    """Scans log file and prints validity report based on total hours."""
    if not os.path.exists(config.LOG_FILE):
        print("❌ No attendance log found yet.")
        return

    print(f"\n--- ATTENDANCE REPORT (Threshold: {threshold_hours} hours) ---")
    threshold_seconds = float(threshold_hours) * 3600
    user_totals = {}

    current_name = None
    
    # Parse the log file
    with open(config.LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            # Extract Name
            if line.startswith("Name: "):
                current_name = line.split(": ", 1)[1]
                if current_name not in user_totals:
                    user_totals[current_name] = 0.0
            
            # Extract Total Seconds and add to that user
            elif line.startswith("Total time (net): "):
                try:
                    # Line format: "Total time (net): 123.45 seconds"
                    # Split by ": " then take first part of remainder "123.45"
                    val_str = line.split(": ")[1].split(" ")[0]
                    seconds = float(val_str)
                    if current_name:
                        user_totals[current_name] += seconds
                except Exception:
                    continue

    # Print Validation Results
    if not user_totals:
        print("No completed attendance records found.")
    else:
        for name, total_sec in user_totals.items():
            total_hours = total_sec / 3600.0
            status = "Valid" if total_sec >= threshold_seconds else "Not Valid"
            
            # Using colors if supported, or just text
            print(f"- {name:<15}: {total_hours:.2f} hrs  ->  {status}")
            
    print("------------------------------------------------------\n")