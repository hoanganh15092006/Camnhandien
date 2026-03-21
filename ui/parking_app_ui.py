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
        
        # Load OCR in background
        threading.Thread(target=self._init_ocr, daemon=True).start()
        
        self.show_frame("Home")

    def _init_ocr(self):
        self.reader = easyocr.Reader(['en'], gpu=False)

    def show_frame(self, name):
        if name == "History":
            self.refresh_history_list()
        frame = self.frames[name]
        frame.tkraise()
        if hasattr(self, 'nav_canvas_frame'):
            self.nav_canvas_frame.tkraise()

    def build_bottom_nav(self):
        self.nav_canvas_frame = tk.Frame(self.root, width=900, height=80, bg="white")
        self.nav_canvas_frame.place(x=0, y=770)
        self.nav_canvas = tk.Canvas(self.nav_canvas_frame, width=900, height=80, bg="white", highlightthickness=0)
        self.nav_canvas.pack(fill="both", expand=True)
        
        w = 900 // 3
        # Home
        self.nav_canvas.create_rectangle(0, 0, w, 80, fill="white", outline="", tags="nav_home")
        self.nav_canvas.create_text(w//2, 40, text="🏠\nTrang chủ", font=("Segoe UI", 12), justify="center", fill="#1a73e8", tags="nav_home")
        self.nav_canvas.tag_bind("nav_home", "<Button-1>", lambda e: self.show_frame("Home"))
        
        # History
        self.nav_canvas.create_rectangle(w, 0, w*2, 80, fill="white", outline="", tags="nav_hist")
        self.nav_canvas.create_text(w + w//2, 40, text="📋\nTra cứu", font=("Segoe UI", 12), justify="center", fill="#808080", tags="nav_hist")
        self.nav_canvas.tag_bind("nav_hist", "<Button-1>", lambda e: self.show_frame("History"))
        
        # Info
        self.nav_canvas.create_rectangle(w*2, 0, w*3, 80, fill="white", outline="", tags="nav_info")
        self.nav_canvas.create_text(w*2 + w//2, 40, text="👤\nTài khoản", font=("Segoe UI", 12), justify="center", fill="#808080", tags="nav_info")
        self.nav_canvas.tag_bind("nav_info", "<Button-1>", lambda e: self.show_frame("Info"))

    def build_home_frame(self, parent_frame):
        self.bg_canvas = tk.Canvas(parent_frame, width=900, height=850, highlightthickness=0)
        self.bg_canvas.pack(fill="both", expand=True)
        
        # Gradient
        color_top, color_bottom = "#9CbCBC", "#D8E6E3"
        for i in range(850):
            r = int(int(color_top[1:3], 16) * (1 - i/850) + int(color_bottom[1:3], 16) * (i/850))
            g = int(int(color_top[3:5], 16) * (1 - i/850) + int(color_bottom[3:5], 16) * (i/850))
            b = int(int(color_top[5:7], 16) * (1 - i/850) + int(color_bottom[5:7], 16) * (i/850))
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.bg_canvas.create_line(0, i, 900, i, fill=color)

        # Header Location
        create_rounded_rect(self.bg_canvas, 100, 20, 800, 90, radius=20, fill="white", outline="")
        self.bg_canvas.create_text(160, 40, text="Ga gần nhất:", font=("Segoe UI", 16, "bold"), anchor="w", fill="#202020")
        self.bg_canvas.create_text(160, 65, text="Tòa nhà Trung Tâm Đỗ Xe", font=("Segoe UI", 11), anchor="w", fill="#808080")
        self.bg_canvas.create_oval(115, 40, 145, 70, fill="#E0E0E0", outline="")
        self.bg_canvas.create_text(130, 55, text="📍", font=("Segoe UI", 16))

        # 3 Action Buttons
        bts = [("btn1", 165, "#f2b24c", "IN", "Xe Vào", "ENTRY"), 
               ("btn2", 390, "#f07865", "OUT", "Xe Ra", "EXIT"), 
               ("btn3", 615, "#40bced", "$", "Nạp tiền", "TOPUP")]
        for tag, x, color, txt, lbl, mode in bts:
            create_rounded_rect(self.bg_canvas, x, 110, x+120, 230, radius=15, fill="white", outline="#cccccc", width=2, tags=tag)
            self.bg_canvas.create_rectangle(x+30, 130, x+90, 190, fill=color, outline="", width=0, tags=tag)
            self.bg_canvas.create_text(x+60, 160, text=txt, font=("Segoe UI", 20 if len(txt)<3 else 24, "bold"), fill="white", tags=tag)
            self.bg_canvas.create_text(x+60, 210, text=lbl, font=("Segoe UI", 12, "bold"), fill="#202020", tags=tag)
            if mode == "TOPUP": self.bg_canvas.tag_bind(tag, "<Button-1>", lambda e: self.open_topup())
            else: self.bg_canvas.tag_bind(tag, "<Button-1>", lambda e, m=mode: self.open_scanner(m))

        create_rounded_rect(self.bg_canvas, 50, 250, 850, 360, radius=15, fill="white", outline="")
        self.bg_canvas.create_text(70, 275, text="HÀNH TRÌNH CỦA BẠN", font=("Segoe UI", 14, "bold"), anchor="w", fill="#18434a")
        self.journey_text_id = self.bg_canvas.create_text(100, 320, text="Chưa có xe trong bãi", font=("Segoe UI", 13), anchor="w", fill="#e66f36")
        self.bg_canvas.create_text(75, 320, text="🍂", font=("Segoe UI", 14), anchor="w")

        # Tin tức
        self.bg_canvas.create_text(50, 400, text="Tin tức & chương trình", font=("Segoe UI", 16, "bold"), anchor="w", fill="#202020")
        create_rounded_rect(self.bg_canvas, 50, 430, 440, 530, radius=15, fill="#cc3333", outline="")
        self.bg_canvas.create_text(245, 480, text="Ưu đãi Gửi xe tháng", font=("Segoe UI", 14, "bold"), fill="white")
        create_rounded_rect(self.bg_canvas, 460, 430, 850, 530, radius=15, fill="#2b4c7e", outline="")
        self.bg_canvas.create_text(655, 480, text="Q&A Hướng dẫn", font=("Segoe UI", 14, "bold"), fill="white")
        create_rounded_rect(self.bg_canvas, 50, 550, 850, 650, radius=15, fill="#0f7c46", outline="")
        self.bg_canvas.create_text(450, 600, text="HÀNH TRÌNH XANH - Tích điểm đổi quà", font=("Segoe UI", 16, "bold"), fill="white")

    def build_history_frame(self, parent_frame):
        tk.Label(parent_frame, text="Tra Cứu Lịch Sử Giao Dịch", font=("Segoe UI", 20, "bold"), bg="#1e1e2e", fg="white").pack(pady=20)
        search_frame = tk.Frame(parent_frame, bg="#1e1e2e")
        search_frame.pack(pady=5)
        tk.Label(search_frame, text="Biển số cần tra:", font=("Segoe UI", 12), bg="#1e1e2e", fg="white").pack(side="left", padx=5)
        self.search_plate_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=self.search_plate_var, font=("Segoe UI", 12), width=25).pack(side="left", padx=5)
        tk.Button(search_frame, text="Tìm", font=("Segoe UI", 10, "bold"), bg="#89b4fa", fg="#1e1e2e", width=8, command=self.refresh_history_list).pack(side="left", padx=5)
        tk.Button(search_frame, text="Tất cả xe", font=("Segoe UI", 10, "bold"), bg="#a6e3a1", fg="#1e1e2e", command=self.show_all_owned_history).pack(side="left", padx=5)
        self.hist_msg_var = tk.StringVar(value="")
        tk.Label(parent_frame, textvariable=self.hist_msg_var, font=("Segoe UI", 12, "italic"), bg="#1e1e2e", fg="#f38ba8").pack(pady=5)
        
        tree_frame = tk.Frame(parent_frame, bg="#1e1e2e")
        tree_frame.pack(fill="both", expand=True, padx=10)
        h_scroll = ttk.Scrollbar(tree_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")
        columns = ("time", "plate", "type", "amount", "note")
        self.hist_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=18, xscrollcommand=h_scroll.set)
        h_scroll.config(command=self.hist_tree.xview)
        for c, t, w in zip(columns, ["Thời gian", "Biển số", "Loại", "Số tiền", "Ghi chú"], [120, 120, 100, 100, 350]):
            self.hist_tree.heading(c, text=t)
            self.hist_tree.column(c, width=w, stretch=tk.NO, anchor="center" if c!="note" else "w")
        self.hist_tree.pack(fill="both", expand=True)

        self.hist_tree.bind("<Button-1>", lambda e: "break" if self.hist_tree.identify_region(e.x, e.y) == "separator" else None, add="+")
        self._drag_start_x = 0
        def on_drag_start(e): self._drag_start_x = e.x
        def on_drag_motion(e):
            delta = self._drag_start_x - e.x
            self.hist_tree.xview_scroll(delta, "units")
            self._drag_start_x = e.x
        self.hist_tree.bind("<Button-1>", on_drag_start, add="+")
        self.hist_tree.bind("<B1-Motion>", on_drag_motion)

    def show_all_owned_history(self):
        for row in self.hist_tree.get_children(): self.hist_tree.delete(row)
        if not self.current_user:
            self.hist_msg_var.set("Vui lòng đăng nhập ở tab Tài khoản để tra cứu.")
            return
        owned = self.db.get_owned_plates(self.current_user)
        all_keys = set(owned + [self.current_user])
        self.hist_msg_var.set(f"Xe của bạn: {', '.join(owned)}" if owned else f"Tài khoản {self.current_user} chưa có xe nào.")
        for r in self.db.get_history():
            if r['plate'] in all_keys: self._insert_tree_row(r)

    def refresh_history_list(self):
        for row in self.hist_tree.get_children(): self.hist_tree.delete(row)
        if not self.current_user:
            self.hist_msg_var.set("Vui lòng đăng nhập ở tab Tài khoản để tra cứu.")
            return
        target = self.search_plate_var.get().strip().upper()
        if not target: self.show_all_owned_history(); return
        self.hist_msg_var.set(f"Lịch sử của xe: {target}")
        for r in self.db.get_history():
            if r['plate'] == target: self._insert_tree_row(r)

    def _insert_tree_row(self, r):
        amt = f"{r['amount']:,}đ" if r['amount'] != 0 else "-"
        try: time_str = datetime.datetime.fromisoformat(r['time']).strftime("%d/%m %H:%M")
        except: time_str = r['time']
        self.hist_tree.insert("", "end", values=(time_str, r['plate'], r['type'], amt, r.get('note', '')))

    def build_info_frame(self, parent_frame):
        self.info_frame_container = parent_frame
        self.render_info_content()

    def render_info_content(self):
        for widget in self.info_frame_container.winfo_children(): widget.destroy()
        tk.Label(self.info_frame_container, text="Tài Khoản", font=("Segoe UI", 20, "bold"), bg="#1e1e2e", fg="white").pack(pady=30)
        if self.current_user is None:
            tk.Label(self.info_frame_container, text="Bạn chưa đăng nhập. Vui lòng đăng nhập\nhoặc đăng ký theo tên tài khoản bất kỳ.", font=("Segoe UI", 12), bg="#1e1e2e", fg="#a6adc8").pack(pady=10)
            f = tk.Frame(self.info_frame_container, bg="#313244", padx=20, pady=20); f.pack(pady=20)
            tk.Label(f, text="Tài khoản:", font=("Segoe UI", 12), bg="#313244", fg="white").grid(row=0, column=0, pady=5, sticky="w")
            self.login_plate_var = tk.StringVar(); tk.Entry(f, textvariable=self.login_plate_var, font=("Segoe UI", 12), width=25).grid(row=0, column=1, pady=5, padx=10)
            tk.Label(f, text="Mật khẩu:", font=("Segoe UI", 12), bg="#313244", fg="white").grid(row=1, column=0, pady=5, sticky="w")
            self.login_pass_var = tk.StringVar(); tk.Entry(f, textvariable=self.login_pass_var, show="*", font=("Segoe UI", 12), width=25).grid(row=1, column=1, pady=5, padx=10)
            btn_f = tk.Frame(f, bg="#313244"); btn_f.grid(row=2, column=0, columnspan=2, pady=20)
            tk.Button(btn_f, text="Đăng nhập", font=("Segoe UI", 12, "bold"), bg="#89b4fa", fg="#1e1e2e", width=15, command=self.do_login).pack(side="left", padx=10)
            tk.Button(btn_f, text="Đăng ký", font=("Segoe UI", 12, "bold"), bg="#a6e3a1", fg="#1e1e2e", width=15, command=self.do_register).pack(side="left", padx=10)
        else:
            tk.Label(self.info_frame_container, text=f"Xin chào,\n{self.current_user}", font=("Segoe UI", 24, "bold"), bg="#1e1e2e", fg="#89dceb").pack(pady=20)
            tk.Label(self.info_frame_container, text=f"Ví chung: {self.db.get_balance(self.current_user):,} VNĐ", font=("Segoe UI", 14), bg="#1e1e2e", fg="#cdd6f4").pack(pady=5)
            tk.Button(self.info_frame_container, text="Nạp tiền", font=("Segoe UI", 14, "bold"), bg="#f9e2af", fg="#1e1e2e", width=15, command=self.open_topup).pack(pady=20)
            tk.Button(self.info_frame_container, text="Đăng xuất", font=("Segoe UI", 12), bg="#f38ba8", fg="#1e1e2e", width=15, command=lambda: setattr(self, 'current_user', None) or self.render_info_content()).pack(pady=30)

    def do_login(self):
        u, p = self.login_plate_var.get().strip(), self.login_pass_var.get()
        if not u or not p: messagebox.showerror("Lỗi", "Nhập đủ thông tin!"); return
        if self.db.data.get("accounts", {}).get(u) == p: self.current_user = u; self.render_info_content()
        else: messagebox.showerror("Lỗi", "Sai thông tin hoặc tài khoản chưa tồn tại!")

    def do_register(self):
        u, p = self.login_plate_var.get().strip(), self.login_pass_var.get()
        if not u or not p: messagebox.showerror("Lỗi", "Nhập đủ thông tin!"); return
        if u in self.db.data["accounts"]: messagebox.showerror("Lỗi", "Tài khoản tồn tại!"); return
        self.db.data["accounts"][u] = p; self.db.save(); messagebox.showinfo("OK", "Đăng ký thành công!"); self.current_user = u; self.render_info_content()

    def update_journey_status(self, text, color="#e66f36"): self.bg_canvas.itemconfig(self.journey_text_id, text=text, fill=color)

    def open_topup(self):
        acc = self.current_user or simpledialog.askstring("Nạp tiền", "Tên tài khoản:", parent=self.root)
        if acc:
            acc = acc.strip()
            if acc not in self.db.data["accounts"]: messagebox.showerror("Lỗi", "Tài khoản chưa tồn tại!"); return
            amt_s = simpledialog.askstring("Nạp tiền", f"Số tiền nạp cho {acc}:", parent=self.root)
            if amt_s and amt_s.isdigit():
                amt = int(amt_s); nb = self.db.add_balance(acc, amt)
                self.db.add_history_record(acc, "Nạp Tiền", amt, datetime.datetime.now().isoformat(), note=f"+{amt:,}đ → Còn {nb:,}đ")
                messagebox.showinfo("OK", f"Đã nạp {amt:,}đ. Dư: {nb:,}đ"); self.render_info_content()

    def open_scanner(self, mode):
        if not self.reader: messagebox.showwarning("Chờ", "Hệ thống đang khởi động..."); return
        self.scan_mode, self.vote_text, self.vote_count, self.vote_best_conf, self.vote_best_frame = mode, None, 0, 0.0, None
        v = tk.Toplevel(self.root); v.title(f"Quét {'VÀO' if mode=='ENTRY' else 'RA'}"); v.geometry("500x700"); v.configure(bg="#1e1e2e")
        v.grab_set(); self.scan_win = v
        tk.Label(v, text="Camera Quét Biển Số", bg="#1e1e2e", fg="white", font=("Segoe UI",14,"bold")).pack(pady=10)
        self.cam_label = tk.Label(v, bg="black"); self.cam_label.pack(fill="both", expand=True, padx=10, pady=10)
        self.status_var = tk.StringVar(value="Đang mở..."); tk.Label(v, textvariable=self.status_var, bg="#1e1e2e", fg="#a6e3a1").pack(pady=5)
        bf = tk.Frame(v, bg="#1e1e2e"); bf.pack(pady=10)
        for t, c, bg in [("✖ Hủy", self.close_scanner, "#f38ba8"), ("⌨ Nhập tay", self.manual_override, "#89b4fa"), ("💻 PC Cam", lambda: self._set_cam(0), "#a6e3a1"), ("📱 IP Cam", self._set_ip, "#fab387")]:
             tk.Button(bf, text=t, command=c, bg=bg, font=("Segoe UI",12)).pack(side="left", padx=10)
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
            if not cap.isOpened(): self.status_var.set("❌ Lỗi camera!"); return
            self._cap = cap; self.status_var.set("Sẵn sàng..."); threading.Thread(target=self._cap_loop, args=(cap,), daemon=True).start()
            threading.Thread(target=self._ocr_loop, daemon=True).start(); self._poll_display(); self._poll_results()
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
            self._result_queue.put_nowait((text, conf, ann))

    def _poll_display(self):
        if self._stop_capture.is_set(): return
        try:
            f = self._display_queue.get_nowait(); p = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)).resize((480,360)))
            self.cam_label.configure(image=p); self.cam_label.image = p
        except: pass
        self.scan_win.after(30, self._poll_display)

    def _poll_results(self):
        if self._stop_ocr.is_set(): return
        try:
            t, c, a = self._result_queue.get_nowait()
            if t:
                self.status_var.set(f"🔍 {t} ({c:.0%})")
                if t == self.vote_text:
                    self.vote_count += 1
                    if c > self.vote_best_conf: self.vote_best_conf, self.vote_best_frame = c, a
                else: self.vote_text, self.vote_count, self.vote_best_conf, self.vote_best_frame = t, 1, c, a
                if self.vote_count >= 5: self.process_scan_result(self.vote_text, self.vote_best_frame); return
        except: pass
        self.scan_win.after(100, self._poll_results)

    def manual_override(self):
        p = simpledialog.askstring("Nhập tay", "Nhập biển số:", parent=self.scan_win)
        if p and is_valid_plate(p.strip().upper()): self.process_scan_result(p.strip().upper(), None)

    def process_scan_result(self, p, f):
        self._stop_capture.set(); self._stop_ocr.set()
        if self.scan_mode == "ENTRY": self.handle_entry(p, f)
        else: self.handle_exit(p, f)

    def handle_entry(self, p, f):
        if self.db.get_session(p): messagebox.showwarning("!", f"Xe {p} đã trong bãi!", parent=self.scan_win)
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); path = os.path.join(ACTIVE_DIR, f"{p}_{ts}.png")
            if f is not None: cv2.imwrite(path, f); cv2.imwrite(os.path.join(ENTRY_DIR, f"{p}_{ts}.png"), f)
            self.db.start_session(p, path if f is not None else ""); self.db.add_history_record(p, "Xe Vào", 0, datetime.datetime.now().isoformat())
            if self.current_user: self.db.link_plate(self.current_user, p)
            messagebox.showinfo("OK", f"Đã vào bãi: {p}"); self.update_journey_status(f"Xe {p} đang trong bãi", "#28a745")
        self.close_scanner()

    def handle_exit(self, p, f):
        s = self.db.get_session(p)
        if not s: messagebox.showerror("Lỗi", "Không tìm thấy xe!"); self.close_scanner(); return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S"); exp = os.path.join(EXIT_DIR, f"{p}_{ts}.png")
        if f is not None: cv2.imwrite(exp, f)
        v = tk.Toplevel(self.root); v.title("Xác nhận xe ra"); v.geometry("700x500"); v.grab_set()
        l = tk.Frame(v); l.pack()
        try:
            p1 = ImageTk.PhotoImage(Image.open(s.get("entry_image")).resize((300, 300))); tk.Label(l, image=p1, text="Vào", compound="top").pack(side="left", padx=10); l.p1 = p1
            p2 = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)).resize((300, 300))); tk.Label(l, image=p2, text="Ra", compound="top").pack(side="left", padx=10); l.p2 = p2
        except: pass
        now = datetime.datetime.now(); fee = 5000 if now.hour >= 18 else 3000
        tk.Label(v, text=f"Phí gửi xe: {fee:,}đ", font=("Segoe UI", 14), fg="red").pack(pady=10)
        def confirm():
            acc = self.current_user or p
            if self.db.get_balance(acc) >= fee:
                self.db.deduct_balance(acc, fee); self.db.end_session(p)
                self.db.add_history_record(p, "Xe Ra (TT)", -fee, now.isoformat(), note=f"Trừ {fee:,}đ")
                messagebox.showinfo("OK", "Thanh toán thành công!"); self.update_journey_status(f"Xe {p} đã ra", "#6c757d"); v.destroy(); self.close_scanner()
            else: messagebox.showwarning("!", "Không đủ tiền!")
        tk.Button(v, text="Thanh toán", bg="green", fg="white", command=confirm).pack(side="left", padx=100); tk.Button(v, text="Hủy", bg="red", fg="white", command=v.destroy).pack(side="right", padx=100)

    def close_scanner(self):
        self._stop_capture.set(); self._stop_ocr.set(); 
        if self._cap: self._cap.release(); self._cap = None
        if hasattr(self, 'scan_win') and self.scan_win.winfo_exists(): self.scan_win.destroy()
