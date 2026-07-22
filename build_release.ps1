param(
    [string]$Version = "1.5.0",
    [string]$OAuthClient = "",
    [string]$GitHubRepository = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Máy build cần Python. Máy nhận bản build không cần cài Python."
}

$args = @("build_app.py", "--version", $Version)
if ($OAuthClient) {
    $args += @("--oauth-client", $OAuthClient)
}
if ($GitHubRepository) {
    $args += @("--github-repo", $GitHubRepository)
}

& py @args
if ($LASTEXITCODE -ne 0) {
    throw "Build thất bại với mã $LASTEXITCODE"
}

Write-Host ""
Write-Host "Bản phát hành nằm tại: release\v$Version" -ForegroundColor Green
Write-Host "Upload ZIP và file .sha256.txt lên GitHub Release v$Version để app tự cập nhật." -ForegroundColor Green
Write-Host "Máy nhận chỉ cần giải nén ZIP và chạy Import_Localize.exe." -ForegroundColor Green
