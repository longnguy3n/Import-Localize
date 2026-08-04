# Import Localize v1.7.1 — Fill dữ liệu tùy chọn

## Thay đổi
Nút **Fill Translate_Data** giờ mở hộp thiết lập trước khi chạy.

Các trường có thể chọn:
- **Tab cần fill** — mặc định `Translate_Data`.
- **Hàng nguồn** — mặc định `2`.
- **Các cột cần fill** — hỗ trợ `D:I`, `D,F,H:J`, `AA:AC`.
- **Cột xác định hàng cuối** — mặc định `A`.

Ứng dụng sao chép ô nguồn xuống hàng cuối giống thao tác kéo Fill trong Google Sheets:
- Công thức tương đối tự điều chỉnh theo từng hàng.
- Giá trị và định dạng cũng được sao chép.
- Các cột không liền nhau được xử lý bằng nhiều `copyPaste` request trong một batch.
- `ARRAYFORMULA` được phát hiện và không bị fill lặp.

Thiết lập gần nhất được lưu trong `%APPDATA%\Import Localize\config.json`.

## Ví dụ
- Tab: `Translate_Data`
- Hàng nguồn: `2`
- Cột: `D:I`
- Cột xác định hàng cuối: `A`

Kết quả: sao chép `D2:I2` xuống đến hàng cuối có dữ liệu trong cột A.
