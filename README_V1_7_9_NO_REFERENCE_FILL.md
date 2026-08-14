# Import Localize v1.7.9 — Fill không dùng cột tham chiếu

## Thay đổi chính

- Bỏ hoàn toàn trường **Cột xác định hàng cuối** khỏi hộp Fill.
- Fill không còn đọc dữ liệu ở bất kỳ cột tham chiếu nào.
- Hàng cuối được lấy từ metadata nhẹ của Google Sheets: `gridProperties.rowCount`.
- Metadata được đọc với `includeGridData=false`, nên không phải chờ công thức hoặc dữ liệu từ tab/nguồn khác tính xong.
- Chỉ đọc hàng nguồn nhỏ (ví dụ `D2:I2`) để kiểm tra ô nguồn có dữ liệu/công thức hợp lệ.
- Sau đó dùng một `batchUpdate/copyPaste` để fill đến toàn bộ số hàng hiện có của tab.

## Ví dụ

Thiết lập:

- Tab: `Translate_Data`
- Hàng nguồn: `2`
- Cột: `D:I`
- Tab hiện có 5000 hàng

Ứng dụng sẽ fill `D2:I2` xuống `D3:I5000` mà không đọc cột A/B/C hay chờ dữ liệu ở các cột đó hoàn tất.

## Lưu ý

Fill dùng **số hàng hiện có của tab**, không phải hàng cuối có dữ liệu. Nếu tab có 10.000 hàng thì công thức sẽ được fill tới hàng 10.000.

## Kiểm tra

- `validate_ui_forms.py`: OK
- `compileall`: OK
- `pytest`: 25 passed, 2 skipped
