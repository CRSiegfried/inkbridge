"""Offline tests for the private-cloud transport against a mocked server.

The mock reproduces the contract from Analysis 0013 F7: signed-query
required on oss/upload (rejection is HTTP 200 + success:false), token
header required, upload/finish trusts the client, phantom rows serve
E0321 on download.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from inkbridge.transport.private_cloud import (
    MissingBytesError,
    PCClient,
    PrivateCloudError,
    _env,
    login_password_digest,
)

TOKEN = "tok-123"
DOC_DIR_ID = 42


class FakeServer:
    """State machine for the mocked private cloud."""

    def __init__(self):
        # fileName -> listing row; bytes stored separately so we can model
        # phantom rows (row present, bytes absent).
        self.rows: dict[str, dict] = {}
        self.blobs: dict[str, bytes] = {}
        self.strip_signature = False  # simulate httpx params= footgun server-side

    def row(self, name: str, md5: str, size: int, file_id: str) -> dict:
        return {"id": file_id, "fileName": name, "isFolder": "N",
                "md5": md5, "size": size}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        ok = lambda extra=None: httpx.Response(200, json={"success": True, **(extra or {})})  # noqa: E731
        fail = lambda code, msg: httpx.Response(  # noqa: E731
            200, json={"success": False, "errorCode": code, "errorMsg": msg})

        if path == "/api/official/user/query/random/code":
            return ok({"randomCode": "RC", "timestamp": 1700000000})
        if path == "/api/official/user/account/login/new":
            body = json.loads(request.content)
            expected = login_password_digest("pw", "RC")
            if body["password"] != expected:
                return fail("E0000", "bad password digest")
            return ok({"token": TOKEN})

        # everything below needs the token
        if request.headers.get("x-access-token") != TOKEN:
            return httpx.Response(401)

        if path == "/api/file/list/query":
            body = json.loads(request.content)
            if body["directoryId"] == 0:
                rows = [{"id": DOC_DIR_ID, "fileName": "Document", "isFolder": "Y",
                         "md5": "", "size": 0}]
            elif body["directoryId"] == DOC_DIR_ID:
                rows = list(self.rows.values())
            else:
                rows = []
            return ok({"userFileVOList": rows})

        if path == "/api/file/upload/apply":
            body = json.loads(request.content)
            return ok({
                "fullUploadUrl": "http://cloud.test/api/oss/upload"
                                 "?signature=SIG&timestamp=1&nonce=N&path=P",
                "innerName": "inner-" + body["fileName"],
            })

        if path == "/api/oss/upload":
            if self.strip_signature or "signature" not in dict(request.url.params):
                return fail("E0001", "signature missing")  # 200 + success:false
            inner = request.url.params.get("innerName")
            # crude multipart body capture: everything between the part header
            # blank line and the closing boundary
            raw = request.read()
            payload = raw.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            self.blobs[inner] = payload
            return ok()

        if path == "/api/file/upload/finish":
            body = json.loads(request.content)
            # trusts the client: records the row whether or not bytes landed
            self.rows[body["fileName"]] = self.row(
                body["fileName"], body["md5"], body["fileSize"],
                "id-" + body["fileName"])
            return ok()

        if path == "/api/file/download/url":
            body = json.loads(request.content)
            name = body["id"].removeprefix("id-")
            inner = "inner-" + name
            if inner not in self.blobs:
                return fail("E0321", "This file does not exist")
            return ok({"url": f"http://cloud.test/blob/{inner}"})

        if path.startswith("/blob/"):
            inner = path.removeprefix("/blob/")
            return httpx.Response(200, content=self.blobs[inner],
                                  headers={"content-type": "application/octet-stream"})

        return httpx.Response(404)


@pytest.fixture()
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture()
def client(server: FakeServer) -> PCClient:
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    c = PCClient("http://cloud.test", http=http)
    c.login("user@test", "pw")
    return c


def test_login_digest_shape():
    # sha256(md5(pw) + randomCode), hex — the sncloud-compatible scheme
    assert login_password_digest("pw", "RC") == hashlib.sha256(
        (hashlib.md5(b"pw").hexdigest() + "RC").encode()).hexdigest()


def test_login_sets_token(client: PCClient):
    assert client.token == TOKEN


def test_push_roundtrip(client: PCClient, server: FakeServer, tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-fake")
    info = client.push(f, "Document")
    assert info["md5"] == hashlib.md5(b"%PDF-fake").hexdigest()
    assert server.blobs["inner-doc.pdf"] == b"%PDF-fake"

    out = tmp_path / "back.pdf"
    got = client.pull("Document", "doc.pdf", out)
    assert got["match"] is True
    assert out.read_bytes() == b"%PDF-fake"


def test_push_rejects_success_false_body(client: PCClient, server: FakeServer,
                                         tmp_path: Path):
    # 0013 F7: stripped signature fails as HTTP 200 + success:false; a
    # status-code-only client would think the upload landed.
    server.strip_signature = True
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    with pytest.raises(PrivateCloudError) as exc:
        client.push(f, "Document")
    assert exc.value.endpoint == "/oss/upload"
    assert server.blobs == {}


def test_push_verifies_listing_md5(client: PCClient, server: FakeServer,
                                   tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"payload")

    original_handler = server.handler

    def corrupting_handler(request: httpx.Request) -> httpx.Response:
        resp = original_handler(request)
        if request.url.path == "/api/file/upload/finish":
            server.rows["doc.pdf"]["md5"] = "0" * 32
        return resp

    client.http = httpx.Client(transport=httpx.MockTransport(corrupting_handler))
    with pytest.raises(PrivateCloudError, match="md5"):
        client.push(f, "Document")


def test_pull_phantom_row_raises_missing_bytes(client: PCClient, server: FakeServer,
                                               tmp_path: Path):
    # Row in the listing, no bytes behind it: upload/finish trusted a client
    # whose oss/upload never landed. Must surface as FileNotFoundError.
    server.rows["ghost.pdf"] = server.row("ghost.pdf", "a" * 32, 10, "id-ghost.pdf")
    with pytest.raises(MissingBytesError):
        client.pull("Document", "ghost.pdf", tmp_path / "out.pdf")
    assert isinstance(MissingBytesError("x"), FileNotFoundError)


def test_push_same_name_maps_to_file_exists(client: PCClient, server: FakeServer,
                                            tmp_path: Path):
    # Observed live 2026-07-20: same-name re-push is refused at apply time.
    original_handler = server.handler

    def refusing_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/file/upload/apply":
            return httpx.Response(200, json={
                "success": False, "errorCode": "E0322",
                "errorMsg": "A file with the same name already exists"})
        return original_handler(request)

    client.http = httpx.Client(transport=httpx.MockTransport(refusing_handler))
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    with pytest.raises(FileExistsError, match="E0322"):
        client.push(f, "Document")


def test_pull_unlisted_file_raises(client: PCClient, tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="not on server"):
        client.pull("Document", "nope.pdf", tmp_path / "out.pdf")


def test_signed_query_survives_extra_params(client: PCClient, server: FakeServer,
                                            tmp_path: Path):
    # The client must append innerName/fileName to the signed query without
    # replacing it (the httpx params= footgun from 0013 F7).
    seen = {}
    original_handler = server.handler

    def spying_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/oss/upload":
            seen.update(dict(request.url.params))
        return original_handler(request)

    client.http = httpx.Client(transport=httpx.MockTransport(spying_handler))
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    client.push(f, "Document")
    assert {"signature", "timestamp", "nonce", "path", "innerName"} <= set(seen)


def test_env_reads_dotenv_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("INKBRIDGE_CLOUD_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text('INKBRIDGE_CLOUD_URL="http://x:19072"\n')
    assert _env("INKBRIDGE_CLOUD_URL", env) == "http://x:19072"
    with pytest.raises(KeyError):
        _env("INKBRIDGE_CLOUD_EMAIL", env)


def test_env_prefers_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CLOUD_URL", "http://env-wins")
    env = tmp_path / ".env"
    env.write_text("INKBRIDGE_CLOUD_URL=http://file\n")
    assert _env("INKBRIDGE_CLOUD_URL", env) == "http://env-wins"
