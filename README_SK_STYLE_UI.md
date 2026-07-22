# Import Localize v1.1.0 — SK-style UI

Bản này giữ nguyên toàn bộ nghiệp vụ CSV/OAuth/Google Sheets của v1.0.0 và thay hệ thống giao diện theo cùng ngôn ngữ thiết kế với SK Export.

## Điểm chính

- Header cố định 64 px, logo, version badge, nút Cài đặt/Hướng dẫn/Theme dạng icon.
- Bốn card: **Tệp CSV**, **Google Sheet**, **Hành động**, **Nhật ký**.
- Card có icon, tiêu đề, mô tả, viền và bóng đổ nhẹ.
- Card phần trên giữ chiều cao theo nội dung; card Nhật ký nhận toàn bộ chiều cao còn dư.
- Nhật ký dùng từng dòng có màu theo cấp độ `INFO`, `SUCCESS`, `WARNING`, `FAIL` và neo dòng mới ở đáy.
- Từ 1040 px trở lên, card Tệp CSV và Google Sheet nằm cạnh nhau, chia đều chiều rộng.
- Dưới 1040 px, hai card tự xếp dọc.
- Form chính, Cài đặt và Hướng dẫn vẫn là `.ui`, có thể chỉnh trực tiếp bằng Qt Designer.
- Light/Dark theme dùng chung hệ màu xanh và mật độ bố cục của SK Export.

## File UI

```text
src/import_localize/ui/forms/main_window.ui
src/import_localize/ui/forms/settings_dialog.ui
src/import_localize/ui/forms/help_dialog.ui
```

## Kiểm tra sau khi chỉnh Qt Designer

```powershell
py .\validate_ui_forms.py
py -m compileall -q .\src
```

Không đổi các `objectName` được liệt kê trong `validate_ui_forms.py`.
