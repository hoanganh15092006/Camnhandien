import cv2
import easyocr
import imutils
import numpy as np
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import threading
import queue
import datetime

from core.utils import four_point_transform, preprocess_crop
from core.ocr import process_plate, is_valid_plate
from core.detection import detect_plate_location
from data.database import ParkingDB, ENTRY_DIR, ACTIVE_DIR, EXIT_DIR
from ui.components import create_rounded_rect

class ManagerParkingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Hệ Thống Quản Lý Bãi Đỗ Xe")
        self.root.geometry("1200x800")
        self.root.configure(bg="#f4f6F9")
        
        self.db = ParkingDB()
        self.current_user = None # Typically manager accounts can be added later, for now just basic auth or none
        
        # Scanner thread state
        self.reader = None
        settings = self.db.get_camera_settings()
        self.cam_index = settings.get("cam_index", 0)
        self.ip_cam_url = settings.get("ip_cam_url", "")
        self._cap = None
        self._ocr_queue = queue.Queue(maxsize=1)
        self._result_queue = queue.Queue(maxsize=8)
        self._display_queue = queue.Queue(maxsize=2)
        
        self._stop_capture = threading.Event()
        self._stop_ocr = threading.Event()
        
        self.scan_mode = None 
        self.vote_text = None
        self.vote_count = 0
        self.vote_best_conf = 0.0
        self.vote_best_frame = None

        self.remote_target_plate = None
        self.remote_cmd_id = None
        self.root.after(2000, self._poll_remote_commands)
        
        # Sidebar Frame
        self.sidebar = tk.Frame(self.root, width=250, bg="#343a40")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        logo_lbl = tk.Label(self.sidebar, text="🚗 Smart Parking", font=("Segoe UI", 18, "bold"), bg="#343a40", fg="white", pady=20)
        logo_lbl.pack(fill="x")

        # Main Content Frame
        self.main_content = tk.Frame(self.root, bg="#f4f6F9")
        self.main_content.pack(side="right", fill="both", expand=True)

        self.frames = {}
        for F in ("Dashboard", "History", "Users"):
            frame = tk.Frame(self.main_content, bg="#f4f6F9")
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")
        
        self.main_content.grid_rowconfigure(0, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)

        self.build_sidebar_menu()
        self.build_dashboard_frame(self.frames["Dashboard"])
        self.build_history_frame(self.frames["History"])
        self.build_users_frame(self.frames["Users"])

        # Background OCR init
        threading.Thread(target=self._init_ocr, daemon=True).start()
        
        self.show_frame("Dashboard")

    def _init_ocr(self):
        self.reader = easyocr.Reader(['en'], gpu=False)

    def _poll_remote_commands(self):
        # Only process if we have an active scanner running for the correct command type
        if getattr(self, 'scan_mode', None) in ["ENTRY", "EXIT"]:
            try:
                cmd = self.db.get_pending_command(self.scan_mode)
                if cmd:
                    self.db.update_command_status(cmd['id'], 'PROCESSING')
                    self.remote_target_plate = cmd['qr_plate']
                    self.remote_cmd_id = cmd['id']
                    
                    if self.scan_mode == "ENTRY":
                        self.do_instant_entry_capture()
                    elif self.scan_mode == "EXIT":
                        self.do_instant_exit_capture()
            except Exception as e:
                pass
        self.root.after(1000, self._poll_remote_commands)

    def show_frame(self, name):
        if name == "History":
            self.refresh_history_list()
        elif name == "Dashboard":
            self.refresh_dashboard()
        elif name == "Users":
            self.refresh_users()
        frame = self.frames[name]
        frame.tkraise()
        # Reset sidebar active state
        for btn_name, btn in self.sidebar_btns.items():
            if btn_name == name:
                btn.config(bg="#007bff", fg="white")
            else:
                btn.config(bg="#343a40", fg="#c2c7d0")

    def build_sidebar_menu(self):
        self.sidebar_btns = {}
        menus = [("Tổng quan", "Dashboard", "📊"), ("Lịch sử xe", "History", "📋"), ("Khách hàng", "Users", "👥")]
        for text, frame_name, icon in menus:
            btn = tk.Button(self.sidebar, text=f"  {icon} {text}", font=("Segoe UI", 14), bg="#343a40", fg="#c2c7d0", 
                            bd=0, anchor="w", padx=20, pady=15, activebackground="#4b545c", activeforeground="white",
                            command=lambda f=frame_name: self.show_frame(f))
            btn.pack(fill="x")
            self.sidebar_btns[frame_name] = btn

    def refresh_dashboard(self):
        self.db._sync_mock_data()
        active_sessions = len(self.db.data.get("active_sessions", {}))
        self.dashboard_val_xe_trong_bai.config(text=f"{active_sessions}")
        
    def build_dashboard_frame(self, parent):
        header = tk.Label(parent, text="Tổng quan rào chắn & Bãi đỗ", font=("Segoe UI", 24, "bold"), bg="#f4f6F9", fg="#333333")
        header.pack(pady=20, padx=30, anchor="w")

        # Stats Row
        stats_frame = tk.Frame(parent, bg="#f4f6F9")
        stats_frame.pack(fill="x", padx=30, pady=10)

        # Card 1: Xe trong bãi
        card1 = tk.Frame(stats_frame, bg="white", highlightbackground="#d2d6de", highlightthickness=1)
        card1.pack(side="left", fill="both", expand=True, padx=(0, 15))
        tk.Label(card1, text="Xe Đang Trong Bãi", font=("Segoe UI", 12), bg="white", fg="#666").pack(pady=(15,0))
        self.dashboard_val_xe_trong_bai = tk.Label(card1, text="0", font=("Segoe UI", 28, "bold"), bg="white", fg="#007bff")
        self.dashboard_val_xe_trong_bai.pack(pady=(0,15))

        # Card 2: Sức chứa
        card2 = tk.Frame(stats_frame, bg="white", highlightbackground="#d2d6de", highlightthickness=1)
        card2.pack(side="left", fill="both", expand=True, padx=15)
        tk.Label(card2, text="Tổng Sức Chứa", font=("Segoe UI", 12), bg="white", fg="#666").pack(pady=(15,0))
        tk.Label(card2, text="500", font=("Segoe UI", 28, "bold"), bg="white", fg="#28a745").pack(pady=(0,15))

        # Control Panel
        control_frame = tk.Frame(parent, bg="white", highlightbackground="#d2d6de", highlightthickness=1)
        control_frame.pack(fill="both", expand=True, padx=30, pady=20)
        
        tk.Label(control_frame, text="Kiểm Soát Làn Xe", font=("Segoe UI", 18, "bold"), bg="white", fg="#333").pack(pady=20)

        btns_f = tk.Frame(control_frame, bg="white")
        btns_f.pack(pady=20)

        tk.Button(btns_f, text=" MỞ LÀN VÀO (IN) ", font=("Segoe UI", 16, "bold"), bg="#28a745", fg="white", padx=20, pady=15,
                  command=lambda: self.open_scanner("ENTRY")).pack(side="left", padx=20)
        
        tk.Button(btns_f, text=" MỞ LÀN RA (OUT) ", font=("Segoe UI", 16, "bold"), bg="#dc3545", fg="white", padx=20, pady=15,
                  command=lambda: self.open_scanner("EXIT")).pack(side="left", padx=20)

        self.status_lbl = tk.Label(control_frame, text="Trạng thái hệ thống: Sẵn sàng", font=("Segoe UI", 12, "italic"), bg="white", fg="#666")
        self.status_lbl.pack(pady=40)

    def refresh_history_list(self):
        for row in self.hist_tree.get_children(): self.hist_tree.delete(row)
        target = self.search_plate_var.get().strip().upper()
        history = self.db.get_history()
        # Sort history newer first
        history.reverse()
        for r in history:
            if not target or target in r['plate']:
                amt = f"{r['amount']:,}đ" if r.get('amount', 0) != 0 else "-"
                try: time_str = datetime.datetime.fromisoformat(r['time']).strftime("%d/%m %H:%M:%S")
                except: time_str = r['time']
                self.hist_tree.insert("", "end", values=(time_str, r['plate'], r['type'], amt, r.get('note', '')))

    def build_history_frame(self, parent):
        header = tk.Label(parent, text="Lịch Sử Giao Dịch", font=("Segoe UI", 24, "bold"), bg="#f4f6F9", fg="#333")
        header.pack(pady=20, padx=30, anchor="w")

        search_frame = tk.Frame(parent, bg="#f4f6F9")
        search_frame.pack(fill="x", padx=30, pady=5)
        tk.Label(search_frame, text="Biển số cần tra:", font=("Segoe UI", 12), bg="#f4f6F9", fg="#333").pack(side="left", padx=5)
        self.search_plate_var = tk.StringVar()
        entry = tk.Entry(search_frame, textvariable=self.search_plate_var, font=("Segoe UI", 12), width=30)
        entry.pack(side="left", padx=5)
        entry.bind("<Return>", lambda e: self.refresh_history_list())
        
        tk.Button(search_frame, text="Tìm kiếm", font=("Segoe UI", 12), bg="#007bff", fg="white", command=self.refresh_history_list).pack(side="left", padx=10)
        
        tree_frame = tk.Frame(parent, bg="white", highlightbackground="#d2d6de", highlightthickness=1)
        tree_frame.pack(fill="both", expand=True, padx=30, pady=10)
        
        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        
        columns = ("time", "plate", "type", "amount", "note")
        self.hist_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", yscrollcommand=y_scroll.set)
        y_scroll.config(command=self.hist_tree.yview)
        
        for c, t, w in zip(columns, ["Thời gian", "Biển số", "Loại", "Số tiền", "Ghi chú"], [150, 150, 120, 120, 300]):
            self.hist_tree.heading(c, text=t)
            self.hist_tree.column(c, width=w, stretch=tk.YES if c=="note" else tk.NO, anchor="center" if c!="note" else "w")
        self.hist_tree.pack(fill="both", expand=True)

    def refresh_users(self):
        for row in self.users_tree.get_children(): self.users_tree.delete(row)
        for acc in self.db.data.get("accounts", {}).keys():
            balance = self.db.get_balance(acc)
            owned = self.db.get_owned_plates(acc)
            self.users_tree.insert("", "end", values=(acc, f"{balance:,}đ", ", ".join(owned)))

    def build_users_frame(self, parent):
        header = tk.Label(parent, text="Quản Lý Khách Hàng", font=("Segoe UI", 24, "bold"), bg="#f4f6F9", fg="#333")
        header.pack(pady=20, padx=30, anchor="w")

        top_f = tk.Frame(parent, bg="#f4f6F9")
        top_f.pack(fill="x", padx=30, pady=5)
        tk.Button(top_f, text="Nạp tiền thủ công", font=("Segoe UI", 12), bg="#28a745", fg="white", command=self.open_topup).pack(side="right")

        tree_frame = tk.Frame(parent, bg="white", highlightbackground="#d2d6de", highlightthickness=1)
        tree_frame.pack(fill="both", expand=True, padx=30, pady=10)
        
        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical")
        y_scroll.pack(side="right", fill="y")
        
        columns = ("user", "balance", "plates")
        self.users_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", yscrollcommand=y_scroll.set)
        y_scroll.config(command=self.users_tree.yview)
        
        self.users_tree.heading("user", text="Tài khoản")
        self.users_tree.column("user", width=200, anchor="center")
        self.users_tree.heading("balance", text="Số dư Ví")
        self.users_tree.column("balance", width=150, anchor="center")
        self.users_tree.heading("plates", text="Biển số đã đăng ký")
        self.users_tree.column("plates", width=400, stretch=tk.YES)
        
        self.users_tree.pack(fill="both", expand=True)

    def set_status(self, text):
        self.status_lbl.config(text=f"Trạng thái: {text}")

    def open_topup(self):
        acc = simpledialog.askstring("Nạp tiền", "Nhập tên tài khoản (Khách hàng):", parent=self.root)
        if acc:
            acc = acc.strip()
            if acc not in self.db.data.get("accounts", {}): messagebox.showerror("Lỗi", "Tài khoản chưa tồn tại!"); return
            amt_s = simpledialog.askstring("Nạp tiền", f"Số tiền nạp cho {acc}:", parent=self.root)
            if amt_s and amt_s.isdigit():
                amt = int(amt_s); nb = self.db.add_balance(acc, amt)
                self.db.add_history_record(acc, "Nạp Tiền", amt, datetime.datetime.now().isoformat(), note=f"Hệ thống nạp +{amt:,}đ")
                messagebox.showinfo("OK", f"Đã nạp {amt:,}đ. Dư: {nb:,}đ")
                self.refresh_users()

    def open_scanner(self, mode):
        if not self.reader: 
            messagebox.showwarning("Chờ", "Hệ thống AI đang khởi động..."); return
            
        if hasattr(self, 'scan_win') and self.scan_win.winfo_exists():
            if self.scan_mode == mode:
                self.scan_win.lift()
                self.scan_win.focus_force()
                return
            else:
                self.close_scanner()
                
        self.scan_mode = mode
        self.vote_text, self.vote_count, self.vote_best_conf, self.vote_best_frame = None, 0, 0.0, None
        
        v = tk.Toplevel(self.root)
        v.title(f"Quét {'VÀO' if mode=='ENTRY' else 'RA'}")
        v.geometry("700x550")
        v.configure(bg="#2d3436")
        v.grab_set()
        self.scan_win = v
        
        header_text = "CAMERA KIỂM SOÁT XE VÀO" if mode == "ENTRY" else "CAMERA KIỂM SOÁT XE RA"
        tk.Label(v, text=header_text, bg="#2d3436", fg="white", font=("Segoe UI",16,"bold")).pack(pady=10)
        
        self.cam_label = tk.Label(v, bg="black")
        self.cam_label.pack(fill="both", expand=True, padx=20, pady=5)
        
        self.cam_status_var = tk.StringVar(value="Đang mở...")
        tk.Label(v, textvariable=self.cam_status_var, bg="#2d3436", fg="#00b894", font=("Segoe UI", 12)).pack(pady=5)
        
        bf = tk.Frame(v, bg="#2d3436")
        bf.pack(pady=10)
        
        tk.Button(bf, text="✖ Hủy & Đóng", command=self.close_scanner, bg="#d63031", fg="white", font=("Segoe UI",12)).pack(side="left", padx=10)
        tk.Button(bf, text="⌨ Nhập tay (Sự cố)", command=self.manual_override, bg="#0984e3", fg="white", font=("Segoe UI",12)).pack(side="left", padx=10)
        tk.Button(bf, text="💻 PC Cam", command=lambda: self._set_cam(0), bg="#00b894", fg="white", font=("Segoe UI",12)).pack(side="left", padx=10)
        tk.Button(bf, text="📱 IP Cam", command=self._set_ip, bg="#e17055", fg="white", font=("Segoe UI",12)).pack(side="left", padx=10)
        
        self._start_camera()

    def _set_cam(self, idx): self.cam_index = idx; self.db.save_camera_settings(idx, self.ip_cam_url); self._start_camera()
    def _set_ip(self):
        u = simpledialog.askstring("IP Cam", "Nhập URL:", initialvalue=self.ip_cam_url)
        if u: self.ip_cam_url, self.cam_index = u, -1; self.db.save_camera_settings(-1, u); self._start_camera()

    def _start_camera(self):
        self._stop_capture.set(); self._stop_ocr.set(); import time; time.sleep(0.15)
        self._stop_capture.clear(); self._stop_ocr.clear()
        
        def w():
            cap = cv2.VideoCapture(self.ip_cam_url if self.cam_index==-1 else self.cam_index, cv2.CAP_DSHOW)
            if not cap.isOpened(): self.cam_status_var.set("❌ Lỗi camera!"); return
            self._cap = cap; self.cam_status_var.set("AI đang phân tích luồng hình ảnh...")
            threading.Thread(target=self._cap_loop, args=(cap,), daemon=True).start()
            threading.Thread(target=self._ocr_loop, daemon=True).start()
            self._poll_display()
            self._poll_results()
            
        threading.Thread(target=w, daemon=True).start()

    def _cap_loop(self, cap):
        skip = 0
        while not self._stop_capture.is_set():
            ret, frame = cap.read()
            if not ret: break
            try: self._display_queue.get_nowait()
            except: pass
            self._display_queue.put_nowait(frame)
            skip += 1
            if skip >= 3 and self._ocr_queue.empty():
                skip, small = 0, imutils.resize(frame, width=400)
                loc = detect_plate_location(small)
                self._ocr_queue.put_nowait((frame.copy(), cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), loc, frame.shape[1]/small.shape[1]))

    def _ocr_loop(self):
        while not self._stop_ocr.is_set():
            try: f, g, loc, s = self._ocr_queue.get(timeout=0.5)
            except: continue
            text, conf, ann = None, 0.0, f.copy()
            if loc is not None:
                try:
                    pts = loc.reshape(4,2).astype("float32") * s
                    crop = four_point_transform(f, pts)
                    res = self.reader.readtext(preprocess_crop(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)), allowlist='0123456789ABCDEFGHJKLMNPRSTUVWXYZ.- ')
                    p = process_plate(res)
                    if p and is_valid_plate(p):
                        conf = sum(r[2] for r in res)/len(res)
                        if conf >= 0.6: text = p; pi = (loc*s).astype(int); cv2.polylines(ann, [pi], True, (0,255,0), 3)
                except: pass
            try: self._result_queue.put_nowait((text, conf, ann))
            except: pass

    def _poll_display(self):
        if self._stop_capture.is_set() or not hasattr(self, 'scan_win') or not self.scan_win.winfo_exists(): return
        try:
            f = self._display_queue.get_nowait()
            p = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)).resize((640,400)))
            self.cam_label.configure(image=p); self.cam_label.image = p
        except: pass
        self.scan_win.after(30, self._poll_display)

    def _poll_results(self):
        if self._stop_ocr.is_set() or not hasattr(self, 'scan_win') or not self.scan_win.winfo_exists(): return
        try:
            t, c, a = self._result_queue.get_nowait()
            self.current_seen_frame = a
            
            if t:
                self.cam_status_var.set(f"🔍 Đang xem biển số: {t} (Chờ lệnh App)")
                
                # Check stable plate voting
                if t == getattr(self, 'vote_text', None):
                    self.vote_count += 1
                else:
                    self.vote_text, self.vote_count = t, 1
                    
                if self.vote_count >= 2:
                    self.stable_plate = t
            else:
                if getattr(self, 'vote_count', 0) > 0:
                    self.vote_count -= 1
                if getattr(self, 'vote_count', 0) <= 0:
                    self.stable_plate = None
                    self.vote_text = None
            
            # EXIT is now handled by do_instant_exit_capture
        except: pass
        self.scan_win.after(100, self._poll_results)

    def manual_override(self):
        p = simpledialog.askstring("Nhập tay", "Nhập biển số:", parent=self.scan_win)
        if p and is_valid_plate(p.strip().upper()): self.process_scan_result(p.strip().upper(), None)

    def do_instant_entry_capture(self):
        import time
        t = getattr(self, 'stable_plate', None)
        if not t: t = getattr(self, 'vote_text', None)
        
        if not t:
            t = simpledialog.askstring("Sự Cố Camera IN", "Camera không nhận ra biển số!\nXin bảo vệ nhập thủ công bằng mắt thường:", parent=self.scan_win)
            if not t:
                self.set_status("Bảo vệ hủy quy trình nhập IN.")
                self.db.update_command_status(self.remote_cmd_id, 'FAILED', "Bảo vệ từ chối xe Vô Danh từ trạm PC.")
                self.remote_target_plate = None
                return
            t = t.strip().upper()
            
        f = getattr(self, 'current_seen_frame', None)
        if f is None and hasattr(self, '_cap') and self._cap is not None:
             ret, f = self._cap.read()
        
        if f is None and not self._display_queue.empty():
            try: f = self._display_queue.get_nowait()
            except: pass
            
        ann = f.copy() if f is not None else None
        
        self.handle_entry(t, ann, linked_user=self.remote_target_plate)
        self.db.update_command_status(self.remote_cmd_id, 'COMPLETED', f"Biển số '{t}' đã vào bãi an toàn!")
        self.set_status(f"Xe {t} mới vào lúc {datetime.datetime.now().strftime('%H:%M')} (Lập tức ghi hình)")
        
        self.remote_target_plate = None
        self.stable_plate = None
        self.vote_text = None

    def do_instant_exit_capture(self):
        t = getattr(self, 'stable_plate', None)
        if not t: t = getattr(self, 'vote_text', None)
        
        target_user = self.remote_target_plate
        import datetime
        fee = 5000 if datetime.datetime.now().hour >= 18 else 3000
        
        if not t or t.startswith("KHONG_BKS"):
            # Predict the plate for the guard based on active sessions
            active_for_user = [p for p in self.db.get_owned_plates(target_user) if self.db.get_session(p)]
            suggest = active_for_user[0] if len(active_for_user) == 1 else ""
            
            t = simpledialog.askstring("Sự Cố Camera OUT", f"Không rõ biển số. Khách hàng '{target_user}' đang chờ!\nHãy gõ biển số xe để trừ tiền vào App:", initialvalue=suggest, parent=self.scan_win)
            
            if not t:
                self.set_status("Hủy nhập tay OUT!")
                self.db.update_command_status(self.remote_cmd_id, 'FAILED', "Thất bại: Camera vướng & Bảo vệ hủy nhập tay.")
                self.remote_target_plate, self.stable_plate, self.vote_text = None, None, None
                return
            t = t.strip().upper()

        owned = self.db.get_owned_plates(target_user)
        if t in owned:
            if self.db.get_session(t):
                if self.db.get_balance(target_user) >= fee:
                    self.db.deduct_balance(target_user, fee)
                    self.db.end_session(t)
                    self.db.add_history_record(t, "Xe Ra (App)", -fee, datetime.datetime.now().isoformat(), note=f"App: Trừ {fee:,}đ")
                    self.set_status(f"Ra thành công: {t}")
                    self.db.update_command_status(self.remote_cmd_id, 'COMPLETED', f"Mở barie thành công! Xe '{t}' đã ra bãi. Trừ {fee:,}đ.")
                else:
                    self.set_status(f"Từ chối: {target_user} không đủ {fee:,}đ!")
                    self.db.update_command_status(self.remote_cmd_id, 'FAILED', f"Tài khoản không đủ cước (Cần {fee:,}đ). Nạp thêm để ra.")
            else:
                self.db.update_command_status(self.remote_cmd_id, 'FAILED', f"Lỗi: Biển số '{t}' hiện KHÔNG có trong bãi.")
        else:
            self.db.update_command_status(self.remote_cmd_id, 'FAILED', f"Nhầm xe! Xe '{t}' trước mặt không phải của tài khoản '{target_user}'.")
            
        self.remote_target_plate = None
        self.stable_plate = None
        self.vote_text = None
        self.refresh_dashboard()

    def process_scan_result(self, p, f, linked_user=None):
        if self.scan_mode == "ENTRY": self.handle_entry(p, f, linked_user)
        else: 
            self._stop_capture.set(); self._stop_ocr.set() # Stop for manual exit window
            self.handle_exit(p, f)

    def handle_entry(self, p, f, linked_user=None):
        if self.db.get_session(p): 
            print(f"Xe {p} đã trong bãi, bỏ qua")
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(ACTIVE_DIR, f"{p}_{ts}.png")
            if f is not None: 
                cv2.imwrite(path, f)
                cv2.imwrite(os.path.join(ENTRY_DIR, f"{p}_{ts}.png"), f)
            
            self.db.start_session(p, path if f is not None else "")
            
            note_str = ""
            if linked_user:
                self.db.link_plate(linked_user, p)
                note_str = f"App Liên kết: {linked_user}"
                
            self.db.add_history_record(p, "Xe Vào", 0, datetime.datetime.now().isoformat(), note=note_str)
            self.set_status(f"Xe {p} mới vào lúc {datetime.datetime.now().strftime('%H:%M')} (Cam đang mở)")
        # KHÔNG GỌI close_scanner() để camera tiếp tục mở
        self.refresh_dashboard()

    def process_remote_exit(self, p, f, paying_user):
        s = self.db.get_session(p)
        if not s: 
            return
            
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        exp = os.path.join(EXIT_DIR, f"{p}_{ts}.png")
        if f is not None: cv2.imwrite(exp, f)

        now = datetime.datetime.now(); fee = 5000 if now.hour >= 18 else 3000
        if self.db.get_balance(paying_user) >= fee:
            self.db.deduct_balance(paying_user, fee)
            self.db.end_session(p)
            self.db.add_history_record(p, "Xe Ra (App)", -fee, now.isoformat(), note=f"Trừ {fee:,}đ từ ví {paying_user}")
            self.set_status(f"Xe {p} ra thành công (Remote by {paying_user}) (Cam đang mở)")
        else:
            # Not enough money? Still keep camera open but log it
            print(f"Tài khoản {paying_user} không đủ tiền để tự động ra bãi!")
            
        self.refresh_dashboard()

    def handle_exit(self, p, f):
        s = self.db.get_session(p)
        if not s: 
            messagebox.showerror("Lỗi", "Không tìm thấy xe trong bãi!")
            self.close_scanner()
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        exp = os.path.join(EXIT_DIR, f"{p}_{ts}.png")
        if f is not None: cv2.imwrite(exp, f)

        v = tk.Toplevel(self.root)
        v.title("Kiểm tra thông tin - Xác nhận xe ra")
        v.geometry("750x450")
        v.configure(bg="#f4f6F9")
        v.grab_set()

        lbl_tit = tk.Label(v, text=f"Biển số: {p}", font=("Segoe UI", 18, "bold"), bg="#f4f6F9")
        lbl_tit.pack(pady=10)

        img_frame = tk.Frame(v, bg="#f4f6F9")
        img_frame.pack()
        try:
            p1 = ImageTk.PhotoImage(Image.open(s.get("entry_image")).resize((300, 200)))
            tk.Label(img_frame, image=p1, text="Ảnh lúc VÀO", compound="top", font=("Segoe UI", 12), bg="white").pack(side="left", padx=10)
            img_frame.p1 = p1
            
            p2 = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)).resize((300, 200))) if f is not None else None
            if p2:
                tk.Label(img_frame, image=p2, text="Ảnh lúc RA", compound="top", font=("Segoe UI", 12), bg="white").pack(side="right", padx=10)
                img_frame.p2 = p2
        except: pass
        
        now = datetime.datetime.now(); fee = 5000 if now.hour >= 18 else 3000
        tk.Label(v, text=f"Phí gửi xe: {fee:,}đ", font=("Segoe UI", 18, "bold"), fg="#dc3545", bg="#f4f6F9").pack(pady=10)

        def confirm(method):
            # Check if linked account can pay
            acc = None
            for key_acc, info in self.db.data.get("accounts", {}).items():
                if p in self.db.get_owned_plates(key_acc) or key_acc == p:
                    acc = key_acc
                    break
            
            if acc and method == "APP":
                if self.db.get_balance(acc) >= fee:
                    self.db.deduct_balance(acc, fee)
                    self.db.end_session(p)
                    self.db.add_history_record(p, "Xe Ra (Thay toán ví)", -fee, now.isoformat(), note=f"Trừ {fee:,}đ vào ví {acc}")
                    self.set_status(f"Xe {p} ra thành công (TT Ví)")
                else: 
                    messagebox.showwarning("!", f"Tài khoản {acc} không đủ tiền, thu tiền mặt!")
                    return
            else:
                self.db.end_session(p)
                self.db.add_history_record(p, "Xe Ra (Tiền mặt)", -fee, now.isoformat(), note=f"Thu {fee:,}đ tiền mặt")
                self.set_status(f"Xe {p} ra thành công (Tiền mặt)")

            v.destroy()
            self.close_scanner()
            self.refresh_dashboard()

        bf = tk.Frame(v, bg="#f4f6F9")
        bf.pack(pady=10)
        tk.Button(bf, text="Thu tiền qua APP (Ví)", font=("Segoe UI", 12), bg="#007bff", fg="white", padx=10, command=lambda: confirm("APP")).pack(side="left", padx=10)
        tk.Button(bf, text="Thu Tiền Mặt", font=("Segoe UI", 12), bg="#28a745", fg="white", padx=10, command=lambda: confirm("CASH")).pack(side="left", padx=10)
        tk.Button(bf, text="Hủy", font=("Segoe UI", 12), bg="#6c757d", fg="white", padx=10, command=v.destroy).pack(side="left", padx=10)

    def close_scanner(self):
        self._stop_capture.set(); self._stop_ocr.set(); 
        if self._cap: self._cap.release(); self._cap = None
        if hasattr(self, 'scan_win') and self.scan_win.winfo_exists(): self.scan_win.destroy()

