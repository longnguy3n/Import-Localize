# Import Localize v1.6.4 — Sửa updater Robocopy exit code 16

## Nguyên nhân
Updater cũ gọi `robocopy.exe` qua `Start-Process -ArgumentList`. Trên các đường dẫn có khoảng trắng như `Import Localize`, PowerShell có thể ghép và tách sai đối số. Robocopy nhận đường dẫn không hợp lệ và trả mã lỗi nghiêm trọng 16.

## Cách sửa
- Gọi `robocopy.exe` trực tiếp bằng mảng đối số PowerShell.
- Giữ nguyên đường dẫn có khoảng trắng.
- Kiểm tra source tồn tại trước khi backup/cài đặt.
- Ghi source, destination, output và exit code đầy đủ vào `update_apply.log`.
- Giữ quy ước Robocopy: mã 0–7 là thành công/cảnh báo, mã từ 8 trở lên là lỗi.

## Lưu ý
Bản updater đang cài bị lỗi nên cần cài v1.6.4 thủ công một lần. Từ v1.6.4, cập nhật tự động sẽ dùng cơ chế đã sửa.
