from __future__ import annotations

import ipaddress
import re
import sys
from urllib.parse import urlsplit

from app.config import Settings


_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _is_valid_public_host(host: str) -> bool:
    normalized = host.strip().casefold().rstrip(".")
    if not normalized or "*" in normalized or ":" in normalized:
        return False
    if normalized == "localhost":
        return False

    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        labels = normalized.split(".")
        return len(labels) >= 2 and all(_DNS_LABEL.fullmatch(label) for label in labels)
    return not (
        address.is_loopback
        or address.is_private
        or address.is_unspecified
    )


def validate_production_settings(app_settings: Settings) -> list[str]:
    errors: list[str] = []
    if not app_settings.is_production:
        errors.append("APP_ENV must be production")
    if app_settings.enable_docs:
        errors.append("ENABLE_DOCS must be false")
    if not app_settings.enable_security_headers:
        errors.append("ENABLE_SECURITY_HEADERS must be true")

    public_base_url = app_settings.public_https_base_url
    if public_base_url is None:
        errors.append("BASE_URL must be a valid public HTTPS origin")

    allowed_hosts = tuple(
        host.strip().casefold().rstrip(".")
        for host in app_settings.allowed_hosts
        if host.strip()
    )
    if not allowed_hosts:
        errors.append("ALLOWED_HOSTS must contain production hostnames")
    elif any(not _is_valid_public_host(host) for host in allowed_hosts):
        errors.append("ALLOWED_HOSTS contains an invalid or non-public hostname")

    if public_base_url is not None:
        base_hostname = (urlsplit(public_base_url).hostname or "").casefold()
        if base_hostname not in allowed_hosts:
            errors.append("ALLOWED_HOSTS must include the BASE_URL hostname")
    return errors


def main() -> int:
    try:
        app_settings = Settings.from_env()
    except ValueError as exc:
        print(f"Production settings are invalid: {exc}", file=sys.stderr)
        return 1

    errors = validate_production_settings(app_settings)
    if errors:
        for error in errors:
            print(f"Production settings are invalid: {error}", file=sys.stderr)
        return 1

    print("Production settings validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
