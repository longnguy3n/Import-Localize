# Import Localize v1.5.0 — cập nhật tự động

## Người dùng bản EXE

Mở:

```text
Cài đặt → Cập nhật
```

Nhập repository GitHub theo dạng:

```text
owner/repository
```

Sau đó nhấn **Kiểm tra cập nhật**. Khi có bản mới, ứng dụng sẽ:

1. Tải ZIP và file checksum từ GitHub Releases.
2. Xác minh SHA-256 trước khi giải nén.
3. Chuẩn bị bản cập nhật trong `%APPDATA%\Import Localize\updates`.
4. Đóng ứng dụng, sao lưu bản đang chạy, thay file và tự mở lại.
5. Tự khôi phục bản cũ nếu bước thay file thất bại.

Cấu hình, OAuth Client và token Google trong `%APPDATA%\Import Localize` không bị thay đổi.

> Tự cài đặt chỉ hoạt động với bản `Import_Localize.exe` dạng PyInstaller onedir trên Windows. Khi chạy source bằng Python, ứng dụng chỉ kiểm tra được phiên bản mới.

## Chuẩn bị GitHub repository

Tính năng dùng **GitHub Releases**, không tải source ZIP tự động của GitHub. Mỗi Release phải có đúng hai asset:

```text
Import_Localize_v1.5.0.zip
Import_Localize_v1.5.0.zip.sha256.txt
```

Hai file này được `build_app.py` tạo tự động.

Repository công khai dùng được ngay. Với repository riêng tư, máy người dùng phải có biến môi trường `IMPORT_LOCALIZE_GITHUB_TOKEN`; không nên phân phối token chung trong bản build.

## Build bản có sẵn nguồn cập nhật

```powershell
cd F:\Codes\Import_Localize

.\build_release.ps1 `
  -Version 1.5.0 `
  -OAuthClient "F:\Secrets\Import-Localize\oauth_client.json" `
  -GitHubRepository "owner/repository"
```

`GitHubRepository` và đường dẫn OAuth được nhớ trong `.build_config.json`, nên các lần build sau có thể chỉ cần:

```powershell
.\build_release.ps1 -Version 1.5.1
```

## Phát hành bản mới

Cài GitHub CLI, đăng nhập một lần:

```powershell
gh auth login
```

Sau khi build:

```powershell
.\publish_github_release.ps1 `
  -Version 1.5.0 `
  -Repository "owner/repository"
```

Script tạo Release `v1.5.0` và upload ZIP cùng checksum. Các máy đang dùng bản cũ sẽ nhận diện Release này khi kiểm tra cập nhật.

Có thể dùng ghi chú phát hành riêng:

```powershell
.\publish_github_release.ps1 `
  -Version 1.5.0 `
  -Repository "owner/repository" `
  -NotesFile ".\RELEASE_NOTES_1.5.0.md"
```

## Quy tắc phiên bản

Phiên bản phải tăng theo dạng SemVer:

```text
1.5.0 → 1.5.1 → 1.6.0 → 2.0.0
```

Tag GitHub Release phải là `v<phiên-bản>`, ví dụ `v1.5.1`.
