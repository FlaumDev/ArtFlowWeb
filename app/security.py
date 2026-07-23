from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import Message, Receive, Scope, Send


SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
        "style-src 'self'; font-src 'self'; connect-src 'self'; "
        "img-src 'self' https:;"
    ),
    "permissions-policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}

DOCS_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'none'; form-action 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "font-src 'self' https://cdn.jsdelivr.net; connect-src 'self'; "
    "img-src 'self' https: data:;"
)


class SecurityHeadersMiddleware:
    def __init__(
        self,
        app,
        *,
        enable_hsts: bool = False,
        csp_overrides: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self.enable_hsts = enable_hsts
        self.csp_overrides = csp_overrides or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["x-content-type-options"] = "nosniff"
                content_type = (
                    headers.get("content-type", "")
                    .partition(";")[0]
                    .strip()
                    .casefold()
                )
                if (
                    content_type == "text/html"
                    or content_type == "application/json"
                    or content_type.endswith("+json")
                ):
                    for name, value in SECURITY_HEADERS.items():
                        if name == "x-content-type-options":
                            continue
                        if name == "content-security-policy":
                            value = self.csp_overrides.get(
                                scope["path"],
                                value,
                            )
                        headers[name] = value
                if self.enable_hsts:
                    headers["strict-transport-security"] = "max-age=31536000"
            await send(message)

        await self.app(scope, receive, send_with_headers)
