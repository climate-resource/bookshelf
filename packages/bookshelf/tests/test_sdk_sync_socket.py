"""One socket-level smoke for the shipped synchronous httpx transport."""

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
import uvicorn

from bookshelf._core.client import BookshelfClient


@pytest.fixture
def live_api_url(app: Any) -> Iterator[str]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    host, port = listener.getsockname()
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", lifespan="off", access_log=False)
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="sdk-uvicorn-smoke",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        pytest.fail("ephemeral uvicorn server did not start")

    yield f"http://{host}:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    listener.close()
    assert not thread.is_alive(), "ephemeral uvicorn server did not stop"


def test_sync_transport_reaches_an_ephemeral_uvicorn_socket(live_api_url: str) -> None:
    with BookshelfClient(live_api_url, auth=None) as client:
        response = client.list_resources(limit=1)

    assert response.items == []
