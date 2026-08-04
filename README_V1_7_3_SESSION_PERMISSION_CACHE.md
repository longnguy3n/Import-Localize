# Import Localize v1.7.3 — Session Editor Permission Cache

## Thay đổi

- Quyền Editor chỉ được kiểm tra một lần cho mỗi Google Spreadsheet trong một phiên mở ứng dụng.
- Import CSV, Fill dữ liệu và tải các tab `export_*` dùng lại kết quả đã xác nhận.
- Nếu đổi sang link của Spreadsheet khác, ứng dụng vẫn kiểm tra quyền một lần cho file mới.
- Nếu đổi tài khoản Google hoặc cài OAuth Client khác, cache trong RAM được xóa.
- Cache không được lưu xuống ổ đĩa và tự mất khi đóng ứng dụng.

## Nhật ký

Lần đầu với một Spreadsheet:

```text
Đã xác nhận quyền Editor với 'DG_Localization'.
```

Các tác vụ tiếp theo trong cùng session:

```text
Bỏ qua kiểm tra quyền Editor: 'DG_Localization' đã được xác nhận trong session này.
```

## An toàn

Ứng dụng vẫn mở Spreadsheet ở từng tác vụ. Nếu quyền truy cập bị thu hồi và Google trả lỗi khi mở file, cache tương ứng sẽ bị xóa để lần sau kiểm tra lại.
