"""The upstream client, over a real socket, against a real TLS server.

Every other test stubs the network out, which is right for parsers and wrong
for the one layer a change of HTTP client changes underneath them: the TLS
handshake, HTTP/2 by ALPN, redirects, gzip, and the exception a refusal
arrives as -- the one `routing.py` catches to decide that another route may
work. CI cannot reach Yandex and should not try. It can reach a server on this
machine, so these ask the app's own `http.client()` each of those questions
against one, with nothing replaced but the certificate authority.

The server is Hypercorn, because it speaks HTTP/2; the authority is trustme,
minted per run. Both are test-only (`requirements-dev.txt`).
"""

from __future__ import annotations

import asyncio
import gzip
import socket
import ssl
import threading
import time

import pytest

trustme = pytest.importorskip("trustme")
hypercorn_asyncio = pytest.importorskip("hypercorn.asyncio")
hypercorn_config = pytest.importorskip("hypercorn.config")

import httpx  # noqa: E402

from app import http, routing  # noqa: E402

PAGE = "Погода в Йошкар-Оле\n" * 200    # big enough for gzip to matter


async def upstream(scope, receive, send):
    """A stand-in for the three sources: enough routes to ask each question."""
    if scope["type"] == "lifespan":
        while (msg := await receive())["type"] != "lifespan.shutdown":
            await send({"type": msg["type"] + ".complete"})
        await send({"type": "lifespan.shutdown.complete"})
        return
    path, headers, body = scope["path"], [], b""
    status = 200
    if path == "/moved":
        status, headers = 302, [(b"location", b"/page")]
    elif path == "/refused":
        status, body = 403, b"go away"
    elif path == "/gzip":
        headers, body = [(b"content-encoding", b"gzip")], gzip.compress(PAGE.encode())
    elif path == "/page":
        body = PAGE.encode()
    else:
        status = 404
    headers.append((b"x-http-version", scope["http_version"].encode()))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


@pytest.fixture(scope="module")
def authority():
    return trustme.CA()


@pytest.fixture(scope="module")
def origin(authority, tmp_path_factory):
    """`https://127.0.0.1:<port>`, serving HTTP/2 and HTTP/1.1 by ALPN. An
    address rather than `localhost`, which may resolve to ::1 first."""
    cert = authority.issue_cert("127.0.0.1")
    pem = tmp_path_factory.mktemp("tls") / "server.pem"
    cert.private_key_and_cert_chain_pem.write_to_path(str(pem))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = hypercorn_config.Config()
    config.bind = [f"127.0.0.1:{port}"]
    config.certfile = config.keyfile = str(pem)
    config.accesslog = config.errorlog = None
    running: dict = {}

    async def serve():
        running["loop"], running["stop"] = asyncio.get_running_loop(), asyncio.Event()
        await hypercorn_asyncio.serve(upstream, config,
                                      shutdown_trigger=running["stop"].wait)

    # A thread of its own, with its own loop, so that each test can drive the
    # client with a plain `asyncio.run` -- and `asyncio.run` closes the loop.
    thread = threading.Thread(target=asyncio.run, args=(serve(),), daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        pytest.fail("the local TLS server did not start")
    yield f"https://127.0.0.1:{port}"
    running["loop"].call_soon_threadsafe(running["stop"].set)
    thread.join(timeout=10)


@pytest.fixture
def trusting(authority, monkeypatch):
    """The app's client, trusting the test authority instead of the world's.

    Only the trust anchors change. Everything else -- the context's settings,
    `trust_env=False`, redirects, the timeout, HTTP/2 -- is what production
    builds, from the same function."""
    ctx = ssl.create_default_context()
    authority.configure_trust(ctx)
    monkeypatch.setattr(http, "_TLS", ctx)


def fetch(url: str, **kw):
    async def go():
        async with http.client(**kw) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r
    return asyncio.run(go())


def refusal(url: str, **kw) -> Exception:
    try:
        fetch(url, **kw)
    except Exception as e:
        return e
    raise AssertionError(f"{url} was fetched; it should have been refused")


@pytest.mark.usefixtures("trusting")
class TestTheClientSpeaksToARealServer:
    def test_http2_is_negotiated_over_tls(self, origin):
        r = fetch(f"{origin}/page")
        assert r.http_version == "HTTP/2"
        assert r.headers["x-http-version"] == "2"
        assert r.text == PAGE

    def test_http1_when_a_route_asks_for_it(self, origin):
        """Gismeteo's routes ask for HTTP/1.1 (`GISMETEO_HTTP2`, off)."""
        r = fetch(f"{origin}/page", http2=False)
        assert r.http_version == "HTTP/1.1"

    def test_a_redirect_is_followed_to_the_page(self, origin):
        r = fetch(f"{origin}/moved")
        assert str(r.url) == f"{origin}/page"
        assert r.text == PAGE

    def test_gzip_is_decoded_into_the_text_the_parsers_read(self, origin):
        r = fetch(f"{origin}/gzip")
        assert r.text == PAGE

    def test_a_403_is_an_http_error_with_its_status(self, origin):
        """What `routing.py` catches as a refusal, and how it reports it."""
        e = refusal(f"{origin}/refused")
        assert isinstance(e, httpx.HTTPError)
        assert routing._brief(e) == "HTTP 403"

    def test_a_closed_port_is_an_http_error_too(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        e = refusal(f"https://127.0.0.1:{port}/page")
        assert isinstance(e, httpx.HTTPError), type(e)


class TestTheTrustIsReal:
    def test_a_certificate_nobody_vouches_for_is_refused(self, origin):
        """The production context, unpatched: the test authority is in no
        trust store, so the handshake must fail -- as a refusal `routing.py`
        catches, not as something that escapes it."""
        e = refusal(f"{origin}/page")
        assert isinstance(e, httpx.HTTPError), type(e)
        assert "CERTIFICATE_VERIFY_FAILED" in str(e)

    def test_the_trust_store_is_loaded_once_and_is_not_empty(self):
        """Built at import, from the CA bundle in the lock: a context with no
        anchors would refuse every upstream, and an import-time load is what
        keeps each new connection from re-reading the bundle."""
        assert http._TLS.verify_mode == ssl.CERT_REQUIRED
        assert http._TLS.check_hostname
        assert http._TLS.cert_store_stats()["x509_ca"] > 100
