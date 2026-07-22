# Import Localize v1.6.2 — sửa cơ chế tự cập nhật

## Lỗi đã sửa

Ở bản cũ, ứng dụng đóng ngay sau khi gọi PowerShell nhưng không xác nhận trình cài có thực sự chạy hoặc có quyền ghi vào thư mục cài đặt. Vì vậy app có thể tắt nhưng file không được thay thế, và khi mở lại vẫn là bản cũ.

## Cơ chế mới

- Chỉ đóng ứng dụng sau khi updater tạo tín hiệu `updater_ready.flag`.
- Kiểm tra quyền ghi vào thư mục cài đặt trước khi đóng app.
- Tự mở UAC nếu thư mục cần quyền Administrator.
- Nếu người dùng từ chối UAC hoặc PowerShell lỗi, app không tự đóng và hiển thị nguyên nhân.
- Chờ app thoát tối đa 25 giây; nếu tiến trình Qt bị treo thì updater đóng cưỡng bức để tiếp tục.
- Sao lưu toàn bộ bản hiện tại vào AppData trước khi chép bản mới.
- Kiểm tra EXE mới có khởi động ổn định trước khi xóa backup.
- Tự rollback và mở lại bản cũ nếu cài đặt thất bại.
- Lưu log tại `%APPDATA%\Import Localize\updates\v<version>\update_apply.log`.

## Cài patch

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\apply_patch.ps1 `
  -ProjectRoot "F:\Codes\Import_Localize"
```

Sau đó build và phát hành bản v1.6.2 trở lên. Bản đã build cũ cần được cập nhật thủ công lên v1.6.2 một lần; từ đó updater mới sẽ được dùng cho các bản sau.
