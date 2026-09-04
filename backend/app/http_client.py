"""A shared httpx client factory. Every `httpx.AsyncClient()` construction
in the codebase goes through `new_http_client()` instead of calling
`httpx.AsyncClient()` directly.

Why: httpx builds a fresh `ssl.SSLContext` per client by default, and
`SSLContext.load_verify_locations()` (loading the CA bundle) measured
~400ms on this platform — reasonable once, ruinous if paid on every batch
submission or every connector's `expand()` call. Building the context once
and reusing it changes nothing about verification behaviour, just when the
cost is paid.
"""

from __future__ import annotations

import ssl
from functools import lru_cache

import httpx


@lru_cache(maxsize=1)
def shared_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def new_http_client(**kwargs: object) -> httpx.AsyncClient:
    kwargs.setdefault("verify", shared_ssl_context())
    return httpx.AsyncClient(**kwargs)
