# Hướng dẫn sử dụng Camnhandien

Dưới đây là các bước để cài đặt môi trường và chạy ứng dụng trên Windows:

## 1. Di chuyển vào thư mục dự án
Mở Command Prompt (cmd) hoặc PowerShell và di chuyển vào thư mục dự án:
```bash
cd Camnhandien
```

## 2. Cách tạo file venv (Virtual Environment)
Nếu bạn chưa có thư mục `venv`, hãy chạy lệnh sau để tạo môi trường ảo:
```bash
python -m venv venv
```

## 3. Kích hoạt môi trường ảo
Trước khi chạy code, bạn cần kích hoạt môi trường ảo:
```bash
.\venv\Scripts\activate
```
*Sau khi kích hoạt, bạn sẽ thấy chữ `(venv)` hiện ở đầu dòng lệnh.*

## 4. Chạy ứng dụng Python
Sau khi đã ở trong thư mục dự án và kích hoạt `venv`, hãy chạy file `main.py`:
```bash
python main.py
```

---
*Lưu ý: Đảm bảo bạn đã cài đặt Python. Nếu lệnh `python` không chạy được, hãy thử thay bằng `py`.*
