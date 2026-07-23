from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PLAYWRIGHT_AVAILABLE = all(
    importlib.util.find_spec(package) is not None
    for package in ("playwright", "pytest_playwright")
)


def pytest_collection_modifyitems(items):
    if PLAYWRIGHT_AVAILABLE:
        return

    marker = pytest.mark.skip(
        reason=(
            "Playwright is not installed; run "
            "`python -m pip install -r requirements-e2e.txt`"
        )
    )
    for item in items:
        if item.get_closest_marker("e2e"):
            item.add_marker(marker)


def _available_port() -> int:
    with socket.socket() as server_socket:
        server_socket.bind(("127.0.0.1", 0))
        return int(server_socket.getsockname()[1])


@pytest.fixture(scope="session")
def e2e_base_url():
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip("Playwright dependencies are unavailable")

    port = _available_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "BASE_URL": base_url,
            "ALLOWED_HOSTS": "127.0.0.1,localhost",
            "BOT_USERNAME": "ArtFlowBot",
            "DATABASE_URL": "",
            "DB_HOST": "",
            "DB_NAME": "",
            "DB_USER": "",
            "DB_PASSWORD": "",
            "PYTHONUTF8": "1",
        }
    )
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (str(PROJECT_ROOT), environment.get("PYTHONPATH", "")),
        )
    )

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.e2e.mock_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        creationflags=creation_flags,
    )

    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail(
                    "E2E application exited before becoming ready "
                    f"with code {process.returncode}"
                )
            try:
                with urlopen(f"{base_url}/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(0.1)
        else:
            pytest.fail("E2E application did not become ready within 15 seconds")

        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
