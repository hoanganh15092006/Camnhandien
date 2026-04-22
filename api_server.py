from flask import Flask, request, jsonify
from flask_cors import CORS
from data.database import ParkingDB
import datetime

app = Flask(__name__)
CORS(app)
db = ParkingDB()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    # For now password logic isn't heavily enforced in db.py mock data sync, but we check accounts dict
    db._sync_mock_data()
    accs = db.data.get("accounts", {})
    if username in accs and accs[username] == password:
        return jsonify({"success": True, "message": "Login successful", "username": username})
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    db._sync_mock_data()
    if username in db.data.get("accounts", {}):
        return jsonify({"success": False, "message": "User exists"}), 400
    
    # create user via add_balance logic initially or via direct sql
    c = db.conn.cursor()
    qr_code = f"QR_{username}"
    c.execute("INSERT INTO users (username, password, balance, qr_code) VALUES (%s, %s, 0, %s)", (username, password, qr_code))
    db.conn.commit()
    db._sync_mock_data()
    return jsonify({"success": True, "message": "Registered successfully", "qr_code": qr_code})

@app.route('/api/user/info', methods=['GET'])
def get_user_info():
    username = request.args.get('username')
    if not username: return jsonify({"error": "Missing username"}), 400
    balance = db.get_balance(username)
    plates = db.get_owned_plates(username)
    qr_code = db.get_qr_code(username)
    return jsonify({
        "username": username,
        "balance": balance,
        "owned_plates": plates,
        "qr_code": qr_code
    })

@app.route('/api/user/topup', methods=['POST'])
def topup():
    data = request.json
    username = data.get('username')
    amount = data.get('amount', 0)
    if amount <= 0: return jsonify({"error": "Invalid amount"}), 400
    new_bal = db.add_balance(username, amount)
    db.add_history_record(username, "Nạp Tiền (App)", amount, datetime.datetime.now().isoformat(), note=f"Nạp qua App Khách hàng")
    return jsonify({"success": True, "new_balance": new_bal})

@app.route('/api/user/history', methods=['GET'])
def get_user_history():
    username = request.args.get('username')
    if not username: return jsonify({"error": "Missing username"}), 400
    all_h = db.get_history()
    plates = set(db.get_owned_plates(username) + [username])
    user_h = [h for h in all_h if h['plate'] in plates]
    return jsonify({"history": user_h})

@app.route('/api/parking/status', methods=['GET'])
def get_status():
    db._sync_mock_data()
    active = len(db.data.get("active_sessions", {}))
    return jsonify({"active_cars": active, "total_capacity": 500, "nearest_station": "Tòa nhà Trung Tâm Đỗ Xe"})

@app.route('/api/user/link_plate', methods=['POST'])
def link_plate():
    data = request.json
    username = data.get('username')
    plate = data.get('plate')
    db.link_plate(username, plate)
    return jsonify({"success": True})

@app.route('/api/user/scan_qr', methods=['POST'])
def scan_qr():
    data = request.json
    qr_code = data.get('qr_code')
    scan_type = data.get('type') # in/out
    
    db._sync_mock_data()
    username = db.get_user_by_qr(qr_code)
    if not username:
        return jsonify({"success": False, "message": "Invalid QR Code"}), 400

    cmd_type = "ENTRY" if scan_type == "in" else "EXIT"
    cmd_id = db.add_remote_command(username, cmd_type)
    
    import time
    for _ in range(15):
        time.sleep(1)
        db._sync_mock_data()
        row = db.get_command_by_id(cmd_id)
        if row:
            if row['status'] == 'COMPLETED':
                return jsonify({"success": True, "message": row.get('result_msg', 'Mở barie thành công!')})
            elif row['status'] == 'FAILED':
                return jsonify({"success": False, "message": row.get('result_msg', 'Thao tác thất bại!')})
                
    return jsonify({"success": False, "message": "Quá thời gian, chưa thấy camera PC phản hồi!"})

@app.route('/api/user/active_sessions', methods=['GET'])
def get_user_active_sessions():
    username = request.args.get('username')
    if not username: return jsonify({"error": "Missing username"}), 400
    db._sync_mock_data()
    owned = db.get_owned_plates(username)
    all_sessions = db.data.get("active_sessions", {})
    history = db.get_history() # Sorted newest first
    
    user_sessions = []
    for plate in owned:
        if plate in all_sessions:
            s = all_sessions[plate]
            user_sessions.append({
                "plate": plate,
                "entry_time": s.get("entry_time"),
                "exit_time": "Đang ở trong bãi",
                "entry_image": s.get("entry_image")
            })
        else:
            # Tìm thời gian vào/ra gần nhất trong lịch sử
            entry_t = ""
            exit_t = ""
            for r in history:
                if r['plate'] == plate:
                    if "Ra" in r['type'] and not exit_t:
                        exit_t = r['time']
                    elif "Vào" in r['type'] and not entry_t:
                        entry_t = r['time']
                    
                    if entry_t and exit_t:
                        break
                        
            if entry_t or exit_t:
                user_sessions.append({
                    "plate": plate,
                    "entry_time": entry_t if entry_t else "Chưa ghi nhận",
                    "exit_time": exit_t if exit_t else "Chưa ghi nhận",
                    "entry_image": ""
                })
            
    return jsonify({"sessions": user_sessions})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
