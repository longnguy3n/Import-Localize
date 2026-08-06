# Import Localize v1.7.4 — Performance Optimization

## Tối ưu Google session
- Giữ OAuth Credentials trong RAM; không đọc lại token JSON ở mỗi hành động.
- Tái sử dụng gspread Client, Spreadsheet và AuthorizedSession cho cùng Google Sheet.
- Cache danh sách worksheet trong 120 giây và tự vô hiệu hóa sau khi tạo/resize tab.
- Vẫn kiểm tra quyền Editor một lần cho mỗi tài khoản + Spreadsheet trong session.

## Tối ưu Fill
- Chỉ đọc cột tham chiếu từ hàng ngay sau hàng nguồn, không đọc lại toàn bộ cột từ hàng 1.
- Dùng majorDimension=COLUMNS để payload nhỏ hơn.
- Đọc hàng nguồn và cột tham chiếu song song.
- Fill tất cả nhóm cột bằng một batchUpdate duy nhất.
- Không copy lại chính hàng nguồn.

## Tối ưu Import
- Không dò encoding/delimiter hai lần cho cùng file trong một lượt import.
- Tái sử dụng worksheet metadata và kết nối session.
- Giữ cơ chế ghi nhiều tab theo batch hiện có.

## Tối ưu Download export_*
- Tải song song tối đa 4 tab.
- Tái sử dụng danh sách worksheet đã cache.
- Vẫn ghi file .part rồi đổi tên nguyên tử khi hoàn tất.

## Cache
Tất cả cache chỉ tồn tại trong RAM và bị xóa khi đăng xuất, đổi OAuth Client hoặc đóng ứng dụng.
