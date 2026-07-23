"""Mocked private-cloud server shared by transport and dispatch tests.

Reproduces the contract from Analysis 0013 F7: signed-query required on
oss/upload (rejection is HTTP 200 + success:false), token header required,
upload/finish trusts the client, phantom rows serve E0321 on download.
"""

from __future__ import annotations

import json

import httpx

from inkbridge.transport.private_cloud import login_password_digest

TOKEN = "tok-123"
DOC_DIR_ID = 42
SUB_DIR_ID = 77  # "Projects", nested inside Document


class FakeServer:
    """State machine for the mocked private cloud."""

    def __init__(self):
        # directoryId -> {fileName -> listing row}; bytes stored separately
        # so we can model phantom rows (row present, bytes absent).
        self.dirs: dict[int, dict[str, dict]] = {DOC_DIR_ID: {}, SUB_DIR_ID: {}}
        self.blobs: dict[str, bytes] = {}
        self.strip_signature = False  # simulate httpx params= footgun server-side

    @property
    def rows(self) -> dict[str, dict]:
        """The Document folder's rows — the directory most tests speak to."""
        return self.dirs[DOC_DIR_ID]

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
                rows = [{"id": SUB_DIR_ID, "fileName": "Projects", "isFolder": "Y",
                         "md5": "", "size": 0}, *self.rows.values()]
            elif body["directoryId"] in self.dirs:
                rows = list(self.dirs[body["directoryId"]].values())
            else:
                rows = []
            # Honor pagination the way the real endpoint does, so a >pageSize
            # folder comes back across multiple pages (drives the ls() paging).
            page_no, page_size = body.get("pageNo", 1), body.get("pageSize", 100)
            start = (page_no - 1) * page_size
            return ok({"userFileVOList": rows[start:start + page_size]})

        if path == "/api/file/upload/apply":
            body = json.loads(request.content)
            # The real cloud has no overwrite: a same-name re-push is refused at
            # apply time with E0322 (observed live 2026-07-20). Modeling it here
            # is what makes dispatch's non-idempotency real and --replace
            # (delete-then-push) actually necessary (A4).
            if body["fileName"] in self.dirs.get(body["directoryId"], {}):
                return fail("E0322", "file already exists")
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
            self.dirs.setdefault(body["directoryId"], {})[body["fileName"]] = self.row(
                body["fileName"], body["md5"], body["fileSize"],
                "id-" + body["fileName"])
            return ok()

        if path == "/api/file/delete":
            body = json.loads(request.content)
            for fid in body["idList"]:
                name = fid.removeprefix("id-")
                for rows in self.dirs.values():
                    rows.pop(name, None)
                self.blobs.pop("inner-" + name, None)
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
