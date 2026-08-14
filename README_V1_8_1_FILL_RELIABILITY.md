# Import Localize v1.8.1 — Fill reliability

## Sửa lỗi
- Không còn ép request Fill xuống read-timeout 6 giây.
- Request Fill chạy trong một HTTP session riêng ở daemon thread với timeout đọc 180 giây.
- Worker vẫn poll nút Dừng mỗi 50 ms nên Dừng không phải chờ request mạng kết thúc.
- Sau batchUpdate, ứng dụng đọc lại một số ô đích bằng `valueRenderOption=FORMULA`.
- Chỉ phát `SUCCESS` khi các ô đích đã thực sự có công thức/giá trị.
- Nếu Google timeout nhưng request đã được áp dụng, app xác minh trạng thái trước khi quyết định retry.
- Trạng thái `applied=False` không còn bị phát thành công; UI sẽ báo Fill chưa được thực hiện.

## Lưu ý khi bấm Dừng
Nếu POST đã tới Google trước thời điểm bấm Dừng, phía Google vẫn có thể hoàn tất request đó sau khi worker đã dừng chờ. Đây là giới hạn của HTTP đồng bộ; app ghi cảnh báo rõ trong log.

## Kiểm tra
- `compileall`: thành công
- 4 file `.ui`: XML hợp lệ
- `pytest`: 25 passed, 2 skipped
