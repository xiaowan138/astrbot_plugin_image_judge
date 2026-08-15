"""One-shot zip packager for the AstrBot plugin.

Usage: python build.py
Output: dist/<plugin_name>-<version>.zip
The zip top-level folder is the plugin name, so AstrBot's web UI can
install it directly. Tests, git files and the build script itself are
excluded.
"""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

INCLUDE_EXTENSIONS = {".py", ".yaml", ".json", ".html", ".md", ".txt", ".png"}
EXCLUDE_ROOT = {"tests", "build.py", "dist"}


def plugin_name() -> str:
    meta = ROOT / "metadata.yaml"
    match = re.search(r"^name:\s*(\S+)", meta.read_text(encoding="utf-8"), re.M)
    if not match:
        sys.exit("metadata.yaml 中缺少 name 字段")
    return match.group(1)


def plugin_version() -> str:
    meta = ROOT / "metadata.yaml"
    match = re.search(r"^version:\s*(\S+)", meta.read_text(encoding="utf-8"), re.M)
    if not match:
        sys.exit("metadata.yaml 中缺少 version 字段")
    return match.group(1).lstrip("v")


def should_include(path: Path, root_relative: str) -> bool:
    # 顶层目录/文件白名单排除。
    top_level = root_relative.split("/", 1)[0]
    if top_level in EXCLUDE_ROOT:
        return False
    # 隐藏文件/目录（.git、.zcode、__pycache__ 等）一律不进发布包。
    if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
        return False
    return path.suffix.lower() in INCLUDE_EXTENSIONS


def collect_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if should_include(path, relative):
            files.append(path)
    return files


def main() -> None:
    name = plugin_name()
    version = plugin_version()
    DIST.mkdir(exist_ok=True)
    archive = DIST / f"{name}-v{version}.zip"

    files = collect_files()
    if not files:
        sys.exit("没有找到需要打包的文件")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arcname = f"{name}/{path.relative_to(ROOT).as_posix()}"
            zf.write(path, arcname)
    print(f"已打包 {len(files)} 个文件 -> {archive}")

    # Clean up any leftover staged copies from previous runs.
    staged = ROOT / name
    if staged.is_dir():
        shutil.rmtree(staged, ignore_errors=True)


if __name__ == "__main__":
    main()
