# Import Localize v1.4.0

## Thay đổi

- Có nút **Lên/Xuống** trong card Tệp CSV và phím tắt `Alt+↑` / `Alt+↓`.
- Chế độ **Một sheet** luôn dùng đúng file đang nằm trên cùng sau khi sắp xếp.
- Chế độ nhiều sheet giữ thứ tự hiển thị khi đọc, ghi log và tổng hợp dữ liệu.
- Import nhanh dùng Google Sheets API theo lô:
  - chỉ đọc danh sách tab một lần;
  - tạo/resize/freeze nhiều tab trong một request;
  - xóa dữ liệu cũ của nhiều tab trong một request;
  - ghi nhiều tab bằng `values:batchUpdate` với chunk động theo số ô và kích thước payload.
- Build PyInstaller dạng `onedir`; máy sử dụng không cần Python.
- OAuth Client được đóng gói vào bản phát hành, nên máy cài không phải chọn lại `oauth_client.json`.
- `google_oauth_token.json` không được đóng gói. Mỗi máy đăng nhập Google một lần để tạo token riêng.

## Build bản dùng cho máy khác

Lần đầu:

```powershell
cd F:\Codes\Import_Localize
.\build_release.ps1 `
  -Version 1.4.0 `
  -OAuthClient "F:\Secrets\Import-Localize\oauth_client.json"
```

Đường dẫn OAuth được nhớ trong `.build_config.json` (đã bị Git bỏ qua). Các lần sau chỉ cần:

```powershell
.\build_release.ps1 -Version 1.4.1
```

Kết quả:

```text
release\v1.4.0\Import_Localize\
release\v1.4.0\Import_Localize_v1.4.0.zip
```

Máy nhận:

1. Giải nén toàn bộ ZIP.
2. Chạy `Import_Localize.exe`.
3. Lần đầu nhấn **Cài đặt → Đăng nhập Google**.
4. Không cần cài Python và không cần chọn file OAuth.
