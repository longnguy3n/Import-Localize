param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [string]$Title = "",
    [string]$NotesFile = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "Chưa cài GitHub CLI (gh). Tải tại https://cli.github.com/ rồi chạy gh auth login."
}

$NormalizedVersion = $Version.TrimStart('v', 'V')
$ReleaseDir = Join-Path $ProjectRoot "release\v$NormalizedVersion"
$Zip = Join-Path $ReleaseDir "Import_Localize_v$NormalizedVersion.zip"
$Checksum = "$Zip.sha256.txt"

if (-not (Test-Path $Zip)) {
    throw "Không tìm thấy ZIP: $Zip. Hãy build trước."
}
if (-not (Test-Path $Checksum)) {
    throw "Không tìm thấy checksum: $Checksum"
}

$Tag = "v$NormalizedVersion"
if (-not $Title) {
    $Title = "Import Localize v$NormalizedVersion"
}

$args = @(
    "release", "create", $Tag,
    $Zip, $Checksum,
    "--repo", $Repository,
    "--title", $Title
)
if ($NotesFile) {
    $args += @("--notes-file", $NotesFile)
} else {
    $args += @("--generate-notes")
}

& gh @args
if ($LASTEXITCODE -ne 0) {
    throw "Không thể tạo GitHub Release."
}

Write-Host "Đã phát hành $Tag và upload ZIP + checksum." -ForegroundColor Green
