from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from urllib.parse import parse_qs

from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send


VERSIONED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"
STATIC_ASSET_CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=604800"
_VERSIONED_SUFFIXES = {".css", ".js"}
_ALREADY_COMPRESSED_SUFFIXES = {
    ".avif",
    ".br",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mp4",
    ".pdf",
    ".png",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
}

mimetypes.add_type("image/webp", ".webp")


class CompressibleGZipMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = 1000,
        compresslevel: int = 5,
    ) -> None:
        self.app = app
        self.gzip_app = GZipMiddleware(
            app,
            minimum_size=minimum_size,
            compresslevel=compresslevel,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        suffix = PurePosixPath(scope.get("path", "")).suffix.casefold()
        if scope["type"] != "http" or suffix in _ALREADY_COMPRESSED_SUFFIXES:
            await self.app(scope, receive, send)
            return
        await self.gzip_app(scope, receive, send)


class CacheControlledStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code not in {200, 304}:
            return response

        suffix = PurePosixPath(path).suffix.casefold()
        query = parse_qs(
            scope.get("query_string", b"").decode("ascii", errors="ignore"),
            keep_blank_values=False,
        )
        if suffix in _VERSIONED_SUFFIXES and query.get("v"):
            cache_control = VERSIONED_ASSET_CACHE_CONTROL
        else:
            cache_control = STATIC_ASSET_CACHE_CONTROL
        response.headers.setdefault("cache-control", cache_control)
        return response
