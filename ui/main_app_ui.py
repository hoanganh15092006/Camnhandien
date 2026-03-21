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
import csv

from core.utils import four_point_transform, preprocess_crop
from core.ocr import process_plate, is_valid_plate
from core.detection import detect_plate_location
from ui.dialogs import ManualEntryDialog

class LicensePlateApp:
    VOTE_THRESHOLD = 7
    NO_DETECT_FRAMES = 60
    MIN_CONF = 0.65

    def __init__(self, root):
        self.root = root
        self.root.title("Hệ thống nhận diện biển số xe")
        self.root.configure(bg="#1e1e2e")
        self.root.geometry("1100x700")
        self.root.minsize(900, 600)

        self.output_dir = "plates"
        os.makedirs(self.output_dir, exist_ok=True)

        self.cam_index = 0
        self.ip_cam_url = None
        self.available_cams = []
        self._cam_lock = threading.Lock()
        self._cap = None

        self._ocr_queue = queue.Queue(maxsize=1)
        self._result_queue = queue.Queue(maxsize=8)
        self._display_queue = queue.Queue(maxsize=2)

        self.vote_text = None
        self.vote_count = 0
        self.vote_best_conf = 0.0
        self.vote_best_crop = None
        self.vote_best_frame = None
        self.committed_plates = set()
        self.no_detect_count = 0
        self.manual_dialog_open = False
        self.last_snapshot = None

        self._stop_capture = threading.Event()
        self._stop_ocr = threading.Event()

        self.current_plate_var = tk.StringVar(value="—")
        self.conf_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="Đang khởi động...")
        self.cam_combo_var = tk.StringVar(value="Đang quét...")

        self._build_ui()
        threading.Thread(target=self._init_reader_thread, daemon=True).start()

    def _build_ui(self):
        left = tk.Frame(self.root, bg="#1e1e2e")
        left.pack(side="left", fill="both", expand=True, padx=(14, 6), pady=14)

        tk.Label(left, text="📷  Camera trực tiếp", bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))

        self.cam_label = tk.Label(left, bg="#181825", relief="flat", cursor="none")
        self.cam_label.pack(fill="both", expand=True)

        status_frame = tk.Frame(left, bg="#181825", pady=6)
        status_frame.pack(fill="x", pady=(6, 0))
        self.status_indicator = tk.Label(status_frame, text="●", fg="#f38ba8",
                                         bg="#181825", font=("Segoe UI", 12))
        self.status_indicator.pack(side="left", padx=(10, 4))
        tk.Label(status_frame, textvariable=self.status_var, bg="#181825", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(side="left")

        cam_row = tk.Frame(left, bg="#1e1e2e")
        cam_row.pack(fill="x", pady=(8, 0))
        tk.Label(cam_row, text="🎥 Camera:", bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))
        self.cam_combo = ttk.Combobox(cam_row, textvariable=self.cam_combo_var, state="readonly", width=26)
        self.cam_combo.pack(side="left", padx=(0, 6))
        tk.Button(cam_row, text="⇄  Chuyển", bg="#fab387", fg="#1e1e2e", font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=10, pady=4, cursor="hand2", command=self._switch_camera).pack(side="left")

        btn_row = tk.Frame(left, bg="#1e1e2e")
        btn_row.pack(fill="x", pady=(8, 0))
        tk.Button(btn_row, text="⌨  Nhập tay biển số", bg="#cba6f7", fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                  relief="flat", padx=16, pady=8, cursor="hand2", command=self._open_manual_entry).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.force_commit_btn = tk.Button(btn_row, text="✅ Nhập ngay biển đang quét", bg="#a6e3a1", fg="#1e1e2e", font=("Segoe UI", 11, "bold"),
                                          relief="flat", padx=16, pady=8, cursor="hand2", state="disabled", command=self._force_commit)
        self.force_commit_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        right = tk.Frame(self.root, bg="#1e1e2e", width=340)
        right.pack(side="right", fill="y", padx=(6, 14), pady=14)
        right.pack_propagate(False)

        card = tk.Frame(right, bg="#313244", padx=16, pady=14)
        card.pack(fill="x", pady=(0, 14))
        tk.Label(card, text="Biển số vừa nhận diện", bg="#313244", fg="#a6adc8", font=("Segoe UI", 10)).pack(anchor="w")
        tk.Label(card, textvariable=self.current_plate_var, bg="#313244", fg="#cba6f7", font=("Consolas", 26, "bold")).pack(anchor="w", pady=(4, 2))
        conf_row = tk.Frame(card, bg="#313244")
        conf_row.pack(anchor="w")
        tk.Label(conf_row, text="Độ chính xác: ", bg="#313244", fg="#a6adc8").pack(side="left")
        tk.Label(conf_row, textvariable=self.conf_var, bg="#313244", fg="#a6e3a1", font=("Segoe UI", 10, "bold")).pack(side="left")

        tk.Label(right, text="📋  Lịch sử biển số", bg="#1e1e2e", fg="#89b4fa", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))
        tree_frame = tk.Frame(right, bg="#1e1e2e")
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Plate.Treeview", background="#181825", foreground="#cdd6f4", fieldbackground="#181825", rowheight=28)
        style.configure("Plate.Treeview.Heading", background="#313244", foreground="#89b4fa", font=("Segoe UI", 10, "bold"))

        self.tree = ttk.Treeview(tree_frame, columns=("time", "plate", "conf", "src"), show="headings", style="Plate.Treeview")
        self.tree.heading("time", text="Thời gian")
        self.tree.heading("plate", text="Biển số")
        self.tree.heading("conf", text="ĐCX")
        self.tree.heading("src", text="Nguồn")
        self.tree.column("time", width=90, anchor="center")
        self.tree.column("plate", width=130, anchor="center")
        self.tree.column("conf", width=55, anchor="center")
        self.tree.column("src", width=60, anchor="center")
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        tk.Button(right, text="💾  Xuất CSV", bg="#89b4fa", fg="#1e1e2e", font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=12, pady=6, cursor="hand2", command=self._export_csv).pack(fill="x", pady=(10, 0))

    def _init_reader_thread(self):
        self.root.after(0, lambda: self.status_var.set("Đang tải mô hình OCR..."))
        self.reader = easyocr.Reader(['en'], gpu=False)
        self.root.after(0, self._scan_cameras_thread_start)

    def _scan_cameras_thread_start(self):
        self.root.after(0, lambda: self.status_var.set("Đang dò tìm camera..."))
        threading.Thread(target=self._scan_cameras_worker, daemon=True).start()

    def _scan_cameras_worker(self):
        found = []
        for idx in range(5):
            test = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if test.isOpened():
                ret, _ = test.read()
                if ret:
                    label = f"Camera {idx}" + (" (tích hợp)" if idx == 0 else f" (USB #{idx})")
                    found.append((idx, label))
                test.release()
        found.append((-1, "📱 IP Camera (Điện thoại)"))
        self.root.after(0, lambda: self._on_cameras_found(found))

    def _on_cameras_found(self, found):
        self.available_cams = found
        if not found:
            self.status_var.set("❌  Không tìm thấy camera nào!")
            return
        labels = [lbl for _, lbl in found]
        self.cam_combo.configure(values=labels)
        self.cam_combo_var.set(labels[0])
        self._open_camera(found[0][0])

    def _open_camera(self, idx, ip_url=None):
        self._stop_capture.set()
        self._stop_ocr.set()
        def worker():
            import time; time.sleep(0.15)
            with self._cam_lock:
                if self._cap is not None: self._cap.release()
                if ip_url is not None: cap = cv2.VideoCapture(ip_url)
                else: cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self._cap = cap
            if not cap.isOpened(): return
            self.cam_index = idx
            self.root.after(0, lambda: self._on_camera_opened())
            self._stop_capture.clear()
            self._stop_ocr.clear()
            threading.Thread(target=self._capture_loop, args=(cap,), daemon=True).start()
            threading.Thread(target=self._ocr_loop, daemon=True).start()
        threading.Thread(target=worker, daemon=True).start()

    def _on_camera_opened(self):
        self.status_indicator.configure(fg="#a6e3a1")
        self.status_var.set("📷  Camera sẵn sàng")
        self._poll_results()
        self._poll_display()

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
            if ocr_skip >= 2:
                ocr_skip = 0
                if self._ocr_queue.empty():
                    small = imutils.resize(frame, width=640)
                    gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    loc   = detect_plate_location(small)
                    scale = frame.shape[1] / small.shape[1]
                    try: self._ocr_queue.put_nowait((frame.copy(), gray, loc, scale))
                    except queue.Full: pass

    def _ocr_loop(self):
        while not self._stop_ocr.is_set():
            try: frame_bgr, gray, location, scale = self._ocr_queue.get(timeout=0.5)
            except queue.Empty: continue
            text, conf, crop, annotated = None, 0.0, None, frame_bgr.copy()
            if location is not None:
                try:
                    pts = location.reshape(4, 2).astype("float32") * scale
                    crop_bgr = four_point_transform(frame_bgr, pts)
                    crop_gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
                    proc = preprocess_crop(crop_gray)
                    res = self.reader.readtext(proc, allowlist='0123456789ABCDEFGHJKLMNPRSTUVWXYZ.- ', paragraph=False)
                    plate = process_plate(res)
                    if plate and is_valid_plate(plate):
                        conf = sum(r[2] for r in res) / len(res)
                        if conf >= self.MIN_CONF:
                            text, crop = plate, crop_gray
                            pts_int = (location * scale).astype(int)
                            cv2.polylines(annotated, [pts_int], True, (0, 230, 80), 3)
                except Exception: pass
            try: self._result_queue.put_nowait((text, conf, annotated, crop))
            except queue.Full: pass

    def _poll_display(self):
        if self._stop_capture.is_set(): return
        try:
            frame = self._display_queue.get_nowait()
            self.last_snapshot = frame
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            w, h = self.cam_label.winfo_width(), self.cam_label.winfo_height()
            if w > 10 and h > 10: pil_img.thumbnail((w, h))
            photo = ImageTk.PhotoImage(pil_img)
            self.cam_label.configure(image=photo)
            self.cam_label._photo = photo
        except queue.Empty: pass
        self.root.after(33, self._poll_display)

    def _poll_results(self):
        if self._stop_ocr.is_set(): return
        try:
            text, conf, annotated, crop = self._result_queue.get_nowait()
            self._handle_result(text, conf, annotated, crop)
        except queue.Empty: pass
        self.root.after(100, self._poll_results)

    def _handle_result(self, text, conf, annotated, crop):
        if text and conf >= self.MIN_CONF:
            self.no_detect_count = 0
            self.force_commit_btn.configure(state="normal")
            if text == self.vote_text:
                self.vote_count += 1
                if conf > self.vote_best_conf: self.vote_best_conf, self.vote_best_crop, self.vote_best_frame = conf, crop, annotated
            else: self.vote_text, self.vote_count, self.vote_best_conf, self.vote_best_crop, self.vote_best_frame = text, 1, conf, crop, annotated
            self.status_var.set(f"🔍  {text}  ({conf:.0%})")
            if self.vote_count >= self.VOTE_THRESHOLD and text not in self.committed_plates:
                self._commit_plate(text, conf, crop, annotated, source="auto")
        else:
            self.vote_text, self.vote_count, self.force_commit_btn["state"] = None, 0, "disabled"
            self.no_detect_count += 1
            if self.no_detect_count == self.NO_DETECT_FRAMES: self.status_var.set("⚠  Không nhận diện được — nhấn 'Nhập tay' để nhập")

    def _commit_plate(self, text, conf, crop, full_frame, source="auto"):
        self.committed_plates.add(text)
        now = datetime.datetime.now()
        time_str, conf_str = now.strftime("%H:%M:%S"), (f"{conf:.0%}" if source == "auto" else "—")
        self.current_plate_var.set(text)
        self.conf_var.set(conf_str)
        self.tree.insert("", 0, values=(time_str, text, conf_str, "Tự động" if source == "auto" else "Nhập tay"))
        key = text.replace(" ", "_").replace("-", "").replace(".", "")
        if crop is not None: cv2.imwrite(os.path.join(self.output_dir, f'plate_{key}_crop.png'), crop)
        if full_frame is not None: cv2.imwrite(os.path.join(self.output_dir, f'plate_{key}_full.png'), full_frame)

    def _switch_camera(self):
        idx = next((i for i, lbl in self.available_cams if lbl == self.cam_combo_var.get()), 0)
        if idx == -1:
            url = simpledialog.askstring("IP Camera", "Nhập URL stream:", parent=self.root)
            if url: self._open_camera(-1, ip_url=url)
        else: self._open_camera(idx)

    def _open_manual_entry(self):
        self.manual_dialog_open = True
        ManualEntryDialog(self.root, self.last_snapshot, self._on_manual_result)

    def _on_manual_result(self, text, source="manual"):
        self.manual_dialog_open = False
        self._commit_plate(text, 0, None, self.last_snapshot, source=source)

    def _force_commit(self):
        if self.vote_text: self._commit_plate(self.vote_text, self.vote_best_conf, self.vote_best_crop, self.vote_best_frame, source="auto")

    def _export_csv(self):
        with open("history.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Thời gian", "Biển số", "Độ chính xác", "Nguồn"])
            for item in self.tree.get_children(): writer.writerow(self.tree.item(item)["values"])
        messagebox.showinfo("Thành công", "Đã xuất lịch sử ra file history.csv")
