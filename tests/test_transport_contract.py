"""Transport conformance suite (ADR-0007 / remediation A2).

The backend-neutral contract the CLI and ``ops`` depend on — payload shapes
and error semantics, not method names — asserted against every registered
backend. One backend today (the private cloud over ``fake_cloud``); D3's
``LocalFolder`` will plug into the same ``backend`` fixture. Dialect-specific
behavior (signature stripping, E0321 phantoms, pagination) stays in
``test_private_cloud.py`` — migrating it here would make the suite unpassable
for any other backend.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import httpx
import pytest
from fake_cloud import FakeServer

from inkbridge.transport import AuthError, MissingBytesError, Transport
from inkbridge.transport.private_cloud import PCClient


def _private_cloud_backend() -> SimpleNamespace:
    server = FakeServer()
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    client = PCClient("http://cloud.test", http=http)
    client.login("user@test", "pw")
    return SimpleNamespace(name="private_cloud", client=client, server=server)


# Every registered backend runs the same suite. Add LocalFolder here for D3.
BACKENDS = {"private_cloud": _private_cloud_backend}


@pytest.fixture(params=list(BACKENDS))
def backend(request) -> SimpleNamespace:
    return BACKENDS[request.param]()


def _push_tmp(backend, tmp_path, name="doc.pdf", data=b"%PDF-roundtrip") -> bytes:
    f = tmp_path / name
    f.write_bytes(data)
    backend.client.push(f, "Document")
    return data


# -- structural: the seam's protocol + neutral error hierarchy ------------

def test_client_satisfies_transport_protocol(backend):
    assert isinstance(backend.client, Transport)


def test_neutral_exception_hierarchy():
    # The seam's errors are neutral BASES of each backend's own error, and
    # MissingBytesError stays a FileNotFoundError so the phantom-row path maps
    # to NO_CHANGE without string-sniffing (ADR-0007).
    from inkbridge.transport import private_cloud as pc

    assert issubclass(pc.AuthError, AuthError)
    assert issubclass(pc.MissingBytesError, MissingBytesError)
    assert issubclass(MissingBytesError, FileNotFoundError)


# -- semantic: the payload shapes + error taxonomy cli/ops rely on --------

def test_push_pull_roundtrip_and_result_shapes(backend, tmp_path):
    data = b"%PDF-roundtrip"
    info = backend.client.push(_write(tmp_path, "doc.pdf", data), "Document")
    # push result shape
    assert set(info) >= {"md5", "size", "folder", "name"}
    assert info["md5"] == hashlib.md5(data).hexdigest()
    assert info["folder"] == "Document" and info["name"] == "doc.pdf"
    assert info["size"] == len(data)

    # pull round-trips bytes and reports a matching md5
    dest = tmp_path / "out" / "doc.pdf"
    pinfo = backend.client.pull("Document", "doc.pdf", dest)
    assert set(pinfo) >= {"listing_md5", "bytes_md5", "match", "size"}
    assert pinfo["match"] is True
    assert dest.read_bytes() == data


def test_push_to_missing_folder_is_filenotfound(backend, tmp_path):
    with pytest.raises(FileNotFoundError):
        backend.client.push(_write(tmp_path, "x.pdf", b"x"), "Nonexistent")


def test_duplicate_push_is_fileexists(backend, tmp_path):
    # The private cloud has no overwrite: a same-name re-push is refused
    # (E0322 → FileExistsError), which is what dispatch --replace exists to work
    # around (A4). fake_cloud models the refusal as of A4.
    _push_tmp(backend, tmp_path)
    with pytest.raises(FileExistsError):
        backend.client.push(_write(tmp_path, "doc.pdf", b"%PDF-roundtrip"), "Document")


def test_pull_absent_is_filenotfound(backend, tmp_path):
    with pytest.raises(FileNotFoundError):
        backend.client.pull("Document", "nope.pdf", tmp_path / "x")


def test_delete_removes_named(backend, tmp_path):
    _push_tmp(backend, tmp_path)
    assert backend.client.delete("Document", ["doc.pdf"]) == ["doc.pdf"]
    with pytest.raises(FileNotFoundError):
        backend.client.pull("Document", "doc.pdf", tmp_path / "y")


def test_delete_refuses_atomically_when_any_missing(backend, tmp_path):
    _push_tmp(backend, tmp_path, name="keep.pdf")
    with pytest.raises(FileNotFoundError):
        backend.client.delete("Document", ["keep.pdf", "missing.pdf"])
    # atomic: the present file must survive the refused batch
    rows = {r["fileName"]
            for r in backend.client.ls(backend.client.resolve_dir("Document"))}
    assert "keep.pdf" in rows


def test_ls_row_shape_and_resolve_compose(backend, tmp_path):
    _push_tmp(backend, tmp_path)
    handle = backend.client.resolve_dir("Document")  # opaque; ls consumes it
    rows = backend.client.ls(handle)
    row = next(r for r in rows if r["fileName"] == "doc.pdf")
    assert set(row) >= {"fileName", "isFolder", "size", "md5"}
    assert row["isFolder"] == "N"


def test_resolve_missing_folder_is_filenotfound(backend):
    with pytest.raises(FileNotFoundError):
        backend.client.resolve_dir("NoSuchFolder")


def _write(tmp_path, name, data):
    f = tmp_path / name
    f.write_bytes(data)
    return f
