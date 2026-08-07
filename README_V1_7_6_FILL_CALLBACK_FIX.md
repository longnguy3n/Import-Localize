# Import Localize v1.7.6

Sửa lỗi Fill dữ liệu:

`name 'log_callback' is not defined`

Nguyên nhân: `fill_translate_data_columns()` dùng callback log cho cơ chế retry nhưng chữ ký hàm bị thiếu tham số `log_callback`.

Bản v1.7.6 bổ sung tham số này và giữ nguyên cơ chế retry/timeout của v1.7.5.
