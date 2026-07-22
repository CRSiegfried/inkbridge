"""Offline tests for the private-cloud transport against a mocked server
(tests/fake_cloud.py; fixtures in conftest.py)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from fake_cloud import DOC_DIR_ID, SUB_DIR_ID, TOKEN, FakeServer

from inkbridge.transport.private_cloud import (
    AuthError,
    MissingBytesError,
    PCClient,
    PrivateCloudError,
    _env,
    login_password_digest,
)


def test_login_digest_shape():
    # sha256(md5(pw) + randomCode), hex — the sncloud-compatible scheme
    assert login_password_digest("pw", "RC") == hashlib.sha256(
        (hashlib.md5(b"pw").hexdigest() + "RC").encode()).hexdigest()


def test_login_sets_token(client: PCClient):
    assert client.token == TOKEN


def test_login_bad_password_raises_auth(server: FakeServer):
    # A success:false from the login endpoint is an auth failure, typed so the
    # CLI can map it to AUTH(5) — not a generic PrivateCloudError.
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    c = PCClient("http://cloud.test", http=http)
    with pytest.raises(AuthError):
        c.login("user@test", "wrong-password")


def test_expired_token_raises_auth(client: PCClient):
    # A 401 on an authenticated call (missing/expired token) -> AuthError.
    client.token = "stale-token"
    with pytest.raises(AuthError):
        client.ls()


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


def test_delete_removes_row_and_bytes(client: PCClient, server: FakeServer,
                                      tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    client.push(f, "Document")
    assert client.delete("Document", "doc.pdf") == ["doc.pdf"]
    assert server.rows == {} and server.blobs == {}
    with pytest.raises(FileNotFoundError):
        client.pull("Document", "doc.pdf", tmp_path / "out.pdf")


def test_delete_missing_name_deletes_nothing(client: PCClient, server: FakeServer,
                                             tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"x")
    client.push(f, "Document")
    with pytest.raises(FileNotFoundError, match="nope.pdf"):
        client.delete("Document", ["doc.pdf", "nope.pdf"])
    assert "doc.pdf" in server.rows  # all-or-nothing: nothing was deleted


def test_pull_unlisted_file_raises(client: PCClient, tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="not on server"):
        client.pull("Document", "nope.pdf", tmp_path / "out.pdf")


def test_nested_folder_roundtrip(client: PCClient, server: FakeServer,
                                 tmp_path: Path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"nested")
    info = client.push(f, "Document/Projects")
    assert info["folder"] == "Document/Projects"
    assert server.dirs[SUB_DIR_ID]["doc.pdf"]["md5"] == hashlib.md5(b"nested").hexdigest()
    assert client.find("Document", "doc.pdf") is None  # landed in the subfolder only

    out = tmp_path / "back.pdf"
    got = client.pull("Document/Projects", "doc.pdf", out)
    assert got["match"] is True and out.read_bytes() == b"nested"

    assert client.delete("Document/Projects", "doc.pdf") == ["doc.pdf"]
    assert server.dirs[SUB_DIR_ID] == {}


def test_resolve_dir_walks_segments(client: PCClient):
    assert client.resolve_dir("Document") == DOC_DIR_ID
    assert client.resolve_dir("Document/Projects") == SUB_DIR_ID
    assert client.resolve_dir("/Document/Projects/") == SUB_DIR_ID  # slash-tolerant
    assert client.resolve_dir("") == 0 and client.resolve_dir("/") == 0  # the root


def test_resolve_dir_names_missing_segment(client: PCClient):
    with pytest.raises(FileNotFoundError, match="'Archive' not found in Document"):
        client.resolve_dir("Document/Archive")
    with pytest.raises(FileNotFoundError, match="'Nope' not found in the root"):
        client.resolve_dir("Nope/Deeper")


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
