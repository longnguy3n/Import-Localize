$token = Join-Path $env:APPDATA "Import Localize\google_oauth_token.json"
if (Test-Path $token) {
    Remove-Item $token -Force
    Write-Host "Đã xóa phiên Google: $token"
} else {
    Write-Host "Chưa có phiên Google được lưu."
}
