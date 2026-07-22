# Import Localize v1.3.0 — Một sheet / Nhiều sheet

## Nhiều sheet

- Tên file: `[Tên Google Sheet] - [Tên tab].csv`.
- Mỗi file được nhập vào một tab riêng.
- Tên Google Spreadsheet trong tên file được đối chiếu với link đích.
- Tab đã có bị thay thế toàn bộ; tab chưa có được tạo mới.

## Một sheet

- Nhập tên tab trực tiếp trong card Google Sheet đích.
- Chỉ file nằm trên cùng trong danh sách CSV được sử dụng.
- Các file phía dưới được giữ trong danh sách nhưng không được nhập.
- Tên file không cần theo format nhiều sheet.

## Mặc định cố định

- Dòng đầu CSV luôn là tiêu đề.
- Không thêm cột nguồn file.
- Luôn thay thế toàn bộ trang tính hiện tại.
