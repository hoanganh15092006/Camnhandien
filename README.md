# Hướng dẫn sử dụng Hệ thống Camnhandien

Dưới đây là các bước để cài đặt môi trường từ đầu (cho máy tính chưa có cài đặt gì) và sử dụng hệ thống: **Nhận diện biển số (Core)** và **Ứng dụng quản lý bãi xe (GUI)**.

---

## 🛠 1. Chuẩn bị môi trường (Bắt buộc)

Trước khi chạy, máy tính của bạn cần được cài đặt Python (phiên bản chuẩn có hỗ trợ giao diện Tkinter) và các thư viện cần thiết. Hãy mở terminal (Command Prompt, PowerShell hoặc Git Bash) bằng quyền Quản trị viên (Run as Administrator) và thực hiện các bước sau:

1. **Cài đặt Python chuẩn (Nếu máy chưa có)**:
   Mở PowerShell hoặc Command Prompt và chạy lệnh dưới đây (chờ terminal tải và cài đặt xong):
   ```bash
   winget install --id Python.Python.3.11 --accept-package-agreements --accept-source-agreements
   ```
   *Lưu ý: Nếu máy bạn đã cài Python đầy đủ từ `python.org` thì có thể bỏ qua bước này. Sau khi cài đặt, hãy khởi động lại terminal để hệ thống nhận diện được lệnh `python` mới cài.*

2. **Di chuyển vào thư mục dự án**:
   Mở terminal Bash/CMD mới và gõ lệnh để đi đến thư mục chứa code của bạn:
   phải cd vào thư mục Camnhandien
   ```bash
   cd Camnhandien
   ```

4. **Thiết lập môi trường ảo (venv)**:
   Môi trường ảo giúp chạy mã nguồn mà không ảnh hưởng tới hệ thống.
   ```bash
   python -m venv venv  
   ```
   Nếu không chạy được lệnh trên thì chạy lệnh này
   ```bash
   py -m venv venv
   ```

5. **Kích hoạt môi trường ảo**:
   - Trên **Windows CMD / PowerShell**:
     ```bash
     .\venv\Scripts\activate
     ```
   - Trên **Git Bash**:
     ```bash
     source venv/Scripts/activate
     ```

6. **Cài đặt thư viện AI (YOLOv8 + OCR)**:
   Khi dòng lệnh có chữ `(venv)` ở đầu, hãy chạy lệnh cài đặt tất cả các thư viện cần thiết:
   ```bash
   pip install opencv-python easyocr imutils numpy Pillow ultralytics
   ```
   *(Quá trình này sẽ tải các module nặng như PyTorch cho YOLOv8 và EasyOCR, vui lòng đợi).*

7. **Chuẩn bị file mô hình AI**:
   Đảm bảo file **`best.pt`** (file tôi đã trainAI) được đặt cùng cấp với file `main.py` và `parking_app.py`. Đây là file quan trọng nhất để hệ thống có thể nhận diện vùng biển số một cách chính xác.

---

## 🚀 2. Khởi chạy Ứng dụng

Sau khi đã hoàn tất cài đặt môi trường `venv`, bạn có hai lựa chọn để chạy phần mềm. Các lệnh dưới đây sử dụng đường dẫn Python trực tiếp trong môi trường ảo của dự án (`venv`) để đảm bảo các lỗi về thư viện không xảy ra.

### Lựa chọn 1: Chạy đồng thời cả 2 màn hình bằng 1 lệnh (Git Bash)
Nếu bạn đang sử dụng Git Bash, bạn có thể mở cả ứng dụng xử lý ảnh (`main.py`) và ứng dụng quản lý bãi xe (`parking_app.py`) chỉ với một dòng lệnh ở thư mục dự án:
```bash
./venv/Scripts/python.exe main.py & ./venv/Scripts/python.exe parking_app.py
```

### Lựa chọn 2: Chạy riêng biệt từng ứng dụng (Mở 2 terminal khác nhau)
Mở 2 cửa sổ PowerShell / CMD và vẫn đứng ở thư mục `Camnhandien`:

- **Terminal 1: Chạy Nhận diện & Xử lý Ảnh (`main.py`)**  
  Đây là module sử dụng mô hình **YOLOv8 (`best.pt`)** để khoanh vùng biển số và nhận diện thô.
  ```bash
  .\venv\Scripts\python.exe main.py
  ```

- **Terminal 2: Chạy Quản lý Bãi xe (`parking_app.py`)**  
  Khởi động GUI ứng dụng hoàn chỉnh tích hợp mô hình AI mới nhất để quản lý bãi xe.
  ```bash
  .\venv\Scripts\python.exe parking_app.py
  ```

---

## ℹ Các tính năng chính của Parking App:
- **AI Detection**: Tích hợp mô hình YOLO (`best.pt`) để phát hiện biển số cực nhạy, kể cả khi bị nghiêng.
- **Trang chủ**: Thực hiện Quét xe vào (IN) và Xe ra (OUT). Tích hợp trừ tiền tự động từ ví.
- **Tra cứu**: Nhập biển số để xem lịch sử hành trình. Hỗ trợ tính năng **Lướt (Swipe)** bằng chuột trên danh sách để xem chi tiết ghi chú.
- **Tài khoản**: Đăng ký/Đăng nhập (bằng biển số) để liên kết phương tiện và nạp tiền/quản lý ví.

### Cấu trúc file và dữ liệu lưu trữ sinh ra:
- `best.pt`: File trọng số mô hình AI đã huấn luyện.
- `parking_data.json`: Lưu thông tin tài khoản, số dư ví và toàn bộ lịch sử sử dụng hệ thống.
- `parking_sessions/`: Lưu ảnh xe lúc Vào / Ra để dễ dàng kiểm tra đối chứng khi kiểm soát bãi.
- `plates/`: Lưu các ảnh đã cắt tự động vùng chứa biển số để debug.
