import cv2
import easyocr
import imutils
import numpy as np
import re
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk, ImageDraw
import threading
import queue
import datetime
import json
import time

# Import OCR helpers from main.py
try:
    from main import (
        four_point_transform, is_valid_plate, process_plate, detect_plate_location, preprocess_crop
    )
except ImportError:
    messagebox.showerror("Error", "Could not import from main.py. Make sure main.py is in the same folder.")
    exit(1)

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
        # Keep only the last 50 records
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


def create_rounded_rect(canvas, x1, y1, x2, y2, radius=25, **kwargs):
    points = [x1+radius, y1,
              x1+radius, y1,
              x2-radius, y1,
              x2-radius, y1,
              x2, y1,
              x2, y1+radius,
              x2, y1+radius,
              x2, y2-radius,
              x2, y2-radius,
              x2, y2,
              x2-radius, y2,
              x2-radius, y2,
              x1+radius, y2,
              x1+radius, y2,
              x1, y2,
              x1, y2-radius,
              x1, y2-radius,
              x1, y1+radius,
              x1, y1+radius,
              x1, y1]
    return canvas.create_polygon(points, **kwargs, smooth=True)


class MobileParkingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Parking App")
        # Doubled width for desktop view
        self.root.geometry("900x850")
        self.root.resizable(False, False)
        
        self.db = ParkingDB()
        self.current_user = None
        
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
        
        self.scan_mode = None # "ENTRY" or "EXIT"
        self.vote_text = None
        self.vote_count = 0
        self.vote_best_conf = 0.0
        self.vote_best_frame = None
        
        
        # Main Container Frame
        self.main_frame = tk.Frame(self.root, width=900, height=850, bg="#1e1e2e")
        self.main_frame.pack(fill="both", expand=True)

        self.frames = {}
        for F in ("Home", "History", "Info"):
            frame = tk.Frame(self.main_frame, width=900, height=850, bg="#1e1e2e")
            self.frames[F] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.build_home_frame(self.frames["Home"])
        self.build_history_frame(self.frames["History"])
        self.build_info_frame(self.frames["Info"])

        self.build_bottom_nav()
        
        # Load OCR in background to not freeze UI
        threading.Thread(target=self._init_ocr, daemon=True).start()
        
        self.show_frame("Home")

    def _init_ocr(self):
        self.reader = easyocr.Reader(['en'], gpu=False)

    def show_frame(self, name):
        if name == "History":
            self.refresh_history_list()
        frame = self.frames[name]
        frame.tkraise()
        # Bring bottom nav on top
        if hasattr(self, 'nav_canvas_frame'):
            self.nav_canvas_frame.tkraise()

    def build_bottom_nav(self):
        self.nav_canvas_frame = tk.Frame(self.root, width=900, height=80, bg="white")
        self.nav_canvas_frame.place(x=0, y=770)
        self.nav_canvas = tk.Canvas(self.nav_canvas_frame, width=900, height=80, bg="white", highlightthickness=0)
        self.nav_canvas.pack(fill="both", expand=True)
        create_rounded_rect(self.nav_canvas, 0, 0, 900, 80, radius=0, fill="white", outline="")
        
        # 3 evenly spaced tabs on 900px
        w = 900 // 3
        # Home (Trang chủ)
        self.nav_canvas.create_rectangle(0, 0, w, 80, fill="white", outline="", tags="nav_home")
        self.nav_canvas.create_text(w//2, 40, text="🏠\nTrang chủ", font=("Segoe UI", 12), justify="center", fill="#1a73e8", tags="nav_home")
        self.nav_canvas.tag_bind("nav_home", "<Button-1>", lambda e: self.show_frame("Home"))
        
        # History (Tra cứu)
        self.nav_canvas.create_rectangle(w, 0, w*2, 80, fill="white", outline="", tags="nav_hist")
        self.nav_canvas.create_text(w + w//2, 40, text="📋\nTra cứu", font=("Segoe UI", 12), justify="center", fill="#808080", tags="nav_hist")
        self.nav_canvas.tag_bind("nav_hist", "<Button-1>", lambda e: self.show_frame("History"))
        
        # Info (Tài khoản)
        self.nav_canvas.create_rectangle(w*2, 0, w*3, 80, fill="white", outline="", tags="nav_info")
        self.nav_canvas.create_text(w*2 + w//2, 40, text="👤\nTài khoản", font=("Segoe UI", 12), justify="center", fill="#808080", tags="nav_info")
        self.nav_canvas.tag_bind("nav_info", "<Button-1>", lambda e: self.show_frame("Info"))

    def build_home_frame(self, parent_frame):
        # Main Canvas for gradient / background
        self.bg_canvas = tk.Canvas(parent_frame, width=900, height=850, highlightthickness=0)
        self.bg_canvas.pack(fill="both", expand=True)
        
        # Draw gradient manually (approximate) - Span 900px
        color_top = "#9CbCBC"
        color_bottom = "#D8E6E3"
        for i in range(850):
            # linear interpolation
            r = int(int(color_top[1:3], 16) * (1 - i/850) + int(color_bottom[1:3], 16) * (i/850))
            g = int(int(color_top[3:5], 16) * (1 - i/850) + int(color_bottom[3:5], 16) * (i/850))
            b = int(int(color_top[5:7], 16) * (1 - i/850) + int(color_bottom[5:7], 16) * (i/850))
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.bg_canvas.create_line(0, i, 900, i, fill=color)

        # Header Location Box - Wide for 900px
        create_rounded_rect(self.bg_canvas, 100, 20, 800, 90, radius=20, fill="white", outline="")
        self.bg_canvas.create_text(160, 40, text="Ga gần nhất:", font=("Segoe UI", 16, "bold"), anchor="w", fill="#202020")
        self.bg_canvas.create_text(160, 65, text="Tòa nhà Trung Tâm Đỗ Xe", font=("Segoe UI", 11), anchor="w", fill="#808080")
        # Location Icon placeholder
        self.bg_canvas.create_oval(115, 40, 145, 70, fill="#E0E0E0", outline="")
        self.bg_canvas.create_text(130, 55, text="📍", font=("Segoe UI", 16))

        # 3 Action Buttons (Xe Vào, Xe Ra, Nạp Tiền)
        # 3 Action Buttons - Spaced across 900px
        # Center points: 225, 450, 675
        
        # Btn 1 - ENTRY
        create_rounded_rect(self.bg_canvas, 165, 110, 285, 230, radius=15, fill="white", outline="#cccccc", width=2, tags="btn1")
        self.bg_canvas.create_rectangle(195, 130, 255, 190, fill="#f2b24c", outline="", width=0, tags="btn1") # Orange box
        self.bg_canvas.create_text(225, 160, text="IN", font=("Segoe UI", 20, "bold"), fill="white", tags="btn1")
        self.bg_canvas.create_text(225, 210, text="Xe Vào", font=("Segoe UI", 12, "bold"), fill="#202020", tags="btn1")
        self.bg_canvas.tag_bind("btn1", "<Button-1>", lambda e: self.open_scanner("ENTRY"))
        
        # Btn 2 - EXIT
        create_rounded_rect(self.bg_canvas, 390, 110, 510, 230, radius=15, fill="white", outline="#cccccc", width=2, tags="btn2")
        self.bg_canvas.create_rectangle(420, 130, 480, 190, fill="#f07865", outline="", width=0, tags="btn2") # Red box
        self.bg_canvas.create_text(450, 160, text="OUT", font=("Segoe UI", 20, "bold"), fill="white", tags="btn2")
        self.bg_canvas.create_text(450, 210, text="Xe Ra", font=("Segoe UI", 12, "bold"), fill="#202020", tags="btn2")
        self.bg_canvas.tag_bind("btn2", "<Button-1>", lambda e: self.open_scanner("EXIT"))
        
        # Btn 3 - TOP-UP
        create_rounded_rect(self.bg_canvas, 615, 110, 735, 230, radius=15, fill="white", outline="#cccccc", width=2, tags="btn3")
        self.bg_canvas.create_rectangle(645, 130, 705, 190, fill="#40bced", outline="", width=0, tags="btn3") # Blue box
        self.bg_canvas.create_text(675, 160, text="$", font=("Segoe UI", 24, "bold"), fill="white", tags="btn3")
        self.bg_canvas.create_text(675, 210, text="Nạp tiền", font=("Segoe UI", 12, "bold"), fill="#202020", tags="btn3")
        self.bg_canvas.tag_bind("btn3", "<Button-1>", lambda e: self.open_topup())

        # HÀNH TRÌNH CỦA BẠN box - Expanded
        create_rounded_rect(self.bg_canvas, 50, 250, 850, 360, radius=15, fill="white", outline="")
        self.bg_canvas.create_text(70, 275, text="HÀNH TRÌNH CỦA BẠN", font=("Segoe UI", 14, "bold"), anchor="w", fill="#18434a")
        
        self.journey_text_id = self.bg_canvas.create_text(100, 320, text="Chưa có xe trong bãi", font=("Segoe UI", 13), anchor="w", fill="#e66f36")
        self.bg_canvas.create_text(75, 320, text="🍂", font=("Segoe UI", 14), anchor="w")

        # Tin tức & chương trình
        self.bg_canvas.create_text(50, 400, text="Tin tức & chương trình", font=("Segoe UI", 16, "bold"), anchor="w", fill="#202020")
        
        # Dummy Banner 1 - Left half
        create_rounded_rect(self.bg_canvas, 50, 430, 440, 530, radius=15, fill="#cc3333", outline="")
        self.bg_canvas.create_text(245, 480, text="Ưu đãi Gửi xe tháng", font=("Segoe UI", 14, "bold"), fill="white", justify="center")
        
        # Dummy Banner 2 - Right half
        create_rounded_rect(self.bg_canvas, 460, 430, 850, 530, radius=15, fill="#2b4c7e", outline="")
        self.bg_canvas.create_text(655, 480, text="Q&A Hướng dẫn", font=("Segoe UI", 14, "bold"), fill="white", justify="center")
        
        # Dummy Banner 3 - Full width
        create_rounded_rect(self.bg_canvas, 50, 550, 850, 650, radius=15, fill="#0f7c46", outline="")
        self.bg_canvas.create_text(450, 600, text="HÀNH TRÌNH XANH - Tích điểm đổi quà", font=("Segoe UI", 16, "bold"), fill="white", justify="center")

    def build_history_frame(self, parent_frame):
        tk.Label(parent_frame, text="Tra Cứu Lịch Sử Giao Dịch", font=("Segoe UI", 20, "bold"), bg="#1e1e2e", fg="white").pack(pady=20)
        
        # Search Bar Area
        search_frame = tk.Frame(parent_frame, bg="#1e1e2e")
        search_frame.pack(pady=5)
        
        tk.Label(search_frame, text="Biển số cần tra:", font=("Segoe UI", 12), bg="#1e1e2e", fg="white").pack(side="left", padx=5)
        self.search_plate_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=self.search_plate_var, font=("Segoe UI", 12), width=25).pack(side="left", padx=5)
        tk.Button(search_frame, text="Tìm", font=("Segoe UI", 10, "bold"), bg="#89b4fa", fg="#1e1e2e", width=8, command=self.refresh_history_list).pack(side="left", padx=5)
        
        # Button to show all history of owned plates
        tk.Button(search_frame, text="Tất cả xe", font=("Segoe UI", 10, "bold"), bg="#a6e3a1", fg="#1e1e2e", command=self.show_all_owned_history).pack(side="left", padx=5)
        
        self.hist_msg_var = tk.StringVar(value="")
        tk.Label(parent_frame, textvariable=self.hist_msg_var, font=("Segoe UI", 12, "italic"), bg="#1e1e2e", fg="#f38ba8").pack(pady=5)
        
        # Create a frame to hold treeview + scrollbars
        tree_frame = tk.Frame(parent_frame, bg="#1e1e2e")
        tree_frame.pack(fill="both", expand=True, padx=10)
        
        # Horizontal scrollbar
        h_scroll = ttk.Scrollbar(tree_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")
        
        # Create a treeview for history
        columns = ("time", "plate", "type", "amount", "note")
        self.hist_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=18, xscrollcommand=h_scroll.set)
        h_scroll.config(command=self.hist_tree.xview)
        
        self.hist_tree.heading("time", text="Thời gian")
        self.hist_tree.heading("plate", text="Biển số")
        self.hist_tree.heading("type", text="Loại")
        self.hist_tree.heading("amount", text="Số tiền")
        self.hist_tree.heading("note", text="Ghi chú")
        
        self.hist_tree.column("time", width=120, stretch=tk.NO, anchor="center")
        self.hist_tree.column("plate", width=120, stretch=tk.NO, anchor="center")
        self.hist_tree.column("type", width=100, stretch=tk.NO, anchor="center")
        self.hist_tree.column("amount", width=100, stretch=tk.NO, anchor="e")
        self.hist_tree.column("note", width=350, stretch=tk.NO, anchor="w")
        
        self.hist_tree.pack(fill="both", expand=True)

        # Disable interactive column resizing by trapping the <Button-1> on separators
        # (Separators in Treeview are identified by being on the 'separator' element)
        def disable_resize(event):
            if self.hist_tree.identify_region(event.x, event.y) == "separator":
                return "break"
        self.hist_tree.bind("<Button-1>", disable_resize, add="+")

        # Implement SWIPE (Drag-to-scroll)
        self._drag_start_x = 0
        def on_drag_start(event):
            self._drag_start_x = event.x
        
        def on_drag_motion(event):
            delta = self._drag_start_x - event.x
            self.hist_tree.xview_scroll(delta, "units")
            self._drag_start_x = event.x

        self.hist_tree.bind("<Button-1>", on_drag_start, add="+")
        self.hist_tree.bind("<B1-Motion>", on_drag_motion)

    def show_all_owned_history(self):
        """Show history for all plates linked to the current account."""
        for row in self.hist_tree.get_children():
            self.hist_tree.delete(row)
            
        if not self.current_user:
            self.hist_msg_var.set("Vui lòng đăng nhập ở tab Tài khoản để tra cứu.")
            return
            
        owned = self.db.get_owned_plates(self.current_user)
        # Also include the account name itself (for deposit records)
        all_keys = set(owned + [self.current_user])
        
        if not owned:
            self.hist_msg_var.set(f"Tài khoản {self.current_user} chưa có xe nào được liên kết.")
        else:
            plates_str = ", ".join(owned)
            self.hist_msg_var.set(f"Xe của bạn: {plates_str}")
        
        hist = self.db.get_history()
        for r in hist:
            if r['plate'] not in all_keys:
                continue
            amt_str = f"{r['amount']:,}đ" if r['amount'] > 0 else ("-" if r['amount'] == 0 else f"{r['amount']:,}đ")
            note = r.get('note', '')
            try:
                time_obj = datetime.datetime.fromisoformat(r['time'])
                time_str = time_obj.strftime("%d/%m %H:%M")
            except:
                time_str = r['time']
            self.hist_tree.insert("", "end", values=(time_str, r['plate'], r['type'], amt_str, note))

    def refresh_history_list(self):
        for row in self.hist_tree.get_children():
            self.hist_tree.delete(row)
            
        if not self.current_user:
            self.hist_msg_var.set("Vui lòng đăng nhập ở tab Tài khoản để tra cứu.")
            return
            
        target_plate = self.search_plate_var.get().strip().upper()
        if not target_plate:
            # If no search text, show all owned plates
            self.show_all_owned_history()
            return
            
        self.hist_msg_var.set(f"Lịch sử của xe: {target_plate}")
        hist = self.db.get_history()
        for r in hist:
            if r['plate'] != target_plate:
                continue
                
            amt_str = f"{r['amount']:,}đ" if r['amount'] > 0 else ("-" if r['amount'] == 0 else f"{r['amount']:,}đ")
            note = r.get('note', '')
            try:
                time_obj = datetime.datetime.fromisoformat(r['time'])
                time_str = time_obj.strftime("%d/%m %H:%M")
            except:
                time_str = r['time']
            self.hist_tree.insert("", "end", values=(time_str, r['plate'], r['type'], amt_str, note))


    def build_info_frame(self, parent_frame):
        self.info_frame_container = parent_frame
        self.render_info_content()
        
    def render_info_content(self):
        for widget in self.info_frame_container.winfo_children():
            widget.destroy()
            
        tk.Label(self.info_frame_container, text="Tài Khoản", font=("Segoe UI", 20, "bold"), bg="#1e1e2e", fg="white").pack(pady=30)
        
        if self.current_user is None:
            # Show Login Form
            tk.Label(self.info_frame_container, text="Bạn chưa đăng nhập. Vui lòng đăng nhập\nhoặc đăng ký theo tên tài khoản bất kỳ.", font=("Segoe UI", 12), bg="#1e1e2e", fg="#a6adc8").pack(pady=10)
            
            form_frame = tk.Frame(self.info_frame_container, bg="#313244", padx=20, pady=20)
            form_frame.pack(pady=20)
            
            tk.Label(form_frame, text="Tài khoản:", font=("Segoe UI", 12), bg="#313244", fg="white").grid(row=0, column=0, pady=5, sticky="w")
            self.login_plate_var = tk.StringVar()
            tk.Entry(form_frame, textvariable=self.login_plate_var, font=("Segoe UI", 12), width=25).grid(row=0, column=1, pady=5, padx=10)
            
            tk.Label(form_frame, text="Mật khẩu:", font=("Segoe UI", 12), bg="#313244", fg="white").grid(row=1, column=0, pady=5, sticky="w")
            self.login_pass_var = tk.StringVar()
            tk.Entry(form_frame, textvariable=self.login_pass_var, show="*", font=("Segoe UI", 12), width=25).grid(row=1, column=1, pady=5, padx=10)
            
            btn_frame = tk.Frame(form_frame, bg="#313244")
            btn_frame.grid(row=2, column=0, columnspan=2, pady=20)
            
            tk.Button(btn_frame, text="Đăng nhập", font=("Segoe UI", 12, "bold"), bg="#89b4fa", fg="#1e1e2e", width=15, command=self.do_login).pack(side="left", padx=10)
            tk.Button(btn_frame, text="Đăng ký", font=("Segoe UI", 12, "bold"), bg="#a6e3a1", fg="#1e1e2e", width=15, command=self.do_register).pack(side="left", padx=10)
            
        else:
            # Show Profile Info
            tk.Label(self.info_frame_container, text=f"Xin chào,\n{self.current_user}", font=("Segoe UI", 24, "bold"), bg="#1e1e2e", fg="#89dceb").pack(pady=20)
            
            bal = self.db.get_balance(self.current_user)
            tk.Label(self.info_frame_container, text=f"Ví chung:", font=("Segoe UI", 14), bg="#1e1e2e", fg="#cdd6f4").pack(pady=5)
            tk.Label(self.info_frame_container, text=f"{bal:,} VNĐ", font=("Segoe UI", 32, "bold"), bg="#1e1e2e", fg="#a6e3a1").pack(pady=5)
            
            tk.Button(self.info_frame_container, text="Nạp tiền", font=("Segoe UI", 14, "bold"), bg="#f9e2af", fg="#1e1e2e", width=15, command=self.open_topup).pack(pady=20)
            
            tk.Button(self.info_frame_container, text="Đăng xuất", font=("Segoe UI", 12), bg="#f38ba8", fg="#1e1e2e", width=15, command=self.do_logout).pack(pady=30)
            
    def do_login(self):
        account = self.login_plate_var.get().strip()
        pwd = self.login_pass_var.get()
        if not account or not pwd:
            messagebox.showerror("Lỗi", "Vui lòng nhập đủ thông tin!")
            return
            
        if account not in self.db.data["accounts"]:
            messagebox.showerror("Lỗi đăng nhập", "Tài khoản chưa được đăng ký!")
            return
        if self.db.data["accounts"][account] != pwd:
            messagebox.showerror("Lỗi đăng nhập", "Sai mật khẩu!")
            return
            
        self.current_user = account
        self.render_info_content()
            
    def do_register(self):
        account = self.login_plate_var.get().strip()
        pwd = self.login_pass_var.get()
        if not account or not pwd:
            messagebox.showerror("Lỗi", "Vui lòng nhập đủ thông tin Tài khoản và Mật khẩu!")
            return
            
        if account in self.db.data["accounts"]:
            messagebox.showerror("Lỗi đăng ký", "Tài khoản này đã tồn tại!")
            return
            
        self.db.data["accounts"][account] = pwd
        self.db.save()
        messagebox.showinfo("Thành công", "Đăng ký thành công!")
        self.current_user = account
        self.render_info_content()
            
    def do_logout(self):
        self.current_user = None
        self.render_info_content()

    def update_journey_status(self, text, color="#e66f36"):
        self.bg_canvas.itemconfig(self.journey_text_id, text=text, fill=color)

    def open_topup(self):
        if self.current_user:
            # Already logged in, just ask for amount
            amount_str = simpledialog.askstring("Nạp tiền", f"Nhập số tiền muốn nạp cho tài khoản {self.current_user}:", parent=self.root)
            if amount_str and amount_str.isdigit():
                amount = int(amount_str)
                new_bal = self.db.add_balance(self.current_user, amount)
                old_bal = new_bal - amount
                note = f"+{amount:,}đ → Còn {new_bal:,}đ"
                self.db.add_history_record(self.current_user, "Nạp Tiền", amount, datetime.datetime.now().isoformat(), note=note)
                messagebox.showinfo("Thành công", f"Đã nạp {amount:,}đ vào tài khoản {self.current_user}.\nSố dư mới: {new_bal:,}đ")
                self.update_journey_status(f"Ví: {new_bal:,}đ", color="#1a73e8")
                self.render_info_content() # Refresh UI
            else:
                if amount_str: messagebox.showerror("Lỗi", "Số tiền không hợp lệ")
        else:
            # Not logged in, prompt for account name
            account = simpledialog.askstring("Nạp tiền", "Nhập tên tài khoản (Username):", parent=self.root)
            if account:
                account = account.strip()
                if account not in self.db.data["accounts"]:
                    messagebox.showerror("Lỗi", "Tài khoản không tồn tại. Vui lòng đăng ký trước!")
                    return
                amount_str = simpledialog.askstring("Nạp tiền", f"Nhập số tiền muốn nạp cho {account}:", parent=self.root)
                if amount_str and amount_str.isdigit():
                    amount = int(amount_str)
                    new_bal = self.db.add_balance(account, amount)
                    note = f"+{amount:,}đ → Còn {new_bal:,}đ"
                    self.db.add_history_record(account, "Nạp Tiền", amount, datetime.datetime.now().isoformat(), note=note)
                    messagebox.showinfo("Thành công", f"Đã nạp {amount:,}đ vào tài khoản {account}.\nSố dư mới: {new_bal:,}đ")
                else:
                    if amount_str: messagebox.showerror("Lỗi", "Số tiền không hợp lệ")
            
    # ─── SCANNER UI ────────────────────────────────────────────────────────
    def open_scanner(self, mode):
        """Open the camera interface specifically for ENTRY or EXIT."""
        if not self.reader:
            messagebox.showwarning("Chờ", "Hệ thống nhận diện chưa sẵn sàng, vui lòng đợi 1 giây rồi thử lại.")
            return

        self.scan_mode = mode
        self.vote_text = None
        self.vote_count = 0
        self.vote_best_conf = 0.0
        self.vote_best_frame = None

        self.scan_win = tk.Toplevel(self.root)
        self.scan_win.title(f"Quét Biển Số - {'XE VÀO' if mode == 'ENTRY' else 'XE RA'}")
        self.scan_win.geometry("500x700")
        self.scan_win.configure(bg="#1e1e2e")
        self.scan_win.transient(self.root)
        self.scan_win.grab_set()

        lbl_title = "Camera - Đưa biển số vào camera"
        tk.Label(self.scan_win, text=lbl_title, bg="#1e1e2e", fg="white", font=("Segoe UI", 14, "bold")).pack(pady=10)
        
        self.cam_label = tk.Label(self.scan_win, bg="black")
        self.cam_label.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.status_var = tk.StringVar(value="Đang mở camera...")
        tk.Label(self.scan_win, textvariable=self.status_var, bg="#1e1e2e", fg="#a6e3a1", font=("Segoe UI", 12)).pack(pady=5)
        
        btn_frame = tk.Frame(self.scan_win, bg="#1e1e2e")
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="✖ Hủy", command=self.close_scanner, font=("Segoe UI", 12), bg="#f38ba8").pack(side="left", padx=10)
        tk.Button(btn_frame, text="⌨ Nhập tay", command=self.manual_override, font=("Segoe UI", 12), bg="#89b4fa").pack(side="left", padx=10)
        tk.Button(btn_frame, text="💻 PC Cam", command=self._switchToPCWebcam, font=("Segoe UI", 12), bg="#a6e3a1").pack(side="left", padx=10)
        tk.Button(btn_frame, text="📱 IP Cam", command=self._switchToIPCam, font=("Segoe UI", 12), bg="#fab387").pack(side="left", padx=10)

        self.scan_win.protocol("WM_DELETE_WINDOW", self.close_scanner)
        
        self._start_camera()

    def _switchToPCWebcam(self):
        self.cam_index = 0
        self.db.save_camera_settings(self.cam_index, self.ip_cam_url)
        self.status_var.set("⏳ Đang kết nối Webcam PC...")
        self._start_camera()

    def _switchToIPCam(self):
        url = simpledialog.askstring("Nhập địa chỉ IP Camera", 
                                     "Nhập URL stream từ điện thoại (vd: http://192.168.1.5:8080/video):", 
                                     parent=self.scan_win, initialvalue=self.ip_cam_url)
        if url:
            self.ip_cam_url = url
            self.cam_index = -1
            self.db.save_camera_settings(self.cam_index, self.ip_cam_url)
            self.status_var.set("⏳ Đang kết nối IP camera...")
            self._start_camera()

    def _start_camera(self):
        self._stop_capture.set()
        self._stop_ocr.set()
        import time; time.sleep(0.15)
        self._stop_capture.clear()
        self._stop_ocr.clear()
        
        def worker():
            if self.cam_index == -1 and self.ip_cam_url:
                cap = cv2.VideoCapture(self.ip_cam_url)
            else:
                cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap = cap
            
            if not cap.isOpened():
                self.root.after(0, lambda: self.status_var.set("❌ Lỗi camera!"))
                return
            
            self.root.after(0, lambda: self.status_var.set("Sẵn sàng quét..."))
            
            threading.Thread(target=self._capture_loop, args=(cap,), daemon=True).start()
            threading.Thread(target=self._ocr_loop, daemon=True).start()
            
            self._poll_display()
            self._poll_results()

        threading.Thread(target=worker, daemon=True).start()

    def _capture_loop(self, cap):
        ocr_skip = 0
        while not self._stop_capture.is_set():
            ret, frame = cap.read()
            if not ret: break
            
            try: self._display_queue.get_nowait()
            except queue.Empty: pass
            
            try: self._display_queue.put_nowait(frame)
            except queue.Full: pass
            
            ocr_skip += 1
            if ocr_skip >= 3:
                ocr_skip = 0
                if self._ocr_queue.empty():
                    small = imutils.resize(frame, width=400)
                    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    loc = detect_plate_location(small)
                    scale = frame.shape[1] / small.shape[1]
                    try:
                        self._ocr_queue.put_nowait((frame.copy(), gray, loc, scale))
                    except queue.Full: pass

    def _ocr_loop(self):
        while not self._stop_ocr.is_set():
            try:
                frame_bgr, gray, location, scale = self._ocr_queue.get(timeout=0.5)
            except queue.Empty:
                continue
                
            text = None
            conf = 0.0
            annotated = frame_bgr.copy()
            
            if location is not None:
                try:
                    pts = location.reshape(4, 2).astype("float32")
                    pts *= scale
                    crop_bgr = four_point_transform(frame_bgr, pts)
                    crop_gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
                    proc = preprocess_crop(crop_gray)
                    
                    res = self.reader.readtext(proc, allowlist='0123456789ABCDEFGHJKLMNPRSTUVWXYZ.- ',
                                               paragraph=False, width_ths=0.5, height_ths=0.5,
                                               min_size=10, text_threshold=0.5, low_text=0.3)
                    plate = process_plate(res)
                    if plate and len(plate) >= 5 and is_valid_plate(plate):
                        conf = sum(r[2] for r in res) / len(res)
                        if conf >= 0.6:
                            text = plate
                            pts_int = (location * scale).astype(int)
                            cv2.polylines(annotated, [pts_int], True, (0, 255, 0), 3)
                            cv2.putText(annotated, plate, (pts_int[0][0][0], pts_int[0][0][1]-10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                except Exception:
                    pass
            
            try:
                self._result_queue.put_nowait((text, conf, annotated))
            except queue.Full:
                try: self._result_queue.get_nowait()
                except queue.Empty: pass
                self._result_queue.put_nowait((text, conf, annotated))

    def _poll_display(self):
        if self._stop_capture.is_set(): return
        try:
            frame = self._display_queue.get_nowait()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            w, h = self.cam_label.winfo_width(), self.cam_label.winfo_height()
            if w > 10 and h > 10:
                pil_img.thumbnail((w, h))
            photo = ImageTk.PhotoImage(pil_img)
            self.cam_label.configure(image=photo)
            self.cam_label.image = photo
        except queue.Empty: pass
        except Exception: pass
        
        self.scan_win.after(30, self._poll_display)

    def _poll_results(self):
        if self._stop_ocr.is_set(): return
        try:
            text, conf, annotated = self._result_queue.get_nowait()
            if text:
                self.status_var.set(f"🔍 {text} ({conf:.0%})")
                if text == self.vote_text:
                    self.vote_count += 1
                    if conf > self.vote_best_conf:
                        self.vote_best_conf = conf
                        self.vote_best_frame = annotated
                else:
                    self.vote_text = text
                    self.vote_count = 1
                    self.vote_best_conf = conf
                    self.vote_best_frame = annotated
                    
                if self.vote_count >= 5:
                    self.process_scan_result(self.vote_text, self.vote_best_frame)
                    return # Stop polling, we are done
        except queue.Empty:
            pass
            
        self.scan_win.after(100, self._poll_results)

    def manual_override(self):
        plate = simpledialog.askstring("Nhập tay", "Nhập biển số:", parent=self.scan_win)
        if plate and is_valid_plate(plate.strip()):
            self.process_scan_result(plate.strip(), None)
        else:
            if plate: messagebox.showerror("Lỗi", "Biển số không hợp lệ")

    def process_scan_result(self, plate, frame):
        # Stop camera
        self._stop_capture.set()
        self._stop_ocr.set()
        
        if self.scan_mode == "ENTRY":
            self.handle_entry(plate, frame)
        elif self.scan_mode == "EXIT":
            self.handle_exit(plate, frame)

    def handle_entry(self, plate, frame):
        session = self.db.get_session(plate)
        if session:
            messagebox.showwarning("Cảnh báo", f"Xe {plate} đang ở trong bãi rồi!", parent=self.scan_win)
        else:
            time_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            img_name = f"{plate}_{time_str}.png"
            
            entry_path = os.path.join(ENTRY_DIR, img_name)
            active_path = os.path.join(ACTIVE_DIR, img_name)
            
            if frame is not None:
                cv2.imwrite(entry_path, frame)
                cv2.imwrite(active_path, frame)
                
            self.db.start_session(plate, active_path if frame is not None else "")
            self.db.add_history_record(plate, "Xe Vào", 0, datetime.datetime.now().isoformat())
            
            # Auto-link plate to logged-in account
            if self.current_user:
                self.db.link_plate(self.current_user, plate)
            
            messagebox.showinfo("Thành công", f"Đã ghi nhận xe {plate} VÀO bãi.", parent=self.scan_win)
            self.update_journey_status(f"Xe {plate} đang trong bãi", color="#28a745")
        self.close_scanner()

    def handle_exit(self, plate, frame):
        session = self.db.get_session(plate)
        if not session:
            messagebox.showerror("Lỗi", f"Không tìm thấy xe {plate} trong bãi!", parent=self.scan_win)
            self.close_scanner()
            return
            
        time_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        img_name = f"{plate}_{time_str}.png"
        exit_path = os.path.join(EXIT_DIR, img_name)
        
        if frame is not None:
            cv2.imwrite(exit_path, frame)
            
        # Verify Identity (Show Entry and Exit images side by side)
        entry_img_path = session.get("entry_image")
        
        verify_win = tk.Toplevel(self.root)
        verify_win.title("Xác nhận xe ra")
        verify_win.geometry("700x500")
        verify_win.grab_set()
        
        tk.Label(verify_win, text=f"Kiểm tra xe ra: {plate}", font=("Segoe UI", 16, "bold")).pack(pady=10)
        
        frames_layout = tk.Frame(verify_win)
        frames_layout.pack()
        
        # Load Entry Image
        try:
            pil_entry = Image.open(entry_img_path)
            pil_entry.thumbnail((300, 300))
            photo_entry = ImageTk.PhotoImage(pil_entry)
            lbl1 = tk.Label(frames_layout, image=photo_entry, text="Lúc Vào", compound="top")
            lbl1.image = photo_entry
            lbl1.pack(side="left", padx=10)
        except Exception:
            tk.Label(frames_layout, text="[Không có ảnh lúc vào]").pack(side="left", padx=10)
            
        # Load Exit Image
        try:
            pil_exit = Image.open(exit_path)
            pil_exit.thumbnail((300, 300))
            photo_exit = ImageTk.PhotoImage(pil_exit)
            lbl2 = tk.Label(frames_layout, image=photo_exit, text="Lúc Ra", compound="top")
            lbl2.image = photo_exit
            lbl2.pack(side="left", padx=10)
        except Exception:
            tk.Label(frames_layout, text="[Không có ảnh lúc ra]").pack(side="left", padx=10)
            
        # Time-based pricing logic
        now = datetime.datetime.now()
        fee = 5000 if now.hour >= 18 else 3000
        time_text = "Sau 18h" if now.hour >= 18 else "Trước 18h"
        
        info_text = f"Thời gian ra: {now.strftime('%H:%M')} ({time_text})\nPhí gửi xe: {fee:,}đ"
        tk.Label(verify_win, text=info_text, font=("Segoe UI", 14), fg="red").pack(pady=10)
        
        def confirm_checkout():
            # Use logged-in account for payment
            pay_account = self.current_user if self.current_user else plate
            bal = self.db.get_balance(pay_account)
            if bal >= fee:
                self.db.deduct_balance(pay_account, fee)
                remaining = bal - fee
                note = f"Trừ {fee:,}đ → Còn {remaining:,}đ"
                self.db.add_history_record(plate, "Xe Ra (TT)", -fee, datetime.datetime.now().isoformat(), note=note)
                
                # Check out the car
                self.db.end_session(plate)
                
                # Cleanup the 'trong_bai' image
                if entry_img_path and os.path.exists(entry_img_path):
                    try:
                        os.remove(entry_img_path)
                    except Exception: pass
                    
                messagebox.showinfo("Thành công", f"Thanh toán thành công {fee:,}đ.\nTài khoản: {pay_account}\nSố dư còn: {remaining:,}đ", parent=verify_win)
                self.update_journey_status(f"Xe {plate} đã ra khỏi bãi", color="#6c757d")
                verify_win.destroy()
                self.close_scanner()
            else:
                resp = messagebox.askyesno("Thiếu tiền", f"Tài khoản {pay_account} chỉ còn {bal:,}đ. Thiếu {fee-bal:,}đ.\nBạn có muốn nạp thêm ngay bây giờ?", parent=verify_win)
                if resp:
                    amount_str = simpledialog.askstring("Nạp tiền", f"Nhập số tiền nạp cho {pay_account}:", parent=verify_win)
                    if amount_str and amount_str.isdigit():
                        self.db.add_balance(pay_account, int(amount_str))
                        messagebox.showinfo("Thành công", "Nạp tiền thành công, bấm Xác nhận lại.", parent=verify_win)
                
        def cancel_checkout():
            verify_win.destroy()
            self.close_scanner()
            
        tk.Button(verify_win, text="Xác nhận & Thanh toán", bg="green", fg="white", font=("Segoe UI", 12), command=confirm_checkout).pack(side="left", padx=60, pady=20)
        tk.Button(verify_win, text="Hủy", bg="red", fg="white", font=("Segoe UI", 12), command=cancel_checkout).pack(side="right", padx=60, pady=20)

    def close_scanner(self):
        self._stop_capture.set()
        self._stop_ocr.set()
        if self._cap:
            self._cap.release()
            self._cap = None
        if hasattr(self, 'scan_win') and self.scan_win.winfo_exists():
            self.scan_win.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = MobileParkingApp(root)
    root.mainloop()
