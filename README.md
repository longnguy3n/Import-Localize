# Import Localize v1.3.0

Ứng dụng desktop nhập file CSV vào Google Sheets theo hai chế độ:

- **Nhiều sheet:** mỗi CSV vào một tab riêng theo tên file.
- **Một sheet:** chỉ file nằm trên cùng trong danh sách được nhập vào tab do người dùng nhập.

## Chế độ nhiều sheet

Tên file phải có dạng:

```text
[Tên Google Sheet] - [Tên tab cần import].csv
```

Ví dụ:

```text
DG_Localization - import_vi.csv
DG_Localization - import_pt.csv
DG_Localization - import_en.csv
```

Ứng dụng đối chiếu phần `[Tên Google Sheet]` trong tên file với tên Spreadsheet từ link. Mỗi tab đã có sẽ bị thay thế toàn bộ; tab chưa có được tạo mới.

## Chế độ một sheet

- Nhập tên tab trực tiếp trong card **Google Sheet đích**.
- Chỉ file nằm trên cùng trong card **Tệp CSV** được sử dụng.
- Các file phía dưới hiển thị `Không nhập` và không được upload.
- Tên file không cần theo format của chế độ nhiều sheet.

## Mặc định cố định

- Dòng đầu CSV luôn là tiêu đề.
- Không thêm cột nguồn file.
- Luôn thay thế toàn bộ dữ liệu của tab đích.

## Giao diện v1.3.0

Thứ tự card trên màn hình chính:

1. **Google Sheet đích**
2. **Tệp CSV**
3. **Hành động**
4. **Nhật ký**

Card Google Sheet đích chỉ còn Link Sheet, Kiểu nhập, Tên Sheet khi dùng chế độ một sheet, và cách Google xử lý dữ liệu.

## Cài đặt

```powershell
cd F:\Codes\Import_Localize
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## Chạy source

```powershell
cd F:\Codes\Import_Localize\src
py main.py
```

## Google OAuth

Trong **Cài đặt**:

1. Chọn `oauth_client.json` loại Desktop app.
2. Nhấn **Đăng nhập Google**.
3. Tài khoản phải có quyền Editor với bảng tính được dán link.

Token được lưu riêng tại:

```text
%APPDATA%\Import Localize\google_oauth_token.json
```

## Chỉnh giao diện bằng Qt Designer

```powershell
.\open_designer.ps1 -Form main
```

Form chính:

```text
src/import_localize/ui/forms/main_window.ui
```

Sau khi chỉnh:

```powershell
py .\validate_ui_forms.py
```

## Build

```powershell
py .\build_app.py --version 1.3.0
```

Hoặc đóng gói OAuth Client cho bản phát hành nội bộ:

```powershell
py .\build_app.py `
  --version 1.3.0 `
  --oauth-client "F:\Secrets\Import-Localize\oauth_client.json"
```

## Cập nhật tự động

Từ v1.5.0, bản EXE có thể kiểm tra và tự cài bản mới tại **Cài đặt → Cập nhật** thông qua GitHub Releases. Xem [README_V1_5_AUTO_UPDATE.md](README_V1_5_AUTO_UPDATE.md) để cấu hình repository, build và phát hành.
