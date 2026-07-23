from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.config import settings
from scripts.check_production_settings import validate_production_settings
from scripts.verify_production import (
    HttpResponse,
    VerificationError,
    _deep_link_ids,
    audit_html,
    security_header_errors,
    validate_public_base_url,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def production_settings(**overrides):
    values = {
        "app_env": "production",
        "base_url": "https://artflow.example.test",
        "allowed_hosts": (
            "artflow.example.test",
            "artflow-production.up.railway.app",
        ),
        "enable_docs": False,
        "enable_security_headers": True,
    }
    values.update(overrides)
    return replace(settings, **values)


def test_valid_production_settings_pass_operational_check():
    assert validate_production_settings(production_settings()) == []


def test_production_settings_fail_closed_without_safe_hosts_and_headers():
    errors = validate_production_settings(
        production_settings(
            allowed_hosts=("*", "localhost"),
            enable_docs=True,
            enable_security_headers=False,
        )
    )
    rendered = " ".join(errors)
    assert "ALLOWED_HOSTS" in rendered
    assert "ENABLE_DOCS" in rendered
    assert "ENABLE_SECURITY_HEADERS" in rendered


@pytest.mark.parametrize(
    "invalid_base_url",
    [
        "http://artflow.example.test",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://user:password@artflow.example.test",
        "https://artflow.example.test:8443",
        "https://artflow.example.test/path",
        "https://artflow.example.test\n.evil.test",
    ],
)
def test_production_verifier_rejects_non_public_origins(invalid_base_url):
    with pytest.raises(VerificationError):
        validate_public_base_url(invalid_base_url)


def test_html_audit_accepts_isolated_https_external_links():
    html = """
        <a href="https://t.me/ArtFlowBot?start=competition_7"
           target="_blank" rel="noopener noreferrer">Подать заявку</a>
        <img src="https://cdn.example.test/poster?id=7"
             referrerpolicy="no-referrer" alt="Афиша">
        <a href="mailto:team@example.test">Email</a>
    """
    assert audit_html(html, base_hostname="artflow.example.test") == []
    assert _deep_link_ids(html) == {7}


def test_html_audit_rejects_unsafe_links_without_fetching_them():
    html = """
        <a href="javascript:alert(1)">Unsafe</a>
        <a href="https://user:password@example.test/file">Credentials</a>
        <a href="http://example.test/file" target="_blank">HTTP</a>
        <a href="https://login.instagram.evil.test/artflow">Instagram</a>
        <a href="//evil.example.test/path">Protocol relative</a>
        <img src="https://cdn.example.test/poster">
    """
    errors = " ".join(
        audit_html(html, base_hostname="artflow.example.test")
    )
    assert "Forbidden URL scheme" in errors
    assert "user information" in errors
    assert "not HTTPS" in errors
    assert "noopener noreferrer" in errors
    assert "unexpected host" in errors
    assert "Protocol-relative" in errors
    assert "referrerpolicy" in errors


def test_production_header_audit_requires_strict_public_policy():
    response = HttpResponse(
        status=200,
        headers={
            "x-content-type-options": "nosniff",
            "content-security-policy": "default-src 'self'; script-src 'self'",
            "referrer-policy": "no-referrer",
            "x-frame-options": "DENY",
            "permissions-policy": "camera=()",
            "strict-transport-security": "max-age=31536000",
        },
        body=b"{}",
    )
    assert security_header_errors(response) == []


def test_ci_covers_required_security_checks_and_is_not_a_deploy_workflow():
    workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    for command in (
        "python -m compileall app scripts",
        "python -m pytest -q",
        "python -m bandit -r app scripts",
        "python -m pip check",
        "python -m pip_audit -r requirements.lock",
        "python -m scripts.check_production_settings",
        "python -m pytest -m integration",
        "python -m pytest -m e2e",
        "gitleaks",
    ):
        assert command in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "deploy" not in workflow.casefold()


def test_gitleaks_allowlist_is_limited_to_named_test_credentials():
    config = (PROJECT_ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    assert "useDefault = true" in config
    assert "paths =" not in config
    assert "integration-only-password" in config
