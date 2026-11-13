"""Materialize selected bundles through AKE Data Tool's VFS reader."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from .manifest import assets

ROOT = "assets/beyond/dynamicassets/gamedata/"
CONFIGS = {
    "skillsetting",
    "timedilationconfig",
    "hitstopconfig",
    "battlecommandmappingconfig",
    "gameplaymiscsetting",
    "movementsetting_default",
    "gameplaytagconfigset",
}


def wanted(path: str) -> bool:
    return (
        any(
            path.startswith(ROOT + part + "/data_")
            for part in ("characterdata", "abilityentity", "projectile", "enemydata")
        )
        or (path.startswith(ROOT + "gameplayconfig/") and Path(path).stem in CONFIGS)
        or path.startswith(ROOT + "gameplayconfig/gameplaytagconfig/")
        or path.startswith("assets/beyond/dynamicassets/gameplay/globalbuff/")
    ) and path.endswith(".asset")


def prepare(
    ake_tool_root: Path,
    vfs_root: Path,
    key_file: Path | None,
    output: Path,
    version: str,
    runtime_root: Path | None = None,
):
    if output.exists():
        raise ValueError("Output already exists")
    if not version:
        raise ValueError("Version is required")
    if key_file is not None:
        raw_key = key_file.read_bytes()
        key = (
            raw_key
            if len(raw_key) == 32
            else base64.b64decode(raw_key.strip(), validate=True)
        )
    elif runtime_root is not None:
        with tempfile.TemporaryDirectory(prefix="endaxis-key-host-") as scratch:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "endaxis_data_tool.key_host",
                    str(ake_tool_root.resolve()),
                    str(runtime_root.resolve()),
                    scratch,
                ],
                capture_output=True,
                text=True,
                encoding="utf8",
                timeout=120,
                check=True,
            )
            keys = [
                line.removeprefix("ENDAXIS_KEY ")
                for line in result.stdout.splitlines()
                if line.startswith("ENDAXIS_KEY ")
            ]
            if len(keys) != 1:
                raise ValueError("Native host did not return one VFS key")
            key = base64.b64decode(keys[0], validate=True)
    else:
        raise ValueError("A runtime directory or VFS key file is required")
    if len(key) != 32:
        raise ValueError("VFS key must contain 32 bytes")
    # Reuse the external checkout's VFS reader without copying its implementation.
    sys.path.insert(0, str(ake_tool_root.resolve(strict=True)))
    module = importlib.import_module("ake_tool.json_host.vfs")
    module.BLOCKS.update(
        Bundle="7064D8E2", InitialBundle="0CE8FA57", BundleManifest="1CDDBF1F"
    )
    vfs = module.Vfs(vfs_root, key)
    manifests = [
        entry
        for entry in vfs.block("BundleManifest")
        if Path(entry.name).name.lower() == "manifest.hgmmap"
    ]
    if len(manifests) != 1:
        raise ValueError(
            f"Expected one effective manifest.hgmmap, found {len(manifests)}"
        )
    manifest_bytes = manifests[0].read(key, verify=True)
    selection = {}
    for path, bundle in assets(manifest_bytes):
        if wanted(path):
            selection.setdefault(bundle, []).append(path)
    if not selection:
        raise ValueError("No requested data assets in manifest")
    by_name = {}
    # Initial bundles provide a base; Bundle contains the current overrides.
    for kind in ("InitialBundle", "Bundle"):
        for entry in vfs.block(kind):
            by_name[entry.name.casefold()] = entry
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bundles-", dir=output.parent) as temp:
        staging = Path(temp) / "snapshot"
        staging.mkdir()
        records = []
        for name, paths in sorted(selection.items()):
            entry = by_name.get(("Data/Bundles/Windows/" + name).casefold())
            if entry is None:
                raise FileNotFoundError(f"Bundle is absent from prepared VFS: {name}")
            payload = entry.read(key, verify=True)
            digest = hashlib.sha256(payload).hexdigest()
            destination = staging / (hashlib.sha256(name.encode()).hexdigest() + ".ab")
            destination.write_bytes(payload)
            records.append(
                {
                    "name": name,
                    "file": destination.name,
                    "sha256": digest,
                    "assets": sorted(paths),
                }
            )
        (staging / "bundles.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "version": version,
                    "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "bundles": records,
                },
                indent=2,
            ),
            encoding="utf8",
        )
        staging.rename(output)
    return len(records)
