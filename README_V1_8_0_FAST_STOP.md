# Import Localize v1.8.0 — Fast Stop

## Mục tiêu
Giảm thời gian chờ sau khi nhấn **Dừng** trong Import, Fill và tải `export_*`.

## Thay đổi
- Worker dùng cả `threading.Event` và `QThread.requestInterruption()`.
- Các request Google có `cancel_callback` dùng connect-timeout 3 giây và read-timeout tối đa 6 giây.
- Backoff retry kiểm tra nút Dừng mỗi 50 ms.
- Gói upload nhỏ hơn để mỗi request kết thúc nhanh hơn.
- Cấu trúc tab chia tối đa 10 thao tác/request; batchClear tối đa 25 tab/request.
- Đọc CSV kiểm tra cancel mỗi 50 dòng thay vì 500 dòng.
- Download `export_*` poll future mỗi 50 ms thay vì chờ một request hoàn tất.
- gspread metadata timeout giảm xuống 6 giây.

## Giới hạn
Một HTTP request đã được gửi tới Google không thể được thu hồi từ phía server. Nếu nhấn Dừng đúng lúc Google đã nhận một POST, thao tác đó có thể vẫn hoàn tất ở phía Google; app sẽ không gửi bước tiếp theo. Trong trường hợp request đang chờ socket, thời gian chờ tối đa được giảm mạnh so với 120 giây trước đây.
