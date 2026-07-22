from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

APP_NAME = "Import_Localize"
DISPLAY_NAME = "Import Localize"

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
ENTRY_SCRIPT = SRC_DIR / "main.py"
PACKAGE_DIR = SRC_DIR / "import_localize"
FORMS_DIR = PACKAGE_DIR / "ui" / "forms"
THEMES_DIR = SRC_DIR / "themes"
ASSETS_DIR = SRC_DIR / "assets"
CONSTANTS_FILE = PACKAGE_DIR / "app" / "constants.py"
MAIN_FORM = FORMS_DIR / "main_window.ui"

RELEASE_DIR = ROOT_DIR / "release"
PYINSTALLER_WORK_DIR = ROOT_DIR / ".pyinstaller"
BUILD_CONFIG_FILE = ROOT_DIR / ".build_config.json"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
GITHUB_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

RUNTIME_MODULES = {
    "PySide6": "PySide6",
    "gspread": "gspread",
    "google-auth": "google.auth",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "requests": "requests",
}
BUILD_MODULES = {"PyInstaller": "pyinstaller", "PIL": "pillow"}


class BuildError(RuntimeError):
    pass


def run(command: list[str], *, cwd: Path = ROOT_DIR) -> None:
    print("\n> " + subprocess.list2cmdline(command))
    subprocess.run(command, cwd=cwd, check=True)


def ensure_dependencies() -> None:
    missing_build = [
        package
        for module, package in BUILD_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    missing_runtime = [
        package
        for package, module in RUNTIME_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    missing = [*missing_build, *missing_runtime]
    if missing:
        print("Đang cài dependency build còn thiếu: " + ", ".join(missing))
        run([sys.executable, "-m", "pip", "install", "--upgrade", *missing])


def validate_project() -> None:
    required = [
        ENTRY_SCRIPT,
        PACKAGE_DIR,
        FORMS_DIR,
        THEMES_DIR,
        ASSETS_DIR,
        CONSTANTS_FILE,
        MAIN_FORM,
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        raise BuildError("Project thiếu:\n" + "\n".join(f"- {path}" for path in missing))

    for path in FORMS_DIR.glob("*.ui"):
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            raise BuildError(f"File UI lỗi XML: {path}\n{exc}") from exc


def normalize_version(raw: str) -> str:
    version = raw.strip().lstrip("vV")
    if not VERSION_PATTERN.fullmatch(version):
        raise BuildError("Phiên bản phải có dạng 1.4.0 hoặc 1.4.0-beta.1")
    return version


def validate_github_repository(raw: str) -> str:
    repository = (raw or "").strip()
    repository = repository.removeprefix("https://github.com/").strip("/")
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not GITHUB_REPOSITORY_PATTERN.fullmatch(repository):
        raise BuildError(
            "GitHub repository phải có dạng owner/repository, ví dụ longg/Import_Localize"
        )
    return repository


def update_default_repository(repository: str) -> None:
    original = CONSTANTS_FILE.read_text(encoding="utf-8")
    updated = re.sub(
        r'(?m)^(DEFAULT_GITHUB_REPOSITORY\s*=\s*)["\'][^"\']*["\']',
        rf'\g<1>"{repository}"',
        original,
    )
    CONSTANTS_FILE.write_text(updated, encoding="utf-8")
    if repository:
        print(f"Đã cấu hình nguồn cập nhật GitHub: {repository}")
    else:
        print("Bản build chưa gắn repository cập nhật mặc định.")


def update_version(version: str) -> None:
    original = CONSTANTS_FILE.read_text(encoding="utf-8")
    updated = re.sub(
        r'(?m)^(APP_VERSION\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{version}"',
        original,
    )
    CONSTANTS_FILE.write_text(updated, encoding="utf-8")

    ui = MAIN_FORM.read_text(encoding="utf-8")
    ui = re.sub(
        r'(<widget class="QLabel" name="versionLabel">[\s\S]*?<property name="text">\s*<string>)v?[^<]+(</string>)',
        rf"\g<1>v{version}\g<2>",
        ui,
        count=1,
    )
    MAIN_FORM.write_text(ui, encoding="utf-8")
    print(f"Đã cập nhật version thành v{version}")


def validate_oauth_client(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise BuildError(f"Không tìm thấy OAuth Client: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"OAuth Client JSON không hợp lệ: {exc}") from exc
    installed = payload.get("installed") if isinstance(payload, dict) else None
    if not isinstance(installed, dict):
        raise BuildError("OAuth Client phải là loại Desktop app (có khóa 'installed').")
    for field in ("client_id", "client_secret", "auth_uri", "token_uri"):
        if not installed.get(field):
            raise BuildError(f"OAuth Client thiếu trường installed.{field}")
    return path


def _load_build_config() -> dict:
    if not BUILD_CONFIG_FILE.is_file():
        return {}
    try:
        payload = json.loads(BUILD_CONFIG_FILE.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_build_config(**values: object) -> None:
    payload = _load_build_config()
    payload.update({key: value for key, value in values.items() if value not in (None, "")})
    BUILD_CONFIG_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def resolve_github_repository(explicit: str | None) -> str:
    candidates = [
        explicit or "",
        os.getenv("IMPORT_LOCALIZE_GITHUB_REPOSITORY", "").strip(),
        str(_load_build_config().get("github_repository") or ""),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        repository = validate_github_repository(candidate)
        _save_build_config(github_repository=repository)
        return repository
    return ""


def resolve_oauth_client(
    explicit: Path | None,
    *,
    allow_missing: bool,
) -> Path | None:
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)

    env_path = os.getenv("IMPORT_LOCALIZE_OAUTH_CLIENT", "").strip()
    if env_path:
        candidates.append(Path(env_path))

    configured = _load_build_config().get("oauth_client_path")
    if configured:
        candidates.append(Path(str(configured)))

    # oauth_client.json is gitignored, so it may safely exist only on the build machine.
    candidates.append(ROOT_DIR / "oauth_client.json")

    for candidate in candidates:
        try:
            validated = validate_oauth_client(candidate)
            _save_build_config(oauth_client_path=str(validated))
            return validated
        except BuildError:
            continue

    if not allow_missing and sys.stdin.isatty():
        raw = input(
            "Nhập đường dẫn oauth_client.json loại Desktop app "
            "(chỉ cần nhập một lần trên máy build): "
        ).strip().strip('"')
        if raw:
            validated = validate_oauth_client(Path(raw))
            _save_build_config(oauth_client_path=str(validated))
            return validated

    if allow_missing:
        return None

    raise BuildError(
        "Chưa có oauth_client.json để đóng gói. Dùng --oauth-client <đường_dẫn>, "
        "đặt biến IMPORT_LOCALIZE_OAUTH_CLIENT, hoặc đặt file oauth_client.json "
        "cạnh build_app.py. Máy cài sẽ không phải chọn lại file này."
    )


def generate_icon() -> Path:
    from PIL import Image

    source = ASSETS_DIR / "images" / "import_localize_logo.png"
    output = ROOT_DIR / ".build_resources" / "import_localize.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise BuildError(f"Thiếu logo PNG: {source}")
    image = Image.open(source).convert("RGBA")
    image.save(
        output,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)],
    )
    return output


def compile_source() -> None:
    run([sys.executable, "-m", "compileall", "-q", str(SRC_DIR)])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_docs(
    output_dir: Path,
    oauth_bundled: bool,
    github_repository: str,
) -> None:
    oauth_note = (
        "OAuth Client đã được đóng gói. Không cần chọn lại file OAuth trên máy cài."
        if oauth_bundled
        else "Bản build này không có OAuth Client; cần cấu hình trong Cài đặt."
    )
    repository_note = (
        github_repository
        if github_repository
        else "chưa cấu hình; nhập owner/repository trong Cài đặt"
    )
    text = f"""
    {DISPLAY_NAME}
    ===============

    CÁCH DÙNG TRÊN MÁY KHÁC
    1. Giải nén toàn bộ thư mục, không chỉ chép riêng file EXE.
    2. Chạy {APP_NAME}.exe. Máy sử dụng KHÔNG cần cài Python.
    3. {oauth_note}
    4. Lần đầu trên mỗi máy, nhấn Cài đặt → Đăng nhập Google và cấp quyền một lần.
    5. Dán link Google Sheet, chọn CSV rồi Import.

    Token Google được tạo riêng trên từng máy tại:
      %APPDATA%\\Import Localize\\google_oauth_token.json

    CẬP NHẬT ỨNG DỤNG
    - Mở Cài đặt → Cập nhật → Kiểm tra cập nhật.
    - Repository mặc định: {repository_note}
    - Ứng dụng tải ZIP và checksum từ GitHub Releases, kiểm tra SHA-256,
      sau đó tự khởi động lại để thay thế bản cũ.
    - Cấu hình và token trong AppData không bị xóa khi cập nhật.

    Không đóng gói hoặc sao chép token giữa các máy.
    """
    (output_dir / "README_FIRST_RUN.txt").write_text(
        textwrap.dedent(text).strip() + "\n",
        encoding="utf-8",
    )


def build(
    version: str,
    *,
    oauth_client: Path | None,
    no_bundle_oauth: bool,
    github_repository: str | None,
) -> Path:
    ensure_dependencies()
    validate_project()
    repository = resolve_github_repository(github_repository)
    update_version(version)
    update_default_repository(repository)
    compile_source()
    icon = generate_icon()

    oauth_path = resolve_oauth_client(
        oauth_client,
        allow_missing=no_bundle_oauth,
    )

    release_version_dir = RELEASE_DIR / f"v{version}"
    final_app_dir = release_version_dir / APP_NAME
    if release_version_dir.exists():
        shutil.rmtree(release_version_dir)
    release_version_dir.mkdir(parents=True, exist_ok=True)

    work_dir = PYINSTALLER_WORK_DIR / "work"
    dist_dir = PYINSTALLER_WORK_DIR / "dist"
    spec_dir = PYINSTALLER_WORK_DIR / "spec"
    shutil.rmtree(PYINSTALLER_WORK_DIR, ignore_errors=True)
    work_dir.mkdir(parents=True)
    dist_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)

    sep = ";" if sys.platform.startswith("win") else ":"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(icon),
        "--workpath",
        str(work_dir),
        "--distpath",
        str(dist_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(SRC_DIR),
        "--add-data",
        f"{FORMS_DIR}{sep}import_localize/ui/forms",
        "--add-data",
        f"{THEMES_DIR}{sep}themes",
        "--add-data",
        f"{ASSETS_DIR}{sep}assets",
        "--collect-submodules",
        "gspread",
        "--collect-submodules",
        "google_auth_oauthlib",
        "--collect-submodules",
        "google.auth",
        "--collect-data",
        "certifi",
        "--hidden-import",
        "google.auth.transport.requests",
        "--hidden-import",
        "google.oauth2.credentials",
        "--hidden-import",
        "google_auth_oauthlib.flow",
        "--hidden-import",
        "PySide6.QtUiTools",
        "--hidden-import",
        "PySide6.QtSvg",
        "--hidden-import",
        "PySide6.QtSvgWidgets",
        "--exclude-module",
        "tkinter",
        str(ENTRY_SCRIPT),
    ]
    run(command)

    built = dist_dir / APP_NAME
    if not built.is_dir():
        raise BuildError(f"PyInstaller không tạo thư mục: {built}")
    shutil.copytree(built, final_app_dir)

    oauth_bundled = False
    if oauth_path:
        shutil.copy2(oauth_path, final_app_dir / "oauth_client.json")
        oauth_bundled = True
        print("Đã đóng gói OAuth Client; máy cài không cần chọn lại file JSON.")

    write_release_docs(final_app_dir, oauth_bundled, repository)
    manifest = {
        "app": DISPLAY_NAME,
        "version": version,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_build_version": sys.version,
        "target_requires_python": False,
        "oauth_client_bundled": oauth_bundled,
        "oauth_token_bundled": False,
        "distribution_type": "PyInstaller onedir",
        "github_update_repository": repository,
        "automatic_updates": bool(repository),
    }
    (final_app_dir / "build_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    archive_base = release_version_dir / f"{APP_NAME}_v{version}"
    archive = Path(shutil.make_archive(str(archive_base), "zip", final_app_dir))
    checksum = sha256(archive)
    (release_version_dir / f"{archive.name}.sha256.txt").write_text(
        f"{checksum}  {archive.name}\n",
        encoding="utf-8",
    )
    shutil.rmtree(PYINSTALLER_WORK_DIR, ignore_errors=True)
    print(
        f"\nBuild hoàn tất. Máy nhận bản build không cần Python:\n"
        f"- Thư mục: {final_app_dir}\n"
        f"- ZIP: {archive}\n"
        f"- SHA-256: {checksum}"
    )
    return archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build Import Localize bằng PyInstaller. Mặc định bắt buộc đóng gói "
            "OAuth Client để máy cài không phải chọn lại file JSON."
        )
    )
    parser.add_argument("--version", help="Phiên bản, ví dụ 1.5.0")
    parser.add_argument(
        "--oauth-client",
        type=Path,
        help="Đường dẫn OAuth Desktop Client JSON trên máy build",
    )
    parser.add_argument(
        "--no-bundle-oauth",
        action="store_true",
        help="Không đóng gói OAuth Client (máy cài phải tự cấu hình)",
    )
    parser.add_argument(
        "--github-repo",
        help=(
            "Repository GitHub dùng cho tự cập nhật, dạng owner/repository. "
            "Giá trị được nhớ trong .build_config.json."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        version = normalize_version(args.version or input("Nhập phiên bản build: "))
        build(
            version,
            oauth_client=args.oauth_client,
            no_bundle_oauth=args.no_bundle_oauth,
            github_repository=args.github_repo,
        )
        return 0
    except (
        BuildError,
        subprocess.CalledProcessError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(f"\nBUILD FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
