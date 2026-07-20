"""Minimal Supernote Private-Cloud client for the fixture loop.

Implements the private-cloud dialect captured in Analysis 0013/0015:
sncloud-compatible login (randomCode + sha256(md5(pw)+rc)), listing, the
custom upload flow (upload/apply -> multipart POST /api/oss/upload ->
upload/finish), and download-URL fetch.

Usage:
    from pc_client import PCClient
    c = PCClient.from_env()     # INKBRIDGE_CLOUD_{URL,EMAIL,PASSWORD} from
                                # the repo .env (or the environment), logged in
    c.ls()                      # root
    c.push(Path("f.pdf"), "Document")
    c.pull("Document", "f.pdf.mark", Path("out/f.pdf.mark"))
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.parse import urlencode

import httpx

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _env(name: str) -> str:
    """INKBRIDGE_CLOUD_* setting from the environment, else the repo .env."""
    if name in os.environ:
        return os.environ[name]
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise KeyError(f"{name} not set in environment or {_ENV_PATH}")


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class PCClient:
    def __init__(self, base: str):
        self.api = base.rstrip("/") + "/api"
        self.http = httpx.Client(timeout=60)
        self.token: str | None = None

    @classmethod
    def from_env(cls) -> "PCClient":
        c = cls(_env("INKBRIDGE_CLOUD_URL"))
        c.login(_env("INKBRIDGE_CLOUD_EMAIL"), _env("INKBRIDGE_CLOUD_PASSWORD"))
        return c

    def _call(self, endpoint: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["x-access-token"] = self.token
        r = self.http.post(self.api + endpoint, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if not data.get("success", False):
            raise RuntimeError(f"{endpoint}: {data.get('errorCode')} {data.get('errorMsg')}")
        return data

    def login(self, email: str, password: str) -> None:
        rc = self._call("/official/user/query/random/code", {"countryCode": 1, "account": email})
        pd = _sha256(hashlib.md5(password.encode()).hexdigest() + rc["randomCode"])
        data = self._call(
            "/official/user/account/login/new",
            {
                "countryCode": 1,
                "account": email,
                "password": pd,
                "browser": "Chrome107",
                "equipment": "1",
                "loginMethod": "1",
                "timestamp": rc["timestamp"],
                "language": "en",
            },
        )
        self.token = data["token"]

    def ls(self, directory_id: int = 0) -> list[dict]:
        data = self._call(
            "/file/list/query",
            {"directoryId": directory_id, "pageNo": 1, "pageSize": 100,
             "order": "time", "sequence": "desc"},
        )
        return data["userFileVOList"]

    def dir_id(self, name: str) -> int:
        for item in self.ls():
            if item["fileName"] == name and item["isFolder"] == "Y":
                return int(item["id"])
        raise FileNotFoundError(f"root folder not found: {name}")

    def find(self, folder: str, filename: str) -> dict | None:
        for item in self.ls(self.dir_id(folder)):
            if item["fileName"] == filename:
                return item
        return None

    def push(self, path: Path, folder: str = "Document") -> dict:
        blob = path.read_bytes()
        md5 = _md5(blob)
        did = self.dir_id(folder)
        apply_ = self._call(
            "/file/upload/apply",
            {"directoryId": did, "fileName": path.name, "md5": md5, "size": len(blob)},
        )
        url = apply_.get("fullUploadUrl") or apply_.get("url")
        # Append to the signed query by hand: httpx's params= REPLACES the
        # URL's query string, which would strip signature/timestamp/nonce/path
        # and make the server reject the upload with a 200 success:false body.
        extra = urlencode({k: apply_[k] for k in ("innerName", "fileName") if apply_.get(k)})
        if extra:
            url += ("&" if "?" in url else "?") + extra
        r = self.http.post(url, files={"file": (path.name, blob, "application/octet-stream")},
                           headers={"x-access-token": self.token})
        r.raise_for_status()
        body = r.json()
        if not body.get("success", False):
            raise RuntimeError(f"oss/upload: {body.get('errorCode')} {body.get('errorMsg')}")
        inner = apply_.get("innerName") or url.rsplit("/", 1)[-1]
        self._call(
            "/file/upload/finish",
            {"directoryId": did, "fileName": path.name, "fileSize": len(blob),
             "innerName": inner, "md5": md5},
        )
        return {"md5": md5, "size": len(blob), "folder": folder, "name": path.name}

    def pull(self, folder: str, filename: str, dest: Path) -> dict:
        item = self.find(folder, filename)
        if item is None:
            raise FileNotFoundError(f"{folder}/{filename} not on server")
        data = self._call("/file/download/url", {"id": item["id"], "type": 0})
        r = self.http.get(data["url"], follow_redirects=True,
                          headers={"x-access-token": self.token})
        r.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        got = _md5(r.content)
        return {"listing_md5": item["md5"], "bytes_md5": got,
                "match": got == item["md5"], "size": len(r.content), "dest": str(dest)}


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        os.environ["INKBRIDGE_CLOUD_URL"] = sys.argv[1]
    c = PCClient.from_env()
    for it in c.ls(c.dir_id("Document")):
        print(json.dumps({k: it.get(k) for k in ("fileName", "md5", "size", "updateTime")},
                         ensure_ascii=False))
