from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import requests

from import_localize.app.constants import (
    APP_ID,
    APP_VERSION,
    UPDATE_ASSET_PREFIX,
    UPDATE_DOWNLOAD_CHUNK_BYTES,
    UPDATE_REQUEST_TIMEOUT_SECONDS,
)
from import_localize.app.paths import UPDATE_CACHE_DIR, application_dir

ProgressCallback = Callable[[int, str], None] | None
CancelCallback = Callable[[], bool] | None

_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256_PATTERN = re.compile(r"\b([a-fA-F0-9]{64})\b")


class UpdateError(RuntimeError):
    pass


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True, slots=True)
class UpdateRelease:
    repository: str
    version: str
    tag_name: str
    title: str
    notes: str
    html_url: str
    asset_name: str
    download_url: str
    checksum_url: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PreparedUpdate:
    release: UpdateRelease
    script_path: Path
    staging_dir: Path


def normalize_repository(value: str) -> str:
    repository = (value or "").strip()
    repository = repository.removeprefix("https://github.com/").strip("/")
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise UpdateError(
            "Kho cập nhật phải có dạng owner/repository, ví dụ longg/Import_Localize."
        )
    return repository


def _version_parts(value: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    raw = (value or "").strip().lstrip("vV")
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?",
        raw,
    )
    if not match:
        raise UpdateError(f"Phiên bản không hợp lệ: {value}")
    core = tuple(int(match.group(index)) for index in (1, 2, 3))
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    return core, prerelease


def compare_versions(left: str, right: str) -> int:
    """Return -1, 0 or 1 using a small SemVer-compatible comparator."""
    left_core, left_pre = _version_parts(left)
    right_core, right_pre = _version_parts(right)
    if left_core != right_core:
        return -1 if left_core < right_core else 1
    if left_pre is None and right_pre is None:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1

    for left_item, right_item in zip(left_pre, right_pre):
        if left_item == right_item:
            continue
        left_numeric = left_item.isdigit()
        right_numeric = right_item.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_item) < int(right_item) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    return compare_versions(candidate, current) > 0


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_ID}/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("IMPORT_LOCALIZE_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_latest_release(
    repository: str,
    *,
    cancel_callback: CancelCallback = None,
) -> UpdateRelease:
    repository = normalize_repository(repository)
    if cancel_callback and cancel_callback():
        raise UpdateCancelled("Đã dừng kiểm tra cập nhật.")

    url = f"https://api.github.com/repos/{repository}/releases/latest"
    try:
        response = requests.get(
            url,
            headers=_headers(),
            timeout=UPDATE_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise UpdateError(f"Không thể kết nối GitHub để kiểm tra cập nhật: {exc}") from exc

    if response.status_code == 404:
        raise UpdateError(
            "Không tìm thấy bản phát hành GitHub. Hãy kiểm tra tên repository và "
            "đảm bảo đã tạo ít nhất một Release công khai."
        )
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining", "")
        detail = " Có thể GitHub đã giới hạn số lần kiểm tra." if remaining == "0" else ""
        raise UpdateError(f"GitHub từ chối yêu cầu cập nhật (HTTP 403).{detail}")
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpdateError(f"Phản hồi cập nhật từ GitHub không hợp lệ: {exc}") from exc

    tag_name = str(payload.get("tag_name") or "").strip()
    version = tag_name.lstrip("vV")
    _version_parts(version)
    assets = payload.get("assets") or []
    expected_name = f"{UPDATE_ASSET_PREFIX}{version}.zip"

    zip_asset = next(
        (
            item
            for item in assets
            if str(item.get("name") or "").casefold() == expected_name.casefold()
        ),
        None,
    )
    if zip_asset is None:
        zip_asset = next(
            (
                item
                for item in assets
                if str(item.get("name") or "").startswith(UPDATE_ASSET_PREFIX)
                and str(item.get("name") or "").lower().endswith(".zip")
            ),
            None,
        )
    if zip_asset is None:
        raise UpdateError(
            f"Release {tag_name} không có file {expected_name}. "
            "Hãy upload ZIP được tạo bởi build_app.py."
        )

    zip_name = str(zip_asset.get("name") or "")
    checksum_names = {
        f"{zip_name}.sha256.txt".casefold(),
        f"{zip_name}.sha256".casefold(),
    }
    checksum_asset = next(
        (
            item
            for item in assets
            if str(item.get("name") or "").casefold() in checksum_names
        ),
        None,
    )
    if checksum_asset is None:
        raise UpdateError(
            f"Release {tag_name} thiếu checksum cho {zip_name}. "
            "Hãy upload file .sha256.txt đi kèm."
        )

    download_url = str(zip_asset.get("browser_download_url") or "")
    checksum_url = str(checksum_asset.get("browser_download_url") or "")
    if not download_url or not checksum_url:
        raise UpdateError("Release GitHub thiếu đường dẫn tải xuống hợp lệ.")

    return UpdateRelease(
        repository=repository,
        version=version,
        tag_name=tag_name,
        title=str(payload.get("name") or tag_name),
        notes=str(payload.get("body") or "").strip(),
        html_url=str(payload.get("html_url") or ""),
        asset_name=zip_name,
        download_url=download_url,
        checksum_url=checksum_url,
        size_bytes=int(zip_asset.get("size") or 0),
    )


def can_install_updates() -> bool:
    return bool(sys.platform.startswith("win") and getattr(sys, "frozen", False))


def _check_cancel(callback: CancelCallback) -> None:
    if callback and callback():
        raise UpdateCancelled("Đã dừng tải bản cập nhật.")


def _download_file(
    url: str,
    destination: Path,
    *,
    progress_callback: ProgressCallback = None,
    cancel_callback: CancelCallback = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(
            url,
            headers=_headers(),
            stream=True,
            timeout=(UPDATE_REQUEST_TIMEOUT_SECONDS, 60),
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            received = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(UPDATE_DOWNLOAD_CHUNK_BYTES):
                    _check_cancel(cancel_callback)
                    if not chunk:
                        continue
                    handle.write(chunk)
                    received += len(chunk)
                    if progress_callback:
                        ratio = received / total if total else 0
                        value = progress_start + int((progress_end - progress_start) * ratio)
                        if total:
                            text = f"Đang tải bản cập nhật: {received / 1048576:.1f}/{total / 1048576:.1f} MB"
                        else:
                            text = f"Đang tải bản cập nhật: {received / 1048576:.1f} MB"
                        progress_callback(min(progress_end, value), text)
    except requests.RequestException as exc:
        destination.unlink(missing_ok=True)
        raise UpdateError(f"Không thể tải bản cập nhật: {exc}") from exc


def _read_expected_checksum(url: str, cancel_callback: CancelCallback) -> str:
    _check_cancel(cancel_callback)
    try:
        response = requests.get(
            url,
            headers=_headers(),
            timeout=UPDATE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateError(f"Không thể tải checksum của bản cập nhật: {exc}") from exc
    match = _SHA256_PATTERN.search(response.text)
    if not match:
        raise UpdateError("File checksum của bản cập nhật không chứa SHA-256 hợp lệ.")
    return match.group(1).lower()


def _sha256(path: Path, cancel_callback: CancelCallback = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            _check_cancel(cancel_callback)
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise UpdateError(f"ZIP cập nhật chứa đường dẫn không an toàn: {info.filename}")
            # Reject Unix symlink entries.
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise UpdateError(f"ZIP cập nhật chứa symbolic link: {info.filename}")
            target = (destination / Path(*member.parts)).resolve()
            if destination_root not in target.parents and target != destination_root:
                raise UpdateError(f"ZIP cập nhật vượt ra ngoài thư mục tạm: {info.filename}")
        bundle.extractall(destination)


def _find_application_payload(extracted_dir: Path) -> Path:
    direct = extracted_dir / "Import_Localize.exe"
    if direct.is_file():
        return extracted_dir
    candidates = [
        path.parent
        for path in extracted_dir.rglob("Import_Localize.exe")
        if path.is_file()
    ]
    if len(candidates) != 1:
        raise UpdateError(
            "Không xác định được thư mục ứng dụng trong ZIP cập nhật. "
            "ZIP phải chứa đúng một Import_Localize.exe."
        )
    return candidates[0]


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _write_apply_script(
    *,
    staging_dir: Path,
    payload_dir: Path,
    target_dir: Path,
    release: UpdateRelease,
) -> Path:
    """Create a self-contained updater that survives the application exit.

    The script performs a write-permission probe before acknowledging startup.
    When the installation directory requires administrator rights, it relaunches
    itself with UAC and only creates the ready flag after elevation succeeds.
    """
    script = staging_dir / "apply_update.ps1"
    ready_path = staging_dir / "updater_ready.flag"
    log_path = staging_dir / "update_apply.log"
    result_path = staging_dir / "update_result.txt"

    template = r'''param([switch]$Elevated)
$ErrorActionPreference = 'Stop'
$PidToWait = __PID_TO_WAIT__
$SourceDir = __SOURCE_DIR__
$TargetDir = __TARGET_DIR__
$StagingDir = __STAGING_DIR__
$BackupDir = Join-Path $StagingDir 'backup_current'
$ExePath = Join-Path $TargetDir '__EXE_NAME__'
$ReadyPath = __READY_PATH__
$LogPath = __LOG_PATH__
$ResultPath = __RESULT_PATH__
$BackupReady = $false

function Write-UpdateLog([string]$Message) {
    $Line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogPath -Value $Line -Encoding UTF8
}

function Invoke-Robocopy([string]$From, [string]$To) {
    if (-not (Test-Path -LiteralPath $From)) {
        throw "Robocopy source does not exist: $From"
    }

    New-Item -ItemType Directory -Path $To -Force | Out-Null
    Write-UpdateLog "Robocopy: '$From' -> '$To'"

    # Do not use Start-Process -ArgumentList here. Start-Process joins the
    # argument array into one command line and can split paths containing
    # spaces, which makes Robocopy return fatal exit code 16. Calling the
    # executable directly with an argument array preserves each path.
    $Arguments = @(
        $From,
        $To,
        '/MIR',
        '/COPY:DAT',
        '/DCOPY:DAT',
        '/R:3',
        '/W:1',
        '/XJ',
        '/FFT',
        '/NFL',
        '/NDL',
        '/NJH',
        '/NJS',
        '/NP'
    )

    $Output = & robocopy.exe @Arguments 2>&1
    $ExitCode = $LASTEXITCODE

    foreach ($Line in $Output) {
        if ($null -ne $Line -and $Line.ToString().Trim()) {
            Write-UpdateLog ("Robocopy: " + $Line.ToString().Trim())
        }
    }

    # Robocopy codes 0..7 are success/warning states. Codes >= 8 are errors.
    if ($ExitCode -gt 7) {
        throw "Robocopy failed with exit code $ExitCode. Source='$From'; Destination='$To'"
    }

    Write-UpdateLog "Robocopy completed with exit code $ExitCode."
}

function Test-TargetWritable {
    $Probe = Join-Path $TargetDir ('.update_probe_' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [System.IO.File]::WriteAllText($Probe, 'probe')
        Remove-Item $Probe -Force
        return $true
    } catch {
        try { if (Test-Path $Probe) { Remove-Item $Probe -Force } } catch {}
        return $false
    }
}

function Start-ElevatedUpdater {
    Write-UpdateLog 'Installation folder needs administrator permission; requesting UAC.'
    $Arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"'),
        '-Elevated'
    )
    try {
        $ElevatedProcess = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList $Arguments -WorkingDirectory $StagingDir `
            -Verb RunAs -PassThru
    } catch {
        throw "Administrator permission was not granted: $($_.Exception.Message)"
    }

    $Deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $Deadline) {
        if (Test-Path $ReadyPath) { return }
        if ($ElevatedProcess.HasExited) {
            throw "Elevated updater exited before it was ready (code $($ElevatedProcess.ExitCode))."
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'Timed out while waiting for administrator permission.'
}

try {
    Remove-Item $ReadyPath -Force -ErrorAction SilentlyContinue
    Remove-Item $ResultPath -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "Updater started. Elevated=$Elevated"

    if (-not (Test-TargetWritable)) {
        if ($Elevated) {
            throw "The installation folder is still not writable after elevation: $TargetDir"
        }
        Start-ElevatedUpdater
        exit 0
    }

    Set-Content -Path $ReadyPath -Value 'ready' -Encoding ASCII
    Write-UpdateLog 'Updater is ready; waiting for the application to exit.'

    $ExitDeadline = (Get-Date).AddSeconds(25)
    while (Get-Process -Id $PidToWait -ErrorAction SilentlyContinue) {
        if ((Get-Date) -ge $ExitDeadline) {
            Write-UpdateLog 'Application did not exit in time; forcing it to close.'
            Stop-Process -Id $PidToWait -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 800
            break
        }
        Start-Sleep -Milliseconds 250
    }

    if (Test-Path $BackupDir) { Remove-Item $BackupDir -Recurse -Force }
    Write-UpdateLog 'Creating a full backup in the update cache.'
    Invoke-Robocopy $TargetDir $BackupDir
    $BackupReady = $true

    Write-UpdateLog 'Installing version __RELEASE_VERSION__.'
    Invoke-Robocopy $SourceDir $TargetDir

    if (-not (Test-Path $ExePath)) {
        throw "Updated executable is missing: $ExePath"
    }

    Write-UpdateLog 'Starting the updated application.'
    $Started = Start-Process -FilePath $ExePath -WorkingDirectory $TargetDir -PassThru
    Start-Sleep -Seconds 2
    if ($Started.HasExited) {
        throw "The updated application exited immediately with code $($Started.ExitCode)."
    }

    Set-Content -Path $ResultPath -Value 'success' -Encoding UTF8
    Write-UpdateLog 'Update completed successfully.'
    if (Test-Path $BackupDir) { Remove-Item $BackupDir -Recurse -Force }
} catch {
    $Failure = $_.Exception.Message
    Write-UpdateLog "Update failed: $Failure"
    Set-Content -Path $ResultPath -Value ("failed: " + $Failure) -Encoding UTF8

    if ($BackupReady -and (Test-Path $BackupDir)) {
        try {
            Write-UpdateLog 'Restoring the previous version.'
            Invoke-Robocopy $BackupDir $TargetDir
            if (Test-Path $ExePath) {
                Start-Process -FilePath $ExePath -WorkingDirectory $TargetDir | Out-Null
            }
            Write-UpdateLog 'Rollback completed.'
        } catch {
            Write-UpdateLog "Rollback failed: $($_.Exception.Message)"
        }
    }

    try {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "Không thể cài bản cập nhật.`n`n$Failure`n`nLog: $LogPath",
            'Import Localize Update'
        ) | Out-Null
    } catch {}
    exit 1
}
'''

    replacements = {
        "__PID_TO_WAIT__": str(os.getpid()),
        "__SOURCE_DIR__": _ps_quote(payload_dir),
        "__TARGET_DIR__": _ps_quote(target_dir),
        "__STAGING_DIR__": _ps_quote(staging_dir),
        "__EXE_NAME__": Path(sys.executable).name,
        "__READY_PATH__": _ps_quote(ready_path),
        "__LOG_PATH__": _ps_quote(log_path),
        "__RESULT_PATH__": _ps_quote(result_path),
        "__RELEASE_VERSION__": release.version,
    }
    content = template
    for marker, value in replacements.items():
        content = content.replace(marker, value)
    script.write_text(content.strip() + "\n", encoding="utf-8-sig")
    return script

def prepare_update(
    release: UpdateRelease,
    *,
    progress_callback: ProgressCallback = None,
    cancel_callback: CancelCallback = None,
) -> PreparedUpdate:
    if not can_install_updates():
        raise UpdateError(
            "Chỉ bản Import_Localize.exe đã build trên Windows mới có thể tự cài cập nhật."
        )
    if not is_newer_version(release.version):
        raise UpdateError("Bản phát hành này không mới hơn phiên bản đang chạy.")

    _check_cancel(cancel_callback)
    UPDATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    staging_dir = UPDATE_CACHE_DIR / f"v{release.version}"
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True)
    archive = staging_dir / release.asset_name

    expected_checksum = _read_expected_checksum(
        release.checksum_url,
        cancel_callback,
    )
    _download_file(
        release.download_url,
        archive,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
        progress_start=5,
        progress_end=78,
    )
    _check_cancel(cancel_callback)
    if progress_callback:
        progress_callback(82, "Đang kiểm tra tính toàn vẹn của bản cập nhật...")
    actual_checksum = _sha256(archive, cancel_callback)
    if actual_checksum != expected_checksum:
        raise UpdateError(
            "Checksum SHA-256 không khớp. File cập nhật có thể bị hỏng hoặc bị thay đổi."
        )

    extracted = staging_dir / "extracted"
    if progress_callback:
        progress_callback(88, "Đang giải nén bản cập nhật...")
    _safe_extract(archive, extracted)
    payload_dir = _find_application_payload(extracted)
    script = _write_apply_script(
        staging_dir=staging_dir,
        payload_dir=payload_dir,
        target_dir=application_dir(),
        release=release,
    )
    if progress_callback:
        progress_callback(100, f"Bản v{release.version} đã sẵn sàng để cài đặt.")
    return PreparedUpdate(release=release, script_path=script, staging_dir=staging_dir)


def _update_log_tail(staging_dir: Path, *, max_chars: int = 2500) -> str:
    log_path = staging_dir / "update_apply.log"
    try:
        content = log_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    return content[-max_chars:].strip()


def launch_prepared_update(update: PreparedUpdate) -> None:
    """Launch the external updater and wait for its ready handshake."""
    if not update.script_path.is_file():
        raise UpdateError("Không tìm thấy kịch bản cài đặt bản cập nhật.")

    ready_path = update.staging_dir / "updater_ready.flag"
    result_path = update.staging_dir / "update_result.txt"
    ready_path.unlink(missing_ok=True)
    result_path.unlink(missing_ok=True)

    creation_flags = 0
    startupinfo = None
    if sys.platform.startswith("win"):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0

    try:
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(update.script_path),
            ],
            cwd=str(update.staging_dir),
            close_fds=True,
            creationflags=creation_flags,
            startupinfo=startupinfo,
        )
    except OSError as exc:
        raise UpdateError(f"Không thể khởi chạy trình cài cập nhật: {exc}") from exc

    deadline = time.monotonic() + 65.0
    while time.monotonic() < deadline:
        if ready_path.is_file():
            return
        exit_code = process.poll()
        if exit_code is not None:
            detail = _update_log_tail(update.staging_dir)
            suffix = f"\n\nChi tiết:\n{detail}" if detail else ""
            raise UpdateError(
                "Trình cài cập nhật đã dừng trước khi sẵn sàng "
                f"(mã {exit_code}).{suffix}"
            )
        time.sleep(0.15)

    try:
        process.terminate()
    except OSError:
        pass
    detail = _update_log_tail(update.staging_dir)
    suffix = f"\n\nChi tiết:\n{detail}" if detail else ""
    raise UpdateError(
        "Trình cài cập nhật không phản hồi. Hãy kiểm tra cửa sổ UAC hoặc quyền "
        f"ghi vào thư mục cài đặt.{suffix}"
    )

