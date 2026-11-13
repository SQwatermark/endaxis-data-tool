from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from .documents import COLLECTIONS, load_json, project


def export(manifest: Path, output: Path) -> dict:
    source = load_json(manifest)
    if (
        source.get("schemaVersion") != 1
        or not isinstance(source.get("version"), str)
        or not source["version"]
    ):
        raise ValueError("Raw manifest requires schemaVersion 1 and version")
    if output.exists():
        raise ValueError("Output already exists; use a new snapshot directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".export-", dir=output.parent) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()
        seen, evidence = set(), []
        for item in source["entries"]:
            collection, identity = item["collection"], item["id"]
            if collection not in COLLECTIONS or not re.fullmatch(
                "[a-z0-9][a-z0-9_]{0,159}", identity
            ):
                raise ValueError("Invalid raw identity")
            if (collection, identity) in seen:
                raise ValueError(f"Duplicate identity: {collection}/{identity}")
            seen.add((collection, identity))
            path = (manifest.parent / item["path"]).resolve()
            if manifest.parent.resolve() not in path.parents:
                raise ValueError("Raw file escapes manifest directory")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["sha256"]:
                raise ValueError(f"Raw file digest mismatch: {identity}")
            value = project(collection, identity, load_json(path))
            target = (
                staging
                / collection
                / (
                    identity
                    + (
                        ".runtime-template.json"
                        if collection == "CharacterData"
                        else ".json"
                    )
                )
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            evidence.append(
                {
                    "collection": collection,
                    "id": identity,
                    "rawSha256": digest,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    **(
                        {"objectSha256": item["objectSha256"]}
                        if "objectSha256" in item
                        else {}
                    ),
                }
            )
        report = {"schemaVersion": 1, "version": source["version"], "entries": evidence}
        (staging / "snapshot.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        staging.rename(output)
    return report
