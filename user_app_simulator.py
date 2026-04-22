import tkinter as tk
from tkinter import messagebox, simpledialog
import requests

API_URL = "http://127.0.0.1:5000/api"

class UserAppSimulator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Parking - Ứng Dụng Khách Hàng (Giả lập)")
        self.geometry("350x550")
        self.config(bg="#f5f6f8")
        
        self.username = None
        self.qr_code = None
        self.balance = 0
        
        self.show_login_screen()
        
    def show_login_screen(self):
        self.clear_window()
        tk.Label(self, text="ĐĂNG NHẬP (USER)", font=("Arial", 16, "bold"), bg="#f5f6f8", fg="#002d5e").pack(pady=40)
        
        tk.Label(self, text="Tên đăng nhập / Biển số:", bg="#f5f6f8").pack(anchor="w", padx=30)
        self.entry_user = tk.Entry(self, font=("Arial", 14))
        self.entry_user.pack(padx=30, pady=5, fill="x")
        
        tk.Button(self, text="ĐĂNG NHẬP / ĐĂNG KÝ", bg="#002d5e", fg="white", font=("Arial", 12, "bold"), 
                  command=self.do_login).pack(pady=20, padx=30, fill="x")
                  
    def do_login(self):
        user = self.entry_user.get()
        if not user: return
        
        # Cố gắng đăng ký (tài khoản test), nếu tồn tại thì không sao
        try:
            requests.post(f"{API_URL}/register", json={"username": user, "password": "123"})
            self.load_user_info(user)
        except Exception as e:
            messagebox.showerror("Lỗi kết nối", "Vui lòng bật api_server.py trước!")
            
    def load_user_info(self, username):
        resp = requests.get(f"{API_URL}/user/info?username={username}")
        if resp.status_code == 200:
            data = resp.json()
            self.username = data["username"]
            self.balance = data["balance"]
            self.qr_code = data["qr_code"]
            self.show_dashboard_screen()
            
    def show_dashboard_screen(self):
        self.clear_window()
        
        header = tk.Frame(self, bg="#002d5e", height=150)
        header.pack(fill="x")
        header.pack_propagate(False)
        
        tk.Label(header, text=f"Xin chào, {self.username}", font=("Arial", 14), bg="#002d5e", fg="white").pack(pady=(20, 5))
        tk.Label(header, text="Số dư khả dụng", font=("Arial", 10), bg="#002d5e", fg="#b0bec5").pack()
        tk.Label(header, text=f"{self.balance} VND", font=("Arial", 28, "bold"), bg="#002d5e", fg="white").pack()
        
        # Các nút chức năng
        btn_frame = tk.Frame(self, bg="#f5f6f8")
        btn_frame.pack(fill="both", expand=True, pady=30, padx=20)
        
        tk.Button(btn_frame, text="Mã QR Định Danh Của Tôi", bg="#1e88e5", fg="white", font=("Arial", 12),
                  command=self.show_qr).pack(fill="x", pady=10, ipady=10)
                  
        tk.Button(btn_frame, text="Nạp Tiền GTVT", bg="#4caf50", fg="white", font=("Arial", 12),
                  command=self.do_topup).pack(fill="x", pady=10, ipady=10)
                  
        tk.Label(btn_frame, text="Mô Phỏng Quét QR Thực Tế", bg="#f5f6f8", font=("Arial", 10, "italic"), fg="#757575").pack(pady=(20,0))
        
        tk.Button(btn_frame, text="1. Mô Phỏng 'Dí QR' => Xe Vào (IN)", bg="#ff9800", fg="white", font=("Arial", 10),
                  command=lambda: self.scan_api("in")).pack(fill="x", pady=5)
        tk.Button(btn_frame, text="2. Mô Phỏng 'Dí QR' => Xe Ra (OUT)", bg="#e53935", fg="white", font=("Arial", 10),
                  command=lambda: self.scan_api("out")).pack(fill="x", pady=5)
                  
        tk.Button(self, text="Đăng xuất", command=self.show_login_screen).pack(pady=10)
        
    def show_qr(self):
        messagebox.showinfo("Mã QR Của Tôi", f"Mã QR của bạn trong hệ thống là:\n\n{self.qr_code}\n\nĐưa mã này vào máy quét tại bãi.")
        
    def do_topup(self):
        amount = simpledialog.askinteger("Nạp Tiền", "Nhập số tiền:")
        if amount:
            requests.post(f"{API_URL}/user/topup", json={"username": self.username, "amount": amount})
            messagebox.showinfo("Thành công", f"Đã nạp {amount} VND!")
            self.load_user_info(self.username)
            
    def scan_api(self, scan_type):
        resp = requests.post(f"{API_URL}/user/scan_qr", json={"qr_code": self.qr_code, "type": scan_type})
        data = resp.json()
        if resp.status_code == 200:
            messagebox.showinfo("Barrier Kích Hoạt!", data['message'])
        else:
            messagebox.showwarning("Từ Chối!", data.get('message', 'Lỗi không xác định'))
        self.load_user_info(self.username)

    def clear_window(self):
        for widget in self.winfo_children():
            widget.destroy()

if __name__ == "__main__":
    app = UserAppSimulator()
    app.mainloop()
