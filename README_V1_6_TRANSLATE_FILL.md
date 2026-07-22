# Import Localize v1.6.0 — Fill Translate_Data

## Tính năng mới
Trong card **Hành động** có thêm tùy chọn:

`Fill Translate_Data: sao chép D2:I2 xuống hết dữ liệu`

Khi bật, sau khi import CSV thành công ứng dụng sẽ:
1. Tìm tab `Translate_Data` (không phân biệt chữ hoa/thường).
2. Xác định hàng dữ liệu cuối dựa trên các cột `A:C`.
3. Kiểm tra vùng mẫu `D2:I2` có dữ liệu hoặc công thức.
4. Dùng Google Sheets API để sao chép `D2:I2` xuống `D:I` đến hàng cuối.

Nếu tab không tồn tại, vùng D2:I2 trống hoặc chưa có dữ liệu dưới hàng 2, import vẫn hoàn tất và Nhật ký hiển thị cảnh báo.

Tùy chọn được bật mặc định và được lưu trong cấu hình người dùng.

## Cài patch
```powershell
powershell -ExecutionPolicy Bypass -File .\apply_patch.ps1 -ProjectRoot "F:\Codes\Import_Localize"
```

Sau đó chạy:
```powershell
cd F:\Codes\Import_Localize\src
py main.py
```
