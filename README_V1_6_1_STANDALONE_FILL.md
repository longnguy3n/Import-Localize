# Import Localize v1.6.1 — Fill Translate_Data độc lập

## Thay đổi
- Bỏ checkbox Fill Translate_Data khỏi luồng Import.
- Import CSV chỉ import dữ liệu, không tự chạy fill.
- Thêm nút riêng **Fill Translate_Data** trong card Hành động.
- Nút Fill chỉ cần Link Google Sheet và phiên Google OAuth hợp lệ; không cần chọn CSV.
- Nút Dừng dùng chung cho tác vụ Import hoặc Fill đang chạy.
- Progress và Nhật ký hiển thị riêng theo tác vụ.

## Cơ chế Fill
- Tìm tab `Translate_Data` không phân biệt hoa/thường.
- Xác định hàng cuối dựa trên dữ liệu A:C.
- Sao chép D2:I2 xuống D2:I<hàng cuối>.
- Giữ công thức, giá trị và định dạng theo `PASTE_NORMAL`.
