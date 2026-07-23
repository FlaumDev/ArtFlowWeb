from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "ArtFlowWeb-release.zip"

_EXCLUDED_DIRECTORIES = {
    ".agents",
    ".codex",
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "playwright-report",
    "screenshots",
    "test-results",
    "test_screenshots",
    "tmp",
    "temp",
    "venv",
}
_EXCLUDED_SUFFIXES = {".bak", ".log", ".pyc", ".pyo", ".swp", ".temp", ".tmp"}
_SCREENSHOT_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


def is_forbidden_archive_path(relative_path: PurePosixPath) -> bool:
    parts = relative_path.parts
    if not parts:
        return True
    if any(part in _EXCLUDED_DIRECTORIES for part in parts):
        return True

    name = relative_path.name
    lower_name = name.casefold()
    if lower_name == ".env.example":
        return False
    if lower_name == ".env" or lower_name.startswith(".env."):
        return True
    if lower_name in {".coverage", ".ds_store", "thumbs.db"}:
        return True
    if lower_name.endswith("~") or relative_path.suffix.casefold() in _EXCLUDED_SUFFIXES:
        return True
    return (
        "screenshot" in lower_name
        and relative_path.suffix.casefold() in _SCREENSHOT_SUFFIXES
    )


def iter_release_files(
    project_root: Path,
    output_path: Path,
) -> Iterable[tuple[Path, PurePosixPath]]:
    resolved_output = output_path.resolve()
    for path in sorted(project_root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.resolve() == resolved_output:
            continue
        relative_path = PurePosixPath(path.relative_to(project_root).as_posix())
        if not is_forbidden_archive_path(relative_path):
            yield path, relative_path


def validate_release_archive(archive_path: Path, project_root: Path) -> None:
    try:
        output_member = PurePosixPath(
            archive_path.resolve().relative_to(project_root.resolve()).as_posix()
        )
    except ValueError:
        output_member = None

    with ZipFile(archive_path) as archive:
        members = [PurePosixPath(name) for name in archive.namelist()]

    forbidden = [
        str(member)
        for member in members
        if is_forbidden_archive_path(member) or member == output_member
    ]
    if forbidden:
        joined = ", ".join(forbidden)
        raise RuntimeError(f"Release archive contains forbidden paths: {joined}")
    if PurePosixPath(".env.example") not in members:
        raise RuntimeError("Release archive must contain .env.example")


def create_release_archive(
    project_root: Path = PROJECT_ROOT,
    output_path: Path = DEFAULT_OUTPUT,
) -> Path:
    root = project_root.resolve()
    output = output_path.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(
        output,
        mode="w",
        compression=ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source_path, relative_path in iter_release_files(root, output):
            archive.write(source_path, arcname=relative_path.as_posix())

    validate_release_archive(output, root)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a validated ArtFlowWeb release ZIP.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output ZIP path (default: dist/ArtFlowWeb-release.zip).",
    )
    args = parser.parse_args(argv)

    archive_path = create_release_archive(output_path=args.output)
    size_bytes = archive_path.stat().st_size
    print(f"Release archive: {archive_path}")
    print(f"Size: {size_bytes} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
