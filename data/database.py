import pymysql
import os
import datetime
import json

DB_HOST = "localhost"
DB_USER = "root"
DB_PASS = ""
DB_NAME = "parking_db"
SESSIONS_DIR = "parking_sessions"
ENTRY_DIR = os.path.join(SESSIONS_DIR, "xe_vao")
ACTIVE_DIR = os.path.join(SESSIONS_DIR, "xe_trong_bai")
EXIT_DIR = os.path.join(SESSIONS_DIR, "xe_ra")

class ParkingDB:
    def __init__(self):
        self.data = {"accounts": {}, "active_sessions": {}} 
        for d in [SESSIONS_DIR, ENTRY_DIR, ACTIVE_DIR, EXIT_DIR]:
            if not os.path.exists(d):
                os.makedirs(d)
        
        # Connect to MySQL Server to create database if not exists
        tmp_conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS)
        tmp_cursor = tmp_conn.cursor()
        tmp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        tmp_conn.commit()
        tmp_conn.close()

        # Connect to the actual database with autocommit true
        self.conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
        self._create_tables()
        self._sync_mock_data()

    def _create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        username VARCHAR(255) PRIMARY KEY,
                        password VARCHAR(255),
                        balance INT DEFAULT 0,
                        qr_code VARCHAR(255)
                    )''')
        # Thử thêm cột qr_code nếu bảng cũ chưa có
        try:
            c.execute("ALTER TABLE users ADD COLUMN qr_code VARCHAR(255)")
        except pymysql.err.OperationalError:
            pass
        except pymysql.err.InternalError:
            pass

        c.execute('''CREATE TABLE IF NOT EXISTS owned_plates (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        username VARCHAR(255),
                        plate VARCHAR(255),
                        FOREIGN KEY(username) REFERENCES users(username)
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_sessions (
                        plate VARCHAR(255) PRIMARY KEY,
                        entry_time VARCHAR(255),
                        entry_image VARCHAR(255)
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS history_records (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        plate VARCHAR(255),
                        type VARCHAR(50),
                        amount INT,
                        time VARCHAR(255),
                        note TEXT
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key_name VARCHAR(255) PRIMARY KEY,
                        value_data TEXT
                    )''')
        c.execute('''CREATE TABLE IF NOT EXISTS remote_commands (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        qr_plate VARCHAR(255),
                        cmd_type VARCHAR(50),
                        status VARCHAR(50) DEFAULT 'PENDING'
                    )''')
        try: c.execute("ALTER TABLE remote_commands ADD COLUMN result_msg TEXT")
        except: pass

    def _sync_mock_data(self):
        c = self.conn.cursor()
        c.execute("SELECT username, password FROM users")
        self.data["accounts"] = {row['username']: row['password'] for row in c.fetchall()}
        
        c.execute("SELECT plate, entry_time, entry_image FROM active_sessions")
        for row in c.fetchall():
            self.data["active_sessions"][row['plate']] = {
                "entry_time": row['entry_time'],
                "entry_image": row['entry_image']
            }

    def get_camera_settings(self):
        c = self.conn.cursor()
        c.execute("SELECT value_data FROM settings WHERE key_name='camera'")
        row = c.fetchone()
        if row: return json.loads(row['value_data'])
        return {"cam_index": 0, "ip_cam_url": ""}

    def save_camera_settings(self, cam_index, ip_cam_url):
        val = json.dumps({"cam_index": cam_index, "ip_cam_url": ip_cam_url})
        c = self.conn.cursor()
        c.execute("REPLACE INTO settings (key_name, value_data) VALUES ('camera', %s)", (val,))

    def save(self):
        self._sync_mock_data()
        
    def link_plate(self, account, plate):
        c = self.conn.cursor()
        c.execute("SELECT 1 FROM owned_plates WHERE username=%s AND plate=%s", (account, plate))
        if not c.fetchone():
            c.execute("INSERT INTO owned_plates (username, plate) VALUES (%s, %s)", (account, plate))

    def get_owned_plates(self, account):
        c = self.conn.cursor()
        c.execute("SELECT plate FROM owned_plates WHERE username=%s", (account,))
        return [row['plate'] for row in c.fetchall()]

    def get_balance(self, account):
        c = self.conn.cursor()
        c.execute("SELECT balance FROM users WHERE username=%s", (account,))
        row = c.fetchone()
        return row['balance'] if row else 0
        
    def add_balance(self, account, amount):
        current = self.get_balance(account)
        c = self.conn.cursor()
        if current == 0: 
            c.execute("SELECT 1 FROM users WHERE username=%s", (account,))
            if not c.fetchone():
                c.execute("INSERT INTO users (username, password, balance, qr_code) VALUES (%s, '123456', %s, %s)", (account, amount, f"QR_{account}"))
            else:
                c.execute("UPDATE users SET balance = balance + %s WHERE username=%s", (amount, account))
        else:
            c.execute("UPDATE users SET balance = balance + %s WHERE username=%s", (amount, account))
        return current + amount
        
    def deduct_balance(self, account, amount):
        current = self.get_balance(account)
        if current >= amount:
            c = self.conn.cursor()
            c.execute("UPDATE users SET balance = balance - %s WHERE username=%s", (amount, account))
            return True
        return False
        
    def start_session(self, plate, image_path, entry_time=None):
        etime = entry_time if entry_time else datetime.datetime.now().isoformat()
        c = self.conn.cursor()
        c.execute("REPLACE INTO active_sessions (plate, entry_time, entry_image) VALUES (%s, %s, %s)", (plate, etime, image_path))
        self._sync_mock_data()
        
    def end_session(self, plate):
        c = self.conn.cursor()
        c.execute("SELECT * FROM active_sessions WHERE plate=%s", (plate,))
        session = c.fetchone()
        if session:
            c.execute("DELETE FROM active_sessions WHERE plate=%s", (plate,))
            self._sync_mock_data()
            return session
        return None
        
    def add_history_record(self, plate, scan_type, amount, time_str, note=""):
        c = self.conn.cursor()
        c.execute("INSERT INTO history_records (plate, type, amount, time, note) VALUES (%s, %s, %s, %s, %s)", 
                  (plate, scan_type, amount, time_str, note))
        
    def get_history(self):
        c = self.conn.cursor()
        c.execute("SELECT plate, type, amount, time, note FROM history_records ORDER BY time ASC") 
        h = list(c.fetchall())
        h.reverse()
        return h

    def get_session(self, plate):
        c = self.conn.cursor()
        c.execute("SELECT entry_time, entry_image FROM active_sessions WHERE plate=%s", (plate,))
        row = c.fetchone()
        return row if row else None

    def get_user_by_qr(self, qr_code):
        c = self.conn.cursor()
        c.execute("SELECT username FROM users WHERE qr_code=%s", (qr_code,))
        row = c.fetchone()
        return row['username'] if row else None

    def get_qr_code(self, username):
        c = self.conn.cursor()
        c.execute("SELECT qr_code FROM users WHERE username=%s", (username,))
        row = c.fetchone()
        if row and row['qr_code']: return row['qr_code']
        # Migrate old user
        new_qr = f"QR_{username}"
        c.execute("UPDATE users SET qr_code=%s WHERE username=%s", (new_qr, username))
        return new_qr

    def add_remote_command(self, qr_plate, cmd_type):
        c = self.conn.cursor()
        c.execute("INSERT INTO remote_commands (qr_plate, cmd_type, status) VALUES (%s, %s, 'PENDING')", (qr_plate, cmd_type))
        return c.lastrowid

    def get_pending_command(self, cmd_type=None):
        c = self.conn.cursor()
        if cmd_type:
            c.execute("SELECT * FROM remote_commands WHERE status='PENDING' AND cmd_type=%s ORDER BY id ASC LIMIT 1", (cmd_type,))
        else:
            c.execute("SELECT * FROM remote_commands WHERE status='PENDING' ORDER BY id ASC LIMIT 1")
        return c.fetchone()

    def update_command_status(self, cmd_id, status, result_msg=""):
        c = self.conn.cursor()
        c.execute("UPDATE remote_commands SET status=%s, result_msg=%s WHERE id=%s", (status, result_msg, cmd_id))
        
    def get_command_by_id(self, cmd_id):
        c = self.conn.cursor()
        c.execute("SELECT * FROM remote_commands WHERE id=%s", (cmd_id,))
        return c.fetchone()

