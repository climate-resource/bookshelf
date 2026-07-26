"""One socket-level smoke for the shipped synchronous httpx transport."""

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bookshelf._core.client import BookshelfClient


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        assert self.path == "/v1/resources?limit=1"
        payload = b'{"items":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def live_api_url() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, name="sdk-http-smoke", daemon=True)
    thread.start()

    host, port = server.server_address
    yield f"http://{host}:{port}"

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    assert not thread.is_alive(), "ephemeral HTTP server did not stop"


def test_sync_transport_reaches_an_ephemeral_http_socket(live_api_url: str) -> None:
    with BookshelfClient(live_api_url, auth=None) as client:
        response = client.list_resources(limit=1)

    assert response.items == []
