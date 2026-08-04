# Import Localize v1.7.0 — Download export_* tabs

## Chức năng

- Thêm nút **Tải các tab export_*** trong card Hành động.
- Người dùng chọn thư mục lưu trực tiếp trên máy.
- Chỉ tải các tab có tên bắt đầu chính xác bằng `export_`.
- CSV được lấy trực tiếp từ endpoint export của Google Sheets, không parse hoặc tạo lại.
- Tên file: `[Tên Google Sheet] - [Tên tab].csv`.
- Hỗ trợ progress, log, dừng an toàn và ghi file tạm `.part`.
- Nhớ thư mục tải gần nhất.

## Quyền Google

Tài khoản OAuth hiện tại phải có quyền Editor với Google Sheet đã nhập link.
