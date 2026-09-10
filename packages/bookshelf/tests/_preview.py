"""A mocked deployment answering the calls a preview upload makes, shared across modules."""

import json
from typing import Any

import httpx

from tests._core_payloads import TS

BASE_URL = "https://bookshelf.test"
PREVIEW_ID = "0197a000-0000-7000-8000-0000000000f1"
SHA = "a" * 40


class PreviewDeployment:
    """Answers the preview routes, recording every request and remembering the preview's state.

    ``refuse`` maps a path suffix to the status the deployment answers it with instead.
    ``multipart`` answers every upload with two parts instead of one.
    """

    def __init__(self, *, refuse: dict[str, int] | None = None, multipart: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.refuse = refuse or {}
        self.multipart = multipart
        self.state = "open"
        self.failure_reason: str | None = None
        self.targets: list[dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def detail(self) -> dict[str, Any]:
        return {
            "id": PREVIEW_ID,
            "proposal_id": "0197a000-0000-7000-8000-0000000000f0",
            "repository": "climate-resource/feedstock",
            "pr_number": 7,
            "candidate": {"head_sha": SHA, "main_sha": SHA, "candidate_tree": SHA},
            "run_id": "42",
            "state": self.state,
            "created_at": TS,
            "sealed_at": TS if self.state == "sealed" else None,
            "failure_reason": self.failure_reason,
            "proposal_url": f"{BASE_URL}/v1/proposals/climate-resource%2Ffeedstock/7",
            "preview_url": f"{BASE_URL}/previews/{PREVIEW_ID}",
            "targets": self.targets,
        }

    def sent(self, suffix: str) -> list[dict[str, Any]]:
        """The JSON bodies of every request whose path ends with ``suffix``."""
        return [
            json.loads(request.content) if request.content else {}
            for request in self.requests
            if request.url.path.endswith(suffix)
        ]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        for suffix, status in self.refuse.items():
            if path.endswith(suffix):
                return httpx.Response(
                    status,
                    json={"title": "Refused", "status": status, "detail": f"refused {suffix}"},
                )
        if request.url.host == "s3.example":
            return httpx.Response(200, headers={"etag": '"etag"'})
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/previews") and path.startswith("/v1/proposals/"):
            self.targets = [
                {**target, "uploaded": False, "baseline": "absent"} for target in body["targets"]
            ]
            return httpx.Response(201, json=self.detail())
        if path.endswith("/uploads"):
            hex_digest = body["hash"].removeprefix("sha256:")
            storage_path = f"preview/org_1/{PREVIEW_ID}/sha256/{hex_digest}"
            size = body["size_bytes"]
            parts = [(1, 0, size // 2), (2, size // 2, size)] if self.multipart else [(1, 0, size)]
            return httpx.Response(
                200,
                json={
                    "upload_id": "multi" if self.multipart else "single",
                    "storage_path": storage_path,
                    "parts": [
                        {
                            "part_number": number,
                            "presigned_url": f"https://s3.example/{hex_digest}/{number}",
                            "start_byte": start,
                            "end_byte": end,
                        }
                        for number, start, end in parts
                    ],
                },
            )
        if path.endswith("/uploads/complete"):
            return httpx.Response(204)
        if "/books/" in path:
            _, volume, version = path.rsplit("/", 2)
            for target in self.targets:
                if (target["volume"], target["version"]) == (volume, version):
                    target["uploaded"] = True
            return httpx.Response(200, json=self.detail())
        if path.endswith("/seal"):
            self.state = "sealed"
            return httpx.Response(200, json=self.detail())
        if path.endswith("/fail"):
            self.state = "failed"
            self.failure_reason = body["reason"]
            return httpx.Response(200, json=self.detail())
        raise AssertionError(f"unexpected request to {path}")
