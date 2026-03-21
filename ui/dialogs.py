import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import cv2

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
