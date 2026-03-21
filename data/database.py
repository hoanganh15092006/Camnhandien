import json
import os
import datetime

DB_FILE = "parking_data.json"
SESSIONS_DIR = "parking_sessions"
ENTRY_DIR = os.path.join(SESSIONS_DIR, "xe_vao")
ACTIVE_DIR = os.path.join(SESSIONS_DIR, "xe_trong_bai")
EXIT_DIR = os.path.join(SESSIONS_DIR, "xe_ra")

class ParkingDB:
    def __init__(self):
        self.data = {"balances": {}, "active_sessions": {}}
        for d in [SESSIONS_DIR, ENTRY_DIR, ACTIVE_DIR, EXIT_DIR]:
            if not os.path.exists(d):
                os.makedirs(d)
        self.load()

    def load(self):
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                pass
        if "balances" not in self.data: self.data["balances"] = {}
        if "active_sessions" not in self.data: self.data["active_sessions"] = {}
        if "accounts" not in self.data: self.data["accounts"] = {}
        if "owned_plates" not in self.data: self.data["owned_plates"] = {}
        if "camera_settings" not in self.data: self.data["camera_settings"] = {"cam_index": 0, "ip_cam_url": ""}

    def get_camera_settings(self):
        return self.data.get("camera_settings", {"cam_index": 0, "ip_cam_url": ""})

    def save_camera_settings(self, cam_index, ip_cam_url):
        self.data["camera_settings"] = {"cam_index": cam_index, "ip_cam_url": ip_cam_url}
        self.save()

    def save(self):
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)

    def link_plate(self, account, plate):
        if account not in self.data["owned_plates"]:
            self.data["owned_plates"][account] = []
        if plate not in self.data["owned_plates"][account]:
            self.data["owned_plates"][account].append(plate)
            self.save()

    def get_owned_plates(self, account):
        return self.data["owned_plates"].get(account, [])

    def get_balance(self, account):
        return self.data["balances"].get(account, 0)
        
    def add_balance(self, account, amount):
        current = self.get_balance(account)
        self.data["balances"][account] = current + amount
        self.save()
        return self.data["balances"][account]
        
    def deduct_balance(self, account, amount):
        current = self.get_balance(account)
        if current >= amount:
            self.data["balances"][account] = current - amount
            self.save()
            return True
        return False
        
    def start_session(self, plate, image_path, entry_time=None):
        self.data["active_sessions"][plate] = {
            "entry_time": entry_time if entry_time else datetime.datetime.now().isoformat(),
            "entry_image": image_path
        }
        self.save()
        
    def end_session(self, plate):
        if plate in self.data["active_sessions"]:
            session = self.data["active_sessions"].pop(plate)
            self.save()
            return session
        return None
        
    def add_history_record(self, plate, scan_type, amount, time_str, note=""):
        if "history" not in self.data:
            self.data["history"] = []
        self.data["history"].insert(0, {
            "plate": plate,
            "type": scan_type,
            "amount": amount,
            "time": time_str,
            "note": note
        })
        if len(self.data["history"]) > 50:
            self.data["history"] = self.data["history"][:50]
        self.save()
        
    def get_history(self):
        return self.data.get("history", [])

    def get_session(self, plate):
        return self.data["active_sessions"].get(plate)
