# Import Localize v1.7.5 — Timeout Recovery

## Mục tiêu
Khắc phục lỗi `requests.exceptions.ReadTimeout` khi Google Sheets API xử lý batch lớn lâu hơn 60 giây.

## Thay đổi
- Tăng timeout Google Sheets từ 60 lên 120 giây.
- Retry tối đa 4 lần với exponential backoff cho request idempotent.
- Chia thao tác tạo/resize/freeze tab thành batch tối đa 20 request.
- Chia batchClear thành nhóm tối đa 50 range.
- Nếu `addSheet` timeout, không retry mù: ứng dụng đọc lại metadata từ Google rồi chỉ thực hiện phần còn thiếu.
- Ghi dữ liệu `values:batchUpdate`, Fill và tải CSV có retry an toàn.
- Kiểm tra quyền Editor lần đầu cũng có retry khi mạng chậm.
- Nút Dừng vẫn phản hồi trong thời gian backoff.

## Lưu ý
Nếu mạng mất hoàn toàn hoặc Google Sheets API không phản hồi sau 4 lần thử, ứng dụng vẫn dừng và báo lỗi rõ ràng thay vì treo vô hạn.
