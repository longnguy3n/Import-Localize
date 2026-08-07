# Import Localize v1.7.7 — loại key trùng trong upload_en

- Chỉ áp dụng cho tab đích `upload_en` (không phân biệt hoa/thường).
- Tự tìm header `key` không phân biệt hoa/thường.
- Giữ lần xuất hiện đầu tiên của mỗi key, bỏ các dòng lặp phía sau.
- Key rỗng được giữ nguyên.
- Giá trị key vẫn phân biệt hoa/thường (`Foo` và `foo` là hai key khác nhau).
- CSV gốc trên máy không bị sửa; chỉ dữ liệu chuẩn bị upload được lọc.
- Nhật ký hiển thị số dòng bị loại và preview key trùng.
