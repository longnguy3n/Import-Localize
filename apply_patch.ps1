param(
    [string]$ProjectRoot = "F:\Codes\Import_Localize"
)

$ErrorActionPreference = "Stop"
$PatchRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)

if (-not (Test-Path (Join-Path $ProjectRoot "src\main.py"))) {
    throw "Không tìm thấy project Import Localize tại: $ProjectRoot"
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupRoot = Join-Path $ProjectRoot ".patch_backups\v1.5.0_$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

$Items = @(
    ".gitignore",
    "README.md",
    "README_V1_5_AUTO_UPDATE.md",
    "build_app.py",
    "build_release.ps1",
    "publish_github_release.ps1",
    "validate_ui_forms.py",
    "tests\test_update_service.py",
    "src\import_localize\app\constants.py",
    "src\import_localize\app\paths.py",
    "src\import_localize\config\settings.py",
    "src\import_localize\services\update_service.py",
    "src\import_localize\workers\update_worker.py",
    "src\import_localize\ui\dialogs.py",
    "src\import_localize\ui\main_window.py",
    "src\import_localize\ui\forms\main_window.ui",
    "src\import_localize\ui\forms\settings_dialog.ui",
    "src\import_localize\ui\forms\help_dialog.ui",
    "src\themes\light.qss",
    "src\themes\dark.qss"
)

foreach ($RelativePath in $Items) {
    $Source = Join-Path $PatchRoot $RelativePath
    if (-not (Test-Path $Source)) {
        throw "Patch thiếu file: $RelativePath"
    }
    $Destination = Join-Path $ProjectRoot $RelativePath
    if (Test-Path $Destination) {
        $Backup = Join-Path $BackupRoot $RelativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $Backup) -Force | Out-Null
        Copy-Item $Destination $Backup -Force
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
    Copy-Item $Source $Destination -Force
}

Get-ChildItem -Path $ProjectRoot -Directory -Filter "__pycache__" -Recurse -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $ProjectRoot -File -Filter "*.pyc" -Recurse -ErrorAction SilentlyContinue |
    Remove-Item -Force

Push-Location $ProjectRoot
try {
    & py .\validate_ui_forms.py
    if ($LASTEXITCODE -ne 0) { throw "Kiểm tra UI thất bại." }
    & py -m compileall -q .\src .\build_app.py
    if ($LASTEXITCODE -ne 0) { throw "Kiểm tra cú pháp thất bại." }
} finally {
    Pop-Location
}

Write-Host "Đã cập nhật Import Localize lên v1.5.0." -ForegroundColor Green
Write-Host "Backup file cũ: $BackupRoot" -ForegroundColor DarkGray
Write-Host "Mở app → Cài đặt → Cập nhật để cấu hình owner/repository." -ForegroundColor Green
