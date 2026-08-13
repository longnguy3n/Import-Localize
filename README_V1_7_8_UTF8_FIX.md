# Import Localize v1.7.8 — UTF-8 fix

- CSV luôn được xử lý theo UTF-8.
- File có UTF-8 BOM và file UTF-8 không BOM đều được hỗ trợ.
- UI luôn hiển thị encoding là `utf-8`.
- Bỏ fallback cp1258/cp1252/latin-1.
- Sửa lỗi đọc mẫu 65.536 byte bị cắt giữa một ký tự UTF-8 nhiều byte bằng incremental decoder.
- Nếu CSV thực sự không phải UTF-8, ứng dụng báo lỗi rõ ràng thay vì âm thầm đọc Latin-1.

Đã kiểm tra trực tiếp với `DG_Localization - upload_vi.csv`: nhận đúng `utf-8`.
