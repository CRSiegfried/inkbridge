"""Supernote Private-Cloud transport.

Implements the private-cloud dialect:
sncloud-compatible login (randomCode + sha256(md5(pw)+rc)), listing, the
custom upload flow (upload/apply -> multipart POST /api/oss/upload ->
upload/finish), and download-URL fetch.

The upload contract is load-bearing here:

- ``POST /api/oss/upload`` needs both the signed query from ``upload/apply``
  and the ``x-access-token`` header; a stripped signature fails as HTTP 200
  with a ``success: false`` body, so the response body is always checked.
- ``upload/finish`` records listing metadata without verifying bytes, so
  ``push`` re-checks the listing afterwards and compares the row's md5.
- A listing row is not proof of retrievable bytes: ``pull`` maps the
  server's E0321 ("file does not exist") to :class:`MissingBytesError`
  (a ``FileNotFoundError``) so pollers can treat it as a benign phantom.

Usage:
    from inkbridge.transport.private_cloud import PCClient
    c = PCClient.from_env()     # INKBRIDGE_CLOUD_{URL,EMAIL,PASSWORD} from
                                # the environment or ./.env, logged in
    c.ls()                      # root listing
    c.push(Path("f.pdf"), "Document")
    c.pull("Document", "f.pdf.mark", Path("out/f.pdf.mark"))
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from inkbridge.obs import get_logger
from inkbridge.transport import base

ENV_VARS = ("INKBRIDGE_CLOUD_URL", "INKBRIDGE_CLOUD_EMAIL", "INKBRIDGE_CLOUD_PASSWORD")

_log = get_logger("cloud")


class PrivateCloudError(RuntimeError):
    """A private-cloud API call returned ``success: false``."""

    def __init__(self, endpoint: str, error_code: str | None, error_msg: str | None):
        super().__init__(f"{endpoint}: {error_code} {error_msg}")
        self.endpoint = endpoint
        self.error_code = error_code
        self.error_msg = error_msg


class AuthError(PrivateCloudError, base.AuthError):
    """Authentication/authorization failure: credentials rejected at login,
    or a 401/403 on an authenticated call (a missing or expired token). A
    typed subclass — like :class:`MissingBytesError` — so the CLI maps it to
    the contract's AUTH(5) exit without inspecting error strings. Also a
    :class:`inkbridge.transport.base.AuthError` so ``_cloud_errors``
    can catch the transport-neutral type; the 3-arg ``PrivateCloudError``
    constructor and message are unchanged (it wins the MRO).
    """


class MissingBytesError(base.MissingBytesError):
    """The listing has a row for the file but the bytes are not on disk
    server-side (E0321). This is a benign phantom row —
    ``upload/finish`` trusts the client, and login-triggered reconciliation
    purges such rows later. Pollers should treat this as "not there yet",
    not as corruption. Still a ``FileNotFoundError`` via the neutral base.
    """


def _env(name: str, env_file: Path | None = None) -> str:
    """Setting from the environment, else the .env file (default ./.env)."""
    if name in os.environ:
        return os.environ[name]
    env_file = env_file or Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise KeyError(f"{name} not set in environment or {env_file}")


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def login_password_digest(password: str, random_code: str) -> str:
    """sncloud-compatible login digest: sha256(md5(password) + randomCode)."""
    inner = hashlib.md5(password.encode()).hexdigest()
    return hashlib.sha256((inner + random_code).encode()).hexdigest()


class PCClient:
    """Client for one private-cloud instance. Construct then :meth:`login`,
    or use :meth:`from_env`.
    """

    def __init__(self, base: str, http: httpx.Client | None = None):
        self.api = base.rstrip("/") + "/api"
        self.http = http or httpx.Client(timeout=60)
        self.token: str | None = None

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "PCClient":
        c = cls(_env("INKBRIDGE_CLOUD_URL", env_file))
        c.login(
            _env("INKBRIDGE_CLOUD_EMAIL", env_file),
            _env("INKBRIDGE_CLOUD_PASSWORD", env_file),
        )
        return c

    def _call(self, endpoint: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["x-access-token"] = self.token
        start = time.monotonic()
        r = self.http.post(self.api + endpoint, json=payload, headers=headers)
        # One timed request line per API call, at INFO so a plain -v surfaces
        # per-request activity (D5) while stdout stays contract-pure.
        _log.info(
            "POST %s -> %d (%.0fms)", endpoint, r.status_code,
            (time.monotonic() - start) * 1000,
        )
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise AuthError(endpoint, str(e.response.status_code),
                                "not authorized (token missing or expired)") from e
            raise
        data = r.json()
        if not data.get("success", False):
            raise PrivateCloudError(endpoint, data.get("errorCode"), data.get("errorMsg"))
        return data

    def login(self, email: str, password: str) -> None:
        try:
            rc = self._call("/official/user/query/random/code",
                            {"countryCode": 1, "account": email})
            data = self._call(
                "/official/user/account/login/new",
                {
                    "countryCode": 1,
                    "account": email,
                    "password": login_password_digest(password, rc["randomCode"]),
                    "browser": "Chrome107",
                    "equipment": "1",
                    "loginMethod": "1",
                    "timestamp": rc["timestamp"],
                    "language": "en",
                },
            )
        except AuthError:
            raise
        except PrivateCloudError as e:
            # A success:false from the random-code / login endpoints is an
            # authentication failure (unknown account or wrong password) —
            # surface it as the contract's AUTH class, not a generic error.
            raise AuthError(e.endpoint, e.error_code, e.error_msg) from e
        self.token = data["token"]
        _log.info("logged in to %s", self.api)

    def ls(self, directory_id: int = 0) -> list[dict]:
        """List a directory in full, following pagination to exhaustion.

        The listing endpoint pages at ``pageSize``; a lone ``pageNo=1`` query
        silently truncates a folder of more than 100 items, which would make
        ``find``, ``check_entries``, and push's post-upload verify treat a
        present file as missing. Fetch successive pages until one comes back
        short of a full page.
        """
        page_size = 100
        items: list[dict] = []
        page_no = 1
        while True:
            data = self._call(
                "/file/list/query",
                {"directoryId": directory_id, "pageNo": page_no,
                 "pageSize": page_size, "order": "time", "sequence": "desc"},
            )
            batch = data["userFileVOList"]
            items.extend(batch)
            if len(batch) < page_size:
                return items
            page_no += 1

    def resolve_dir(self, folder: str) -> int:
        """Directory id for a folder path — ``"Document"`` or nested like
        ``"Document/Projects"`` — walking one listing per segment from the
        root. ``""`` / ``"/"`` resolve to the root itself. Raises
        FileNotFoundError naming the first missing segment; there is no
        folder-creation endpoint in the captured dialect, so folders must
        already exist (made on-device or in the web UI).
        """
        did = 0
        walked: list[str] = []
        for seg in folder.strip("/").split("/"):
            if not seg:
                continue
            row = next((i for i in self.ls(did)
                        if i["fileName"] == seg and i["isFolder"] == "Y"), None)
            if row is None:
                where = "/".join(walked) or "the root"
                raise FileNotFoundError(
                    f"folder {seg!r} not found in {where} (folders are not "
                    "created by inkbridge — make it on the device or web UI)")
            walked.append(seg)
            did = int(row["id"])
        return did

    def find(self, folder: str, filename: str) -> dict | None:
        for item in self.ls(self.resolve_dir(folder)):
            if item["fileName"] == filename:
                return item
        return None

    def push(self, path: Path, folder: str = "Document", *, verify: bool = True) -> dict:
        """Upload ``path`` into the named folder (nested paths ok).

        Checks the ``oss/upload`` response body (a stripped signature fails
        as 200/success:false — 0013 F7) and, with ``verify``, confirms the
        listing row exists afterwards with the local md5. The body check is
        the actual byte-store ack; the listing check catches a finish-time
        metadata mismatch.
        """
        blob = path.read_bytes()
        md5 = _md5(blob)
        did = self.resolve_dir(folder)
        try:
            apply_ = self._call(
                "/file/upload/apply",
                {"directoryId": did, "fileName": path.name, "md5": md5, "size": len(blob)},
            )
        except PrivateCloudError as e:
            # Observed live (2026-07-20): same-name re-push is refused at
            # apply time — the server has no overwrite in this flow.
            if e.error_code == "E0322":
                raise FileExistsError(
                    f"{folder}/{path.name} already exists on the server (E0322); "
                    "the private cloud does not overwrite — push under a new "
                    "name or delete the remote copy first") from e
            raise
        url = apply_.get("fullUploadUrl") or apply_.get("url")
        # Append to the signed query by hand: httpx's params= REPLACES the
        # URL's query string, which would strip signature/timestamp/nonce/path
        # and make the server reject the upload with a 200 success:false body.
        extra = urlencode({k: apply_[k] for k in ("innerName", "fileName") if apply_.get(k)})
        if extra:
            url += ("&" if "?" in url else "?") + extra
        up_start = time.monotonic()
        r = self.http.post(url, files={"file": (path.name, blob, "application/octet-stream")},
                           headers={"x-access-token": self.token})
        # The actual byte upload (multipart) — its own timed line at INFO (D5),
        # since it bypasses _call.
        _log.info(
            "PUT %s -> %d (%d bytes, %.0fms)", "/oss/upload (multipart)",
            r.status_code, len(blob), (time.monotonic() - up_start) * 1000,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("success", False):
            raise PrivateCloudError("/oss/upload", body.get("errorCode"), body.get("errorMsg"))
        inner = apply_.get("innerName") or url.rsplit("/", 1)[-1]
        self._call(
            "/file/upload/finish",
            {"directoryId": did, "fileName": path.name, "fileSize": len(blob),
             "innerName": inner, "md5": md5},
        )
        if verify:
            row = self.find(folder, path.name)
            if row is None:
                raise PrivateCloudError(
                    "/file/upload/finish", None,
                    f"{folder}/{path.name} absent from listing after upload")
            if row.get("md5") != md5:
                raise PrivateCloudError(
                    "/file/upload/finish", None,
                    f"{folder}/{path.name} listed with md5 {row.get('md5')}, expected {md5}")
        return {"md5": md5, "size": len(blob), "folder": folder, "name": path.name}

    def delete(self, folder: str, filenames: str | list[str]) -> list[str]:
        """Delete files from a folder (sncloud-dialect ``/file/delete``
        with an idList; nested folder paths ok). All names must exist in the
        listing; raises FileNotFoundError naming the missing ones before
        deleting anything.
        """
        if isinstance(filenames, str):
            filenames = [filenames]
        did = self.resolve_dir(folder)
        rows = {i["fileName"]: i for i in self.ls(did)}
        missing = [n for n in filenames if n not in rows]
        if missing:
            raise FileNotFoundError(
                f"not on server in {folder}: {', '.join(missing)}")
        self._call(
            "/file/delete",
            {"directoryId": did, "idList": [rows[n]["id"] for n in filenames]},
        )
        return list(filenames)

    def pull(self, folder: str, filename: str, dest: Path) -> dict:
        """Download ``folder/filename`` to ``dest``.

        Raises :class:`FileNotFoundError` if no listing row exists, and
        :class:`MissingBytesError` (also a ``FileNotFoundError``) if the row
        exists but the server can't serve the bytes (E0321 phantom row).
        """
        item = self.find(folder, filename)
        if item is None:
            raise FileNotFoundError(f"{folder}/{filename} not on server")
        try:
            data = self._call("/file/download/url", {"id": item["id"], "type": 0})
        except PrivateCloudError as e:
            if e.error_code == "E0321":
                raise MissingBytesError(
                    f"{folder}/{filename}: listing row exists but bytes are missing "
                    "server-side (E0321 phantom row; reconciliation will purge it)"
                ) from e
            raise
        dl_start = time.monotonic()
        r = self.http.get(data["url"], follow_redirects=True,
                          headers={"x-access-token": self.token})
        # The actual byte download — its own timed line at INFO (D5), since it
        # bypasses _call.
        _log.info(
            "GET %s -> %d (%d bytes, %.0fms)", "blob", r.status_code,
            len(r.content), (time.monotonic() - dl_start) * 1000,
        )
        r.raise_for_status()
        # 0013 F7: the URL fetch itself can come back as a JSON error body
        # (the live capture saw E0321 at this hop) instead of file bytes.
        if r.headers.get("content-type", "").startswith("application/json"):
            body = r.json()
            if isinstance(body, dict) and not body.get("success", True):
                if body.get("errorCode") == "E0321":
                    raise MissingBytesError(
                        f"{folder}/{filename}: listing row exists but bytes are "
                        "missing server-side (E0321 phantom row)")
                raise PrivateCloudError("download", body.get("errorCode"), body.get("errorMsg"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        got = _md5(r.content)
        return {"listing_md5": item["md5"], "bytes_md5": got,
                "match": got == item["md5"], "size": len(r.content), "dest": str(dest)}
