from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .documents import COLLECTIONS


class SourceFiles:
    def __init__(
        self,
        json_root: Path,
        table_root: Path,
        supplemental_root: Path,
        version: str,
        image_root: Path | None = None,
    ):
        self.json_root, self.table_root, self.extra = [
            p.resolve(strict=True) for p in (json_root, table_root, supplemental_root)
        ]
        self.version = version
        self.image_root = (
            image_root.resolve(strict=True) if image_root is not None else None
        )
        snapshot = json.loads(
            (self.extra / "snapshot.json").read_text(encoding="utf-8")
        )
        if snapshot["version"] != version:
            raise ValueError("Supplemental snapshot version mismatch")

    def read(self, path: str) -> bytes:
        parts = path.split("/")
        if any(
            not p or p in (".", "..") or any(c in p for c in "\\:%?#\x00")
            for p in parts
        ):
            raise ValueError("Unsafe resource path")
        collection = parts[0]
        root = (
            self.table_root
            if collection == "TableCfg-current"
            else self.extra
            if collection in COLLECTIONS
            else self.json_root
        )
        relative = parts[1:] if collection == "TableCfg-current" else parts
        target = root.joinpath(*relative).resolve()
        if root not in target.parents:
            raise ValueError("Resource escapes root")
        if (
            len(parts) == 2
            and parts[1] == "manifest.json"
            and collection != "TableCfg-current"
        ):
            directory = root / collection
            if not directory.is_dir():
                raise FileNotFoundError(collection)
            return json.dumps(
                [
                    {
                        "contentFile": f"/api/data/{collection}/{p.relative_to(directory).as_posix()}"
                    }
                    for p in sorted(directory.rglob("*.json"))
                    if p.name != "manifest.json"
                ]
            ).encode()
        if target.suffix != ".json":
            raise ValueError("Only JSON resources are served")
        return target.read_bytes()

    def image(self, path: str) -> bytes:
        root = self.image_root
        if root is None:
            raise FileNotFoundError("AKE image exports are not configured")
        if path == "manifest.json":
            return json.dumps(
                [
                    {
                        "path": p.relative_to(root).as_posix(),
                        "contentFile": "/api/images/" + p.relative_to(root).as_posix(),
                    }
                    for p in sorted(root.rglob("*"))
                    if p.is_file()
                    and p.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg")
                ]
            ).encode()
        if any(
            not p or p in (".", "..") or any(c in p for c in "\\:%?#\x00")
            for p in path.split("/")
        ):
            raise ValueError("Unsafe image path")
        target = (root / path).resolve()
        if root not in target.parents or target.suffix.lower() not in (
            ".png",
            ".webp",
            ".jpg",
            ".jpeg",
        ):
            raise ValueError("Invalid image resource")
        return target.read_bytes()


def serve(files: SourceFiles, port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            try:
                if path.startswith("/api/images/"):
                    body = files.image(path[len("/api/images/") :])
                elif path.startswith("/api/data/"):
                    body = files.read(path[len("/api/data/") :])
                else:
                    raise FileNotFoundError(path)
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/octet-stream"
                    if path.startswith("/api/images/")
                    and not path.endswith("manifest.json")
                    else "application/json; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Endaxis-Source", "endaxis-data-tool")
                collection = (
                    path[len("/api/data/") :].split("/")[0]
                    if path.startswith("/api/data/")
                    else ""
                )
                self.send_header(
                    "X-Endaxis-Provider",
                    "endaxis-data-tool"
                    if collection in COLLECTIONS
                    else "ake-data-tool",
                )
                self.send_header("X-Endaxis-Version", files.version)
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_error(404)
            except ValueError as error:
                self.send_error(400, str(error))

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(
            "ENDAXIS_SOURCE_READY "
            + json.dumps({"port": server.server_port, "version": files.version}),
            flush=True,
        )
        server.serve_forever()
