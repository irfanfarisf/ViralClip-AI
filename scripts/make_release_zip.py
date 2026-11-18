"""Create a clean, reproducible release zip of ViralClip AI.

Excludes virtual environments, node_modules, secrets, caches, and runtime data.
Includes source code, documentation, frontend assets, package manifests, and startup scripts.
"""
from __future__ import annotations

import datetime
import os
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "frontend/node_modules",
    "frontend/dist",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "releases",
    "tools",
    "storage/temp",
    "storage/output",
    "storage/db",
    "storage/e2e",
}

EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".DS_Store",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".tar.gz",
}

EXCLUDE_FILES = {
    ".env",
    ".env.local",
    "Thumbs.db",
}


def should_include(rel_path: Path) -> bool:
    posix_path = rel_path.as_posix()
    for excl_dir in EXCLUDE_DIRS:
        if posix_path == excl_dir or posix_path.startswith(f"{excl_dir}/"):
            return False
    if rel_path.name in EXCLUDE_FILES:
        return False
    if rel_path.suffix in EXCLUDE_EXTS:
        return False
    return True


def create_release_zip(output_zip: Path | None = None) -> Path:
    releases_dir = PROJECT_ROOT / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)

    if output_zip is None:
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_zip = releases_dir / f"viralclip-ai-release-{timestamp}.zip"

    files_packed = 0
    total_bytes = 0

    print(f"Creating release archive: {output_zip}")
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if should_include((root_path / d).relative_to(PROJECT_ROOT))]

            for f in files:
                full_path = root_path / f
                rel_path = full_path.relative_to(PROJECT_ROOT)
                if should_include(rel_path):
                    zf.write(full_path, arcname=rel_path.as_posix())
                    files_packed += 1
                    total_bytes += full_path.stat().st_size

        for keep in ("storage/temp/.gitkeep", "storage/output/.gitkeep", "storage/db/.gitkeep"):
            if keep not in zf.namelist():
                zf.writestr(keep, "")

    zip_size_mb = output_zip.stat().st_size / (1024 * 1024)
    print(f"Done! Packed {files_packed} files ({total_bytes / (1024 * 1024):.2f} MB raw, {zip_size_mb:.2f} MB compressed)")
    print(f"Archive saved to: {output_zip}")
    return output_zip


if __name__ == "__main__":
    out_target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    create_release_zip(out_target)
