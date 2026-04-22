


Camnhandien/
├── core/
│   ├── __init__.py
│   ├── detection.py      # YOLO model and plate detection
│   ├── ocr.py            # EasyOCR and text processing
│   └── utils.py          # Image processing helpers
├── data/
│   ├── __init__.py
│   └── database.py       # ParkingDB logic
├── ui/
│   ├── __init__.py
│   ├── main_app.py       # LicensePlateApp (original main.py GUI)
│   ├── parking_app.py    # MobileParkingApp (original parking_app.py GUI)
│   ├── dialogs.py        # ManualEntryDialog
│   └── components.py     # UI helpers like rounded rects
├── main.py               # Entry point for LicensePlateApp
├── parking_app.py        # Entry point for MobileParkingApp
└── best.pt               # Model file





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

## 🚀 2. Khởi chạy Ứng dụng Desktop (PC)

Sau khi đã hoàn tất cài đặt môi trường `venv`, bạn có hai lựa chọn để chạy phần mềm trên máy tính:

### Lựa chọn 1: Chạy đồng thời cả 2 màn hình bằng 1 lệnh (Git Bash)
Mở ứng dụng nhận diện (`main.py`) và ứng dụng quản lý bãi xe (`parking_app.py`) với một lệnh:
```bash
python main.py & python parking_app.py
```

### Lựa chọn 2: Chạy độc lập
- Nhận diện biển số: `python main.py`
- Quản trị bãi đỗ xe: `python parking_app.py`

---

## 📱 3. Khởi chạy Ứng Dụng Khách Hàng (User App)

Để mô phỏng ứng dụng của khách hàng gửi xe, hệ thống đã chuẩn bị 2 hình thức: Mở bằng Máy ảo Android (app thật) hoặc Mở bằng phần mềm giả lập trên máy tính (nhanh gọn).

### Bước 3.1: Chạy API Backend (Bắt buộc)
1. Mở Terminal mới tại thư mục `Camnhandien`.
2. Chạy thư viện cần thiết: `pip install flask requests`
3. Chạy máy chủ: `python api_server.py`
*(Giữ Terminal này luôn mở)*

### Bước 3.2: Sử dụng Ứng Dụng 

**Tùy chọn A: Dùng App Giả lập Desktop (Khuyên dùng thử nghiệm nhanh)**
Không cần mở Android Studio, tôi đã viết một bản mô phỏng App cực kỳ nhẹ trên máy tính.
- Khởi động CMD/Terminal mới, chạy: `python user_app_simulator.py`
- Giao diện đăng nhập hiện ra, bạn điền tên / biển số bất kỳ.
- Chọn **"Nạp tiền"**.
- Bấm mô phỏng **Quét QR Xe Vào (IN)** và **Ra (OUT)**.
- Bạn sẽ thấy tiền bị trừ và dữ liệu được ném thẳng về `parking_app.py` và `parking_system.db`.

**Tùy chọn B: Dùng App thật trên Android Studio**
1. Mở phần mềm **Android Studio**.
2. Chọn **File > Open** -> Thư mục: `C:\Users\Admin\CAMNHANDIENBIENSO\JavaUserApp`.
3. Nhấn mũi tên xanh **Run** trên máy ảo (Emulator). Mọi thao tác tương tự như bản giả lập bên trên.

---

## ℹ Các tính năng chính của Hệ Sinh Thái:
- **AI Detection**: Tích hợp mô hình YOLO (`best.pt`) phát hiện biển số siêu nhạy.
- **Desktop Manager (`parking_app.py`)**: Giao diện cho bảo vệ trực ở bãi xe. Quét xe vào (IN) và Xe ra (OUT). Tích hợp trừ tiền tự động từ ví.
- **Backend API (`api_server.py`)**: Máy chủ xử lý dữ liệu và cung cấp API REST.
- **Android User App (`JavaUserApp`)**: App dành cho khách hàng. Đăng ký tài khoản, nạp tiền, và hiển thị **Mã QR Định Danh** cá nhân. Dùng mã QR này để tự động check-in/check-out với bãi.

### Cấu trúc file và dữ liệu lưu trữ sinh ra:
- `best.pt`: File trọng số mô hình AI đã huấn luyện.
- `parking_system.db` (trong thư mục `data`): Lưu cơ sở dữ liệu hệ thống chuẩn SQLite thay cho json.
- `parking_sessions/`: Lưu ảnh xe lúc Vào / Ra để dễ dàng kiểm tra đối chứng khi kiểm soát bãi.
- `JavaUserApp/`: Mã nguồn viết bằng gốc **Java XML** của ứng dụng điện thoại.
