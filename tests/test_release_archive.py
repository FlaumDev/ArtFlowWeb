from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.create_release_archive import (
    create_release_archive,
    is_forbidden_archive_path,
    main,
    validate_release_archive,
)


def write_file(project_root: Path, relative_path: str, content: str = "data"):
    path = project_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_release_archive_filters_sensitive_and_generated_files(tmp_path):
    project_root = tmp_path / "project"
    included = {
        ".env.example",
        "app/main.py",
        "static/images/logo.png",
    }
    excluded = {
        ".env",
        ".env.production",
        ".git/config",
        ".idea/workspace.xml",
        ".venv/pyvenv.cfg",
        ".vscode/settings.json",
        "__pycache__/module.cpython-312.pyc",
        ".pytest_cache/state",
        ".coverage",
        "app/server.log",
        "tests/screenshots/failure.png",
        "tests/home-screenshot.webp",
        "tmp/output.tmp",
    }
    for relative_path in included | excluded:
        write_file(project_root, relative_path)

    output = project_root / "dist" / "ArtFlowWeb-release.zip"
    archive_path = create_release_archive(project_root, output)

    with ZipFile(archive_path) as archive:
        members = set(archive.namelist())

    assert included <= members
    assert members.isdisjoint(excluded)
    assert "dist/ArtFlowWeb-release.zip" not in members


def test_release_archive_validation_rejects_forbidden_member(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive_path = tmp_path / "unsafe.zip"
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(".env.example", "APP_ENV=development")
        archive.writestr(".env.production", "SECRET=value")

    with pytest.raises(RuntimeError, match="forbidden paths"):
        validate_release_archive(archive_path, project_root)


def test_git_worktree_pointer_file_is_forbidden():
    assert is_forbidden_archive_path(PurePosixPath(".git"))


def test_release_archive_cli_prints_path_and_size(tmp_path, capsys):
    output = tmp_path / "ArtFlowWeb-release.zip"

    assert main(["--output", str(output)]) == 0

    printed = capsys.readouterr().out
    assert f"Release archive: {output.resolve()}" in printed
    assert "Size:" in printed
    assert output.stat().st_size > 0
