"""Extract selected configuration objects through the Python resource reader."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import tempfile
from pathlib import Path

from .decoders.templates import Template, ability_entity, character, projectile
from .documents import load_json
from .prepare import CONFIGS, ROOT
from .unity.binary import FormatError
from .unity.bundle import read_bundle
from .unity.serialized_file import SerializedFile
from .unity.typetree import TypeTreeDecoder, dump_text


def _selection(path):
    name = Path(path).stem
    if not path.endswith(".asset"):
        return None
    if (
        path.startswith(ROOT + "gameplayconfig/gameplaytagconfig/")
        or name == "gameplaytagconfigset"
    ):
        return "GameplayTagData", name
    if path.startswith(ROOT + "gameplayconfig/") and name in CONFIGS:
        return "NativeConfig", name
    if path.startswith("assets/beyond/dynamicassets/gameplay/globalbuff/"):
        return "GlobalBuffData", name
    for folder, collection in (
        ("characterdata", "CharacterData"),
        ("abilityentity", "AbilityEntityData"),
        ("enemydata", "EnemyData"),
        ("projectile", "ProjectileData"),
    ):
        if path.startswith(ROOT + folder + "/data_"):
            return collection, name[5:]
    return None


def validate_bundles(input, version, files):
    manifest = input / "bundles.json"
    if not manifest.exists():
        return None
    source = load_json(manifest)
    if source.get("schemaVersion") != 1 or source.get("version") != version:
        raise FormatError("Bundle manifest version mismatch")
    remaining, expected = set(files), set()
    for item in source["bundles"]:
        name = item["file"]
        if not name or Path(name).name != name or any(char in name for char in "\\/:"):
            raise FormatError("Bundle file must be a direct child")
        file = input / name
        if file not in remaining:
            raise FormatError(f"Missing or duplicate bundle {name}")
        remaining.remove(file)
        if hashlib.sha256(file.read_bytes()).hexdigest() != item["sha256"].lower():
            raise FormatError(f"Bundle digest mismatch: {name}")
        expected.update(path.lower() for path in item["assets"])
    if remaining:
        raise FormatError("Unlisted bundles found in prepared input")
    return expected


def configuration_objects(data):
    files = {}
    for entry in read_bundle(data):
        if entry.flags & 4:
            file = SerializedFile(entry.name, entry.data)
            if entry.name in files:
                raise FormatError(f"duplicate serialized file {entry.name}")
            files[entry.name] = file

    def resolve(owner, pointer):
        path_id, file_id = pointer["m_PathID"], pointer["m_FileID"]
        if path_id == 0:
            return None
        if file_id < 0 or file_id > len(owner.externals):
            raise FormatError(f"invalid external file ID {file_id}")
        target = owner if file_id == 0 else files.get(owner.externals[file_id - 1])
        if target is None:
            return None
        info = target.objects.get(path_id)
        if info is None:
            raise FormatError(f"missing object {target.name}:{path_id}")
        return target, info

    for owner in files.values():
        for info in owner.objects.values():
            if owner.types[info.type_index].class_id != 142:
                continue
            bundle = TypeTreeDecoder(owner).decode(info).data
            preload = bundle["m_PreloadTable"]
            for container in bundle["m_Container"]:
                path, asset = container["first"].lower(), container["second"]
                selection = _selection(path)
                if selection is None:
                    continue
                start, size = asset["preloadIndex"], asset["preloadSize"]
                if start < 0 or size < 0 or start + size > len(preload):
                    raise FormatError(f"invalid preload range for {path}")
                candidates = []
                for pointer in preload[start : start + size]:
                    target = resolve(owner, pointer)
                    if target and target[0].types[target[1].type_index].class_id == 114:
                        candidates.append(target)
                if len(candidates) != 1:
                    raise FormatError(
                        f"expected one MonoBehaviour for {path}, found {len(candidates)}"
                    )
                file, obj = candidates[0]
                if resolve(owner, asset["asset"]) != (file, obj):
                    raise FormatError(f"container/preload identity mismatch for {path}")
                decoder = TypeTreeDecoder(file)
                value = decoder.decode(obj)
                collection, identity = selection
                if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,159}", identity):
                    raise FormatError(f"invalid configuration identity {identity!r}")
                if collection in ("NativeConfig", "GlobalBuffData", "GameplayTagData"):
                    result = {
                        "asset": {"Name": identity, "Container": path},
                        "text": dump_text(value),
                        "sourceFile": file.name,
                        "pathId": str(obj.path_id),
                        "dependencies": file.externals,
                        "consumedByteCount": value.end,
                        "serializedByteCount": obj.size,
                    }
                elif collection == "EnemyData":
                    result = {
                        "id": identity,
                        "container": path,
                        "rawBase64": base64.b64encode(file.raw(obj)).decode("ascii"),
                    }
                else:
                    root_types = {
                        "CharacterData": "CharacterTemplateData",
                        "AbilityEntityData": "AbilityEntityTemplateData",
                        "ProjectileData": "ProjectileTemplateData",
                    }
                    template = Template(
                        obj, file, value, decoder, identity, root_types[collection]
                    )
                    result = {
                        "CharacterData": character,
                        "AbilityEntityData": ability_entity,
                        "ProjectileData": projectile,
                    }[collection](template)
                source = {
                    "objectSha256": hashlib.sha256(file.raw(obj)).hexdigest(),
                    "objectByteCount": obj.size,
                    "sourceFile": file.name,
                    "pathId": str(obj.path_id),
                }
                yield collection, identity, path, result, source


def extract(input: Path, output: Path, version: str):
    input = input.resolve(strict=True)
    if not version:
        raise ValueError("Version is required")
    if output.exists():
        raise ValueError("Output already exists")
    files = sorted(input.rglob("*.ab"))
    expected = validate_bundles(input, version, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    seen, exported, entries = set(), set(), []
    with tempfile.TemporaryDirectory(
        prefix=".extract-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "objects"
        staging.mkdir()
        for file in files:
            for collection, identity, container, value, source in configuration_objects(
                file.read_bytes()
            ):
                key = (collection, identity)
                if key in seen:
                    raise FormatError(f"duplicate asset {collection}/{identity}")
                seen.add(key)
                exported.add(container)
                target = staging / collection / (identity + ".json")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
                    encoding="utf-8",
                )
                entries.append(
                    {
                        "collection": collection,
                        "id": identity,
                        "path": target.relative_to(staging).as_posix(),
                        "container": container,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        **source,
                    }
                )
        if not entries:
            raise FormatError("No matching configuration assets found")
        if expected is not None and not expected.issubset(exported):
            raise FormatError(
                "Requested assets were not exported: "
                + ", ".join(sorted(expected - exported))
            )
        manifest = {"schemaVersion": 1, "version": version, "entries": entries}
        (staging / "raw-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        staging.rename(output)
    return manifest
