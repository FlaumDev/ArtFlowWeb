from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "compose.integration.yml"
TEST_DATABASE_URL = (
    "postgresql://artflow_test:integration-only-password@"
    "127.0.0.1:55432/artflow_test"
)


@pytest.fixture(scope="session")
def integration_database_url(pytestconfig) -> Iterator[str]:
    if "integration" not in pytestconfig.option.markexpr:
        pytest.skip("Run explicitly with: python -m pytest -m integration")

    external_database_url = os.getenv("ARTFLOW_INTEGRATION_DATABASE_URL")
    if external_database_url:
        yield external_database_url
        return

    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker CLI is unavailable; integration PostgreSQL not started")

    try:
        info = subprocess.run(
            [docker, "info"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"Docker is unavailable: {type(exc).__name__}")

    if info.returncode != 0:
        pytest.skip("Docker daemon is unavailable; integration PostgreSQL not started")

    compose = [docker, "compose", "-f", str(COMPOSE_FILE)]
    started = subprocess.run(
        [*compose, "up", "-d", "--wait"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if started.returncode != 0:
        pytest.skip(
            "Integration PostgreSQL could not start; inspect Docker Compose output"
        )

    try:
        yield TEST_DATABASE_URL
    finally:
        subprocess.run(
            [*compose, "down", "--volumes", "--remove-orphans"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


@pytest.fixture(scope="session", autouse=True)
def require_integration_database(integration_database_url) -> None:
    return None
