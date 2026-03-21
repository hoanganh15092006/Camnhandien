import cv2
import easyocr
import imutils
import numpy as np
import re
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import threading
import queue
import datetime
import csv
from ultralytics import YOLO

# Load the YOLO model for license plate detection
# Make sure best.pt is in the same directory
try:
    model = YOLO("best.pt")
except Exception as e:
    print(f"Error loading best.pt: {e}")
    model = None



# ─── OCR Helpers ──────────────────────────────────────────────────────────────

def fix_chars(text, is_letters=False, is_digits=False):
    dict_char_to_int = {'O': '0', 'I': '1', 'J': '3', 'A': '4', 'G': '6', 'S': '5', 'B': '8', 'Z': '2', 'Q': '0', 'T': '7'}
    dict_int_to_char = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S', '8': 'B', '2': 'Z', '7': 'T'}
    res = ""
    for char in text:
        if is_digits and char.upper() in dict_char_to_int:
            res += dict_char_to_int[char.upper()]
        elif is_letters and char.upper() in dict_int_to_char:
            res += dict_int_to_char[char.upper()]
        else:
            res += char.upper()
    return res


def order_points(pts):
    """Sort 4 points as [top-left, top-right, bottom-right, bottom-left]."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image, pts):
    """Straighten a 4-corner perspective to a top-down rectangle."""
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))
    dst = np.array([[0, 0], [maxWidth - 1, 0], [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


# Vietnamese plate regex patterns:
# 2 digits + 1-2 letters (can include digits like F1) + 3-5 digits
# Supports 1-line and 2-line formats
_PLATE_RE = re.compile(
    r'^\d{2}-[A-Z0-9]{1,2}\s+\d{3,5}$'        # 51-F1 12345
    r'|^\d{2}-[A-Z0-9]{1,2}\s+\d{3}\.\d{2}$'  # 51-F1 123.45
    r'|^\d{2}[A-Z0-9]{1,2}-\d{4,5}$'          # 51F1-12345
    r'|^\d{2}[A-Z0-9]{1,2}-\d{3}\.\d{2}$'      # 51F1-123.45
)

def is_valid_plate(text):
    """Return True only if text matches a known Vietnamese plate pattern."""
    if not text:
        return False
    # Normalise spaces
    t = re.sub(r'\s+', ' ', text.strip())
    return bool(_PLATE_RE.match(t))


def process_plate(res):
    if not res:
        return None
    res = sorted(res, key=lambda r: r[0][0][1])
    formatted_text = ""

    if len(res) >= 2:
        line1 = re.sub(r'[^a-zA-Z0-9]', '', res[0][1])
        line2 = re.sub(r'[^a-zA-Z0-9]', '', res[1][1])
        prov_code = fix_chars(line1[:2], is_digits=True)
        series = line1[2:]
        if len(series) == 2:
            dict_int_to_char_local = {'0': 'O', '1': 'I', '3': 'J', '4': 'A', '6': 'G', '5': 'S', '8': 'B', '2': 'Z'}
            if series[1].isalpha() or series[1] in list(dict_int_to_char_local.values()):
                if series[1] in '0123456789' and series[1] not in dict_int_to_char_local:
                    series = fix_chars(series[0], is_letters=True) + fix_chars(series[1], is_digits=True)
                else:
                    c0 = fix_chars(series[0], is_letters=True)
                    c1 = fix_chars(series[1], is_letters=True) if series[1].isalpha() else fix_chars(series[1], is_digits=True)
                    series = c0 + c1
        elif len(series) == 1:
            series = fix_chars(series[0], is_letters=True)
        line1_fixed = f"{prov_code}-{series}" if series else prov_code
        line2_fixed = fix_chars(line2, is_digits=True)[:5]
        if len(line2_fixed) == 5:
            line2_fixed = f"{line2_fixed[:3]}.{line2_fixed[3:]}"
        elif len(line2_fixed) == 4:
            line2_fixed = f"{line2_fixed[:2]}.{line2_fixed[2:]}"
        formatted_text = f"{line1_fixed} {line2_fixed}"

    elif len(res) == 1:
        text = re.sub(r'[^a-zA-Z0-9]', '', res[0][1])
        if len(text) >= 5:
            prov_code = fix_chars(text[:2], is_digits=True)
            first_letter_idx = -1
            for i, c in enumerate(text[2:]):
                if c.isalpha():
                    first_letter_idx = i + 2
                    break
            if first_letter_idx != -1:
                series = fix_chars(text[first_letter_idx:first_letter_idx+1], is_letters=True)
                rest = fix_chars(text[first_letter_idx+1:], is_digits=True)
                if len(rest) == 5:
                    rest = f"{rest[:3]}.{rest[3:]}"
                formatted_text = f"{prov_code}{series}-{rest}"
            else:
                formatted_text = fix_chars(text, is_digits=True)
        else:
            formatted_text = text

    return formatted_text


def detect_plate_location(frame):
    """
    Find the license plate using YOLOv8 (best.pt).
    Returns the bounding box coordinates as a 4-point array.
    """
    if frame is None or model is None:
        return None

    # Run inference
    results = model.predict(frame, conf=0.5, verbose=False)
    
    if not results or len(results[0].boxes) == 0:
        return None
        
    # Get the box with highest confidence
    box = results[0].boxes[0]
    # x1, y1, x2, y2 coordinates
    coords = box.xyxy[0].cpu().numpy()
    x1, y1, x2, y2 = coords
    
    # Format as a 4-point polygon: [[[x1, y1]], [[x2, y1]], [[x2, y2]], [[x1, y2]]]
    # This matches the previous output format
    res = np.array([[[int(x1), int(y1)]], [[int(x2), int(y1)]], [[int(x2), int(y2)]], [[int(x1), int(y2)]]])
    return res


def preprocess_crop(img):
    h, w = img.shape
    img = cv2.resize(img, (w * 3, h * 3), interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    img = clahe.apply(img)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    img = cv2.filter2D(img, -1, kernel)
    return img


# ─── Manual Entry Dialog ───────────────────────────────────────────────────────

class ManualEntryDialog(tk.Toplevel):
    def __init__(self, parent, snapshot_img, callback):
        super().__init__(parent)
        self.title("Nhập biển số thủ công")
        self.resizable(False, False)
        self.grab_set()
        self.callback = callback
        self.configure(bg="#1e1e2e")
        self.attributes("-topmost", True)

        tk.Label(self, text="⚠  Không nhận diện được biển số",
                 bg="#1e1e2e", fg="#f38ba8",
                 font=("Segoe UI", 13, "bold")).pack(pady=(16, 4), padx=20)

        tk.Label(self, text="Nhìn vào ảnh rồi nhập biển số bên dưới",
                 bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(pady=(0, 10), padx=20)

        if snapshot_img is not None:
            try:
                rgb = cv2.cvtColor(snapshot_img, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)
                pil_img.thumbnail((560, 320))
                self._photo = ImageTk.PhotoImage(pil_img)
                tk.Label(self, image=self._photo, bg="#1e1e2e",
                         relief="flat", bd=0).pack(padx=20, pady=(0, 12))
            except Exception:
                pass

        input_frame = tk.Frame(self, bg="#1e1e2e")
        input_frame.pack(padx=24, pady=(0, 8), fill="x")
        tk.Label(input_frame, text="Biển số:", bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 8))
        self.plate_var = tk.StringVar()
        entry = tk.Entry(input_frame, textvariable=self.plate_var,
                         font=("Consolas", 16, "bold"),
                         bg="#313244", fg="#cba6f7", insertbackground="#cba6f7",
                         relief="flat", bd=8, width=18)
        entry.pack(side="left", ipady=6)
        entry.focus_set()
        entry.bind("<Return>", lambda e: self._confirm())

        tk.Label(self, text='Ví dụ:  51-A1  123.45  hoặc  30F-12345',
                 bg="#1e1e2e", fg="#6c7086",
                 font=("Segoe UI", 9)).pack(padx=24, pady=(0, 10))

        btn_frame = tk.Frame(self, bg="#1e1e2e")
        btn_frame.pack(padx=24, pady=(0, 18))
        tk.Button(btn_frame, text="✔  Xác nhận", bg="#a6e3a1", fg="#1e1e2e",
                  font=("Segoe UI", 11, "bold"), relief="flat", padx=18, pady=8,
                  cursor="hand2", command=self._confirm).pack(side="left", padx=(0, 12))
        tk.Button(btn_frame, text="✖  Bỏ qua", bg="#45475a", fg="#cdd6f4",
                  font=("Segoe UI", 11), relief="flat", padx=18, pady=8,
                  cursor="hand2", command=self.destroy).pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

    def _confirm(self):
        val = self.plate_var.get().strip()
        if not val:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập biển số!", parent=self)
            return
        self.destroy()
        if self.callback:
            self.callback(val, source="manual")


# ─── Main Application ──────────────────────────────────────────────────────────

class LicensePlateApp:
    VOTE_THRESHOLD = 7    # rebalanced for sensitivity
    NO_DETECT_FRAMES = 60
    MIN_CONF = 0.65       # lowered from 0.75 for better handheld/skewed capture

    def __init__(self, root):
        self.root = root
        self.root.title("Hệ thống nhận diện biển số xe")
        self.root.configure(bg="#1e1e2e")
        self.root.geometry("1100x700")
        self.root.minsize(900, 600)

        # ── Shared state (thread-safe via locks / queues) ─────────────────
        self.output_dir = "plates"
        os.makedirs(self.output_dir, exist_ok=True)

        self.cam_index = 0
        self.ip_cam_url = None
        self.available_cams = []       # populated by scan thread
        self._cam_lock = threading.Lock()
        self._cap = None               # only touched by capture thread

        # Queues between threads
        # capture → ocr thread: (bgr_frame, small_gray, location, scale)
        self._ocr_queue = queue.Queue(maxsize=1)
        # ocr thread → main thread: (text, conf, annotated_bgr, crop_gray)
        self._result_queue = queue.Queue(maxsize=8)
        # display queue: main thread gets latest frame from capture thread
        self._display_queue = queue.Queue(maxsize=2)

        # OCR / voting state (only touched by main-thread polling)
        self.vote_text = None
        self.vote_count = 0
        self.vote_best_conf = 0.0
        self.vote_best_crop = None
        self.vote_best_frame = None
        self.committed_plates = set()
        self.no_detect_count = 0
        self.manual_dialog_open = False
        self.last_snapshot = None

        # Thread stop events
        self._stop_capture = threading.Event()
        self._stop_ocr = threading.Event()

        # StringVars
        self.current_plate_var = tk.StringVar(value="—")
        self.conf_var = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="Đang khởi động...")
        self.cam_combo_var = tk.StringVar(value="Đang quét...")

        self._build_ui()

        # Start init chain (all in background threads)
        threading.Thread(target=self._init_reader_thread, daemon=True).start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Left column: camera feed
        left = tk.Frame(self.root, bg="#1e1e2e")
        left.pack(side="left", fill="both", expand=True, padx=(14, 6), pady=14)

        tk.Label(left, text="📷  Camera trực tiếp",
                 bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))

        self.cam_label = tk.Label(left, bg="#181825", relief="flat", cursor="none")
        self.cam_label.pack(fill="both", expand=True)

        # Status bar
        status_frame = tk.Frame(left, bg="#181825", pady=6)
        status_frame.pack(fill="x", pady=(6, 0))
        self.status_indicator = tk.Label(status_frame, text="●", fg="#f38ba8",
                                         bg="#181825", font=("Segoe UI", 12))
        self.status_indicator.pack(side="left", padx=(10, 4))
        tk.Label(status_frame, textvariable=self.status_var,
                 bg="#181825", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(side="left")

        # Camera selector
        cam_row = tk.Frame(left, bg="#1e1e2e")
        cam_row.pack(fill="x", pady=(8, 0))
        tk.Label(cam_row, text="🎥 Camera:",
                 bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 6))
        self.cam_combo = ttk.Combobox(cam_row, textvariable=self.cam_combo_var,
                                      state="readonly", width=26,
                                      font=("Segoe UI", 10))
        self.cam_combo.pack(side="left", padx=(0, 6))
        self.switch_btn = tk.Button(cam_row, text="⇄  Chuyển",
                                    bg="#fab387", fg="#1e1e2e",
                                    font=("Segoe UI", 10, "bold"),
                                    relief="flat", padx=10, pady=4,
                                    cursor="hand2",
                                    command=self._switch_camera)
        self.switch_btn.pack(side="left")

        # Capture / Commit buttons
        btn_row = tk.Frame(left, bg="#1e1e2e")
        btn_row.pack(fill="x", pady=(8, 0))

        tk.Button(btn_row, text="⌨  Nhập tay biển số",
                  bg="#cba6f7", fg="#1e1e2e",
                  font=("Segoe UI", 11, "bold"),
                  relief="flat", padx=16, pady=8,
                  cursor="hand2",
                  command=self._open_manual_entry).pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.force_commit_btn = tk.Button(btn_row, text="✅ Nhập ngay biển đang quét",
                                         bg="#a6e3a1", fg="#1e1e2e",
                                         font=("Segoe UI", 11, "bold"),
                                         relief="flat", padx=16, pady=8,
                                         cursor="hand2",
                                         state="disabled",
                                         command=self._force_commit)
        self.force_commit_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Right column: info + history
        right = tk.Frame(self.root, bg="#1e1e2e", width=340)
        right.pack(side="right", fill="y", padx=(6, 14), pady=14)
        right.pack_propagate(False)

        # Current plate card
        card = tk.Frame(right, bg="#313244", padx=16, pady=14)
        card.pack(fill="x", pady=(0, 14))
        tk.Label(card, text="Biển số vừa nhận diện",
                 bg="#313244", fg="#a6adc8",
                 font=("Segoe UI", 10)).pack(anchor="w")
        tk.Label(card, textvariable=self.current_plate_var,
                 bg="#313244", fg="#cba6f7",
                 font=("Consolas", 26, "bold")).pack(anchor="w", pady=(4, 2))
        conf_row = tk.Frame(card, bg="#313244")
        conf_row.pack(anchor="w")
        tk.Label(conf_row, text="Độ chính xác: ",
                 bg="#313244", fg="#a6adc8",
                 font=("Segoe UI", 10)).pack(side="left")
        tk.Label(conf_row, textvariable=self.conf_var,
                 bg="#313244", fg="#a6e3a1",
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        # History table
        tk.Label(right, text="📋  Lịch sử biển số",
                 bg="#1e1e2e", fg="#89b4fa",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 6))

        tree_frame = tk.Frame(right, bg="#1e1e2e")
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Plate.Treeview",
                         background="#181825", foreground="#cdd6f4",
                         fieldbackground="#181825", rowheight=28,
                         font=("Consolas", 10))
        style.configure("Plate.Treeview.Heading",
                         background="#313244", foreground="#89b4fa",
                         font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Plate.Treeview", background=[("selected", "#45475a")])

        self.tree = ttk.Treeview(tree_frame, columns=("time", "plate", "conf", "src"),
                                  show="headings", style="Plate.Treeview",
                                  selectmode="browse")
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

        tk.Button(right, text="💾  Xuất CSV",
                  bg="#89b4fa", fg="#1e1e2e",
                  font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=12, pady=6,
                  cursor="hand2",
                  command=self._export_csv).pack(fill="x", pady=(10, 0))

    # ─── Thread 1: OCR model init ──────────────────────────────────────────────

    def _init_reader_thread(self):
        self.root.after(0, lambda: self.status_var.set("Đang tải mô hình OCR..."))
        self.reader = easyocr.Reader(['en'], gpu=False)
        self.root.after(0, self._scan_cameras_thread_start)

    # ─── Thread 2: Camera scan (background) ───────────────────────────────────

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
            messagebox.showerror("Lỗi camera", "Không tìm thấy camera nào.")
            return
        labels = [lbl for _, lbl in found]
        self.cam_combo.configure(values=labels)
        self.cam_combo_var.set(labels[0])
        first_idx = found[0][0]
        self._open_camera(first_idx)

    # ─── Thread 3: Capture loop ────────────────────────────────────────────────
    # Runs in a dedicated thread. Reads frames as fast as possible,
    # puts them into _display_queue (for UI) and _ocr_queue (for OCR thread).

    def _open_camera(self, idx, ip_url=None):
        """Open a new camera in background, then start capture + OCR threads."""
        self._stop_capture.set()   # stop old capture thread if any
        self._stop_ocr.set()       # stop old OCR thread if any
        self.root.after(0, lambda: self.status_var.set(f"Đang mở camera {'IP' if idx == -1 else idx}..."))

        def worker():
            # Wait briefly so old threads see the stop event
            import time; time.sleep(0.15)

            with self._cam_lock:
                if self._cap is not None:
                    self._cap.release()
                if ip_url is not None:
                    cap = cv2.VideoCapture(ip_url)
                else:
                    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # minimal latency
                self._cap = cap

            if not cap.isOpened():
                self.root.after(0, lambda: messagebox.showerror(
                    "Lỗi camera", f"Không thể mở camera {'địa chỉ IP' if idx == -1 else idx}."))
                return

            self.cam_index = idx
            label = next((lbl for i, lbl in self.available_cams if i == idx), f"Camera {idx}")
            self.root.after(0, lambda: self._on_camera_opened(label))

            # Reset stop events for new threads
            self._stop_capture.clear()
            self._stop_ocr.clear()

            # Drain stale frames from queues
            for q in (self._display_queue, self._ocr_queue, self._result_queue):
                while not q.empty():
                    try: q.get_nowait()
                    except queue.Empty: break

            # Start capture thread
            threading.Thread(target=self._capture_loop, args=(cap,), daemon=True).start()
            # Start OCR thread
            threading.Thread(target=self._ocr_loop, daemon=True).start()

        threading.Thread(target=worker, daemon=True).start()

    def _on_camera_opened(self, label):
        self.status_indicator.configure(fg="#a6e3a1")
        self.status_var.set(f"📷  {label}")
        # Start polling result queue from main thread
        self._poll_results()
        self._poll_display()

    def _capture_loop(self, cap):
        """
        Capture thread: reads frames at full fps.
        - Always pushes latest frame to _display_queue (overwrite if full).
        - Every N frames, pushes to _ocr_queue for OCR (skip if OCR busy).
        """
        ocr_skip = 0
        OCR_EVERY = 2   # send 1 in every 2 frames to OCR → better coverage

        while not self._stop_capture.is_set():
            ret, frame = cap.read()
            if not ret:
                break

            # Always update display queue (drop old frame)
            try:
                self._display_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._display_queue.put_nowait(frame)
            except queue.Full:
                pass

            # Feed OCR queue at reduced rate, non-blocking
            ocr_skip += 1
            if ocr_skip >= OCR_EVERY:
                ocr_skip = 0
                if self._ocr_queue.empty():
                    # Pre-compute plate detection here (cheap) to save OCR thread time
                    small = imutils.resize(frame, width=640)
                    gray  = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                    loc   = detect_plate_location(small)
                    scale = frame.shape[1] / small.shape[1]
                    try:
                        self._ocr_queue.put_nowait((frame.copy(), gray, loc, scale))
                    except queue.Full:
                        pass

    def _ocr_loop(self):
        """
        OCR thread: waits for frames, runs EasyOCR, puts result in _result_queue.
        This is the ONLY place readtext() is called — never blocks the UI.
        """
        while not self._stop_ocr.is_set():
            try:
                # Use a timeout so we can check for stop event periodically
                frame_bgr, gray, location, scale = self._ocr_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            text  = None
            conf  = 0.0
            crop  = None
            annotated = frame_bgr.copy()

            if location is not None:
                try:
                    # 4-point perspective transform to "flatten" skewed plates
                    pts = location.reshape(4, 2).astype("float32")
                    # Scale points back to original camera resolution
                    pts *= scale
                    crop_bgr = four_point_transform(frame_bgr, pts)
                    crop_gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
                    
                    # Preprocess for better OCR
                    proc = preprocess_crop(crop_gray)
                    
                    res = self.reader.readtext(
                        proc,
                        allowlist='0123456789ABCDEFGHJKLMNPRSTUVWXYZ.- ',
                        paragraph=False,
                        width_ths=0.5, height_ths=0.5,
                        min_size=10, text_threshold=0.5, low_text=0.3,
                    )
                    plate = process_plate(res)
                    
                    if plate and len(plate) >= 5 and is_valid_plate(plate):
                        conf = sum(r[2] for r in res) / len(res)
                        if conf < self.MIN_CONF:
                            plate = None  # discard low confidence
                        else:
                            text = plate
                            crop = crop_gray
                            # Draw overlay on annotated frame for UI feedback
                            pts_int = (location * scale).astype(int)
                            cv2.polylines(annotated, [pts_int], True, (0, 230, 80), 3)
                            cv2.putText(annotated, plate,
                                        (pts_int[0][0][0], pts_int[0][0][1] - 12),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                                        (0, 230, 80), 2, cv2.LINE_AA)
                except Exception:
                    # Catch transform/OCR errors without crashing thread
                    pass

            try:
                self._result_queue.put_nowait((text, conf, annotated, crop))
            except queue.Full:
                try:
                    self._result_queue.get_nowait()
                    self._result_queue.put_nowait((text, conf, annotated, crop))
                except queue.Empty:
                    pass

    # ─── Main thread: display & result polling ─────────────────────────────────

    def _poll_display(self):
        """Update camera display at ~30fps — separate from OCR polling."""
        if self._stop_capture.is_set():
            return
        try:
            frame = self._display_queue.get_nowait()
            self.last_snapshot = frame
            self._show_frame(frame)
        except queue.Empty:
            pass
        self.root.after(33, self._poll_display)   # ~30fps

    def _poll_results(self):
        """
        Drain OCR results from queue and run voting logic — called ~10fps.
        No heavy work here; everything heavy is in the OCR thread.
        """
        if self._stop_ocr.is_set():
            return

        processed = 0
        while processed < 3:   # max 3 results per tick
            try:
                text, conf, annotated, crop = self._result_queue.get_nowait()
                processed += 1
                self._handle_result(text, conf, annotated, crop)
            except queue.Empty:
                break

        self.root.after(100, self._poll_results)  # 10Hz result check

    def _handle_result(self, text, conf, annotated, crop):
        if text is not None and conf >= self.MIN_CONF:
            self.no_detect_count = 0
            self.force_commit_btn.configure(state="normal") # Enable force commit
            
            if text == self.vote_text:
                self.vote_count += 1
                if conf > self.vote_best_conf:
                    self.vote_best_conf  = conf
                    self.vote_best_crop  = crop
                    self.vote_best_frame = annotated
            else:
                self.vote_text       = text
                self.vote_count      = 1
                self.vote_best_conf  = conf
                self.vote_best_crop  = crop
                self.vote_best_frame = annotated

            self.status_var.set(f"🔍  {text}  ({conf:.0%})")

            if self.vote_count >= self.VOTE_THRESHOLD and text not in self.committed_plates:
                self._commit_plate(text, conf, crop, annotated, source="auto")
        else:
            self.vote_text = None
            self.vote_count = 0
            self.force_commit_btn.configure(state="disabled") # Disable if no detection
            
            self.no_detect_count += 1
            if self.no_detect_count == self.NO_DETECT_FRAMES and not self.manual_dialog_open:
                self.status_var.set("⚠  Không nhận diện được — nhấn 'Nhập tay' để nhập")
                self.no_detect_count = 0

    def _show_frame(self, frame):
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            w = self.cam_label.winfo_width()
            h = self.cam_label.winfo_height()
            if w > 10 and h > 10:
                pil_img.thumbnail((w, h))
            photo = ImageTk.PhotoImage(pil_img)
            self.cam_label.configure(image=photo)
            self.cam_label._photo = photo
        except Exception:
            pass

    # ─── Plate commit ──────────────────────────────────────────────────────────

    def _commit_plate(self, text, conf, crop, full_frame, source="auto"):
        self.committed_plates.add(text)
        now = datetime.datetime.now()
        time_str = now.strftime("%H:%M:%S")
        conf_str = f"{conf:.0%}" if source == "auto" else "—"
        src_label = "Tự động" if source == "auto" else "Nhập tay"

        self.current_plate_var.set(text)
        self.conf_var.set(conf_str)
        self.tree.insert("", 0, values=(time_str, text, conf_str, src_label))

        key = text.replace(" ", "_").replace("-", "").replace(".", "")
        if crop is not None:
            cv2.imwrite(os.path.join(self.output_dir, f'plate_{key}_crop.png'), crop)
        if full_frame is not None:
            cv2.imwrite(os.path.join(self.output_dir, f'plate_{key}_full.png'), full_frame)

        print(f"[{source.upper()}] {text}  ({conf_str})  {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # ─── Camera switching ──────────────────────────────────────────────────────

    def _switch_camera(self):
        if not self.available_cams:
            return
        selected_label = self.cam_combo_var.get()
        new_index = next((i for i, lbl in self.available_cams if lbl == selected_label), None)
        
        if new_index == -1:
            url = simpledialog.askstring("Nhập địa chỉ IP Camera", 
                                         "Nhập URL stream từ điện thoại (vd: http://192.168.1.5:8080/video):", 
                                         parent=self.root)
            if url:
                self.ip_cam_url = url
                self.status_var.set("⏳  Đang kết nối IP camera...")
                self._open_camera(-1, ip_url=url)
            else:
                # Reset combobox to previous value if cancelled
                btn = next((lbl for i, lbl in self.available_cams if i == self.cam_index), "...")
                self.cam_combo_var.set(btn)
            return

        if new_index is None or new_index == self.cam_index:
            return
        self.status_var.set("⏳  Đang chuyển camera...")
        self._open_camera(new_index)

    # ─── Manual entry ──────────────────────────────────────────────────────────

    def _open_manual_entry(self):
        if self.manual_dialog_open:
            return
        self.manual_dialog_open = True
        snapshot = self.last_snapshot.copy() if self.last_snapshot is not None else None
        ManualEntryDialog(self.root, snapshot, self._on_manual_plate_entered)

    def _on_manual_plate_entered(self, plate_text, source="manual"):
        self.manual_dialog_open = False
        if plate_text:
            self._commit_plate(plate_text.strip(), conf=0.0,
                               crop=None, full_frame=self.last_snapshot,
                               source="manual")
            self.status_var.set(f"✔  Đã lưu (nhập tay): {plate_text.strip()}")

    # ─── Export ────────────────────────────────────────────────────────────────

    def _force_commit(self):
        """Force the current best OCR result into the database immediately."""
        if self.vote_text and self.vote_best_crop is not None:
            text = self.vote_text
            conf = self.vote_best_conf
            crop = self.vote_best_crop
            frame = self.vote_best_frame
            
            # Reset voting to avoid immediate re-commit
            self.vote_text = None
            self.vote_count = 0
            self.force_commit_btn.configure(state="disabled")
            
            self._commit_plate(text, conf, crop, frame, source="auto")

    def _export_csv(self):
        rows = [self.tree.item(i)["values"] for i in self.tree.get_children()]
        if not rows:
            messagebox.showinfo("Xuất CSV", "Chưa có dữ liệu."); return
        path = os.path.join(self.output_dir,
                            f"plates_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Thời gian", "Biển số", "Độ chính xác", "Nguồn"])
            w.writerows(rows)
        messagebox.showinfo("Xuất CSV thành công", f"Đã lưu:\n{os.path.abspath(path)}")

    # ─── Cleanup ───────────────────────────────────────────────────────────────

    def on_close(self):
        self._stop_capture.set()
        self._stop_ocr.set()
        with self._cam_lock:
            if self._cap:
                self._cap.release()
        self.root.destroy()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = LicensePlateApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
