"""Template projections use TypeTree identities, never guessed payload offsets."""

import base64
import hashlib
import math

from ..unity.binary import FormatError
from ..unity.typetree import Value, float_text

ABILITY_TYPES = {
    "AbilitySystemData",
    "AbilitySystemForEnemyPartData",
    "AbilitySystemForSoulData",
}
QUERY_NAMES = ("HasAny", "HasAll", "ExceptAny", "ExceptAll")


def wrapped(value):
    return {"value": value, "hex": f"0x{value & 0xFFFFFFFF:08x}"}


def normalize(value: Value, *, condition=False):
    node = value.node
    if value.array:
        return [normalize(item, condition=condition) for item in value.children]
    if node.type in ("managedReference", "managedRefArrayItem"):
        return str(value.data["rid"])
    if node.type == "float":
        return (
            float(float_text(value.data, single=True))
            if math.isfinite(value.data)
            else float_text(value.data)
        )
    if node.type == "double" and not math.isfinite(value.data):
        return float_text(value.data)
    # TypeTree's 0x100 flag distinguishes a serialized boolean from a byte enum.
    if node.type == "UInt8" and node.flags & 0x100:
        if value.data not in (0, 1):
            raise FormatError(f"{node.name}: invalid aligned boolean {value.data}")
        return bool(value.data)
    if not value.children:
        return value.data
    result = {
        item.node.name: normalize(item, condition=condition) for item in value.children
    }
    if node.type.startswith("SerializeFieldDictionary"):
        result = {"keys": result["_keyData"], "values": result["_valueData"]}
        if len(result["keys"]) != len(result["values"]):
            raise FormatError(f"{node.name}: dictionary key/value lengths differ")
    if node.type == "AnimationCurve":
        result = {
            "keys": result["m_Curve"],
            "preInfinity": result["m_PreInfinity"],
            "postInfinity": result["m_PostInfinity"],
            "rotationOrder": result["m_RotationOrder"],
        }
    if (
        condition
        and node.type.startswith("Blackboard")
        and "useBlackboardKey" in result
    ):
        result = {
            "useKey": result["useBlackboardKey"],
            "value": result["value"],
            "key": result["blackboardKey"],
        }
    if condition and node.type == "GameplayTagQuery":
        result = query(result)
    if node.type.startswith("PPtr<"):
        result = {"fileId": result["m_FileID"], "pathId": str(result["m_PathID"])}
    return result


def query(value):
    kind = value["queryType"]
    if kind not in range(len(QUERY_NAMES)):
        raise FormatError(f"unknown gameplay tag query type {kind}")
    return {
        "queryType": {"value": kind, "name": QUERY_NAMES[kind]},
        "tags": [{"tagId": wrapped(tag["tagId"])} for tag in value["tags"]],
    }


def flatten(data, names):
    result = dict(data)
    for name in names:
        if name in result:
            for key, value in result.pop(name).items():
                result[f"{name}.{key}"] = value
    return result


def _fields(fields, *, condition=False):
    return {value.node.name: normalize(value, condition=condition) for value in fields}


def _ability(data):
    result = dict(data)
    ui = result["uiData"] = flatten(
        result["uiData"], ("headBar2DOffset", "heightRange")
    )
    ui["damageTextRelated"] = flatten(
        ui["damageTextRelated"],
        (
            "mainChrDmgTxtSpawnOffset",
            "mainChrDmgTxtMoveSpawnOffset",
            "guardDmgTxtSpawnOffset",
            "guardDmgTxtSpawnAreaSize",
            "immuneTxtSpawnOffset",
            "immuneTxtSpawnAreaSize",
        ),
    )
    return result


class Template:
    def __init__(self, info, file, root, decoder, identity, root_type):
        self.raw = file.raw(info)
        self.root = root
        self.refs = decoder.references
        rid = root.data["data"]["rid"]
        self.root_rid = rid
        self.identity = identity
        root_entry = self.entry(rid, root_type, "Beyond.Gameplay")
        self.fields = root_entry[3]
        self.data = _fields(self.fields)
        if self.data["id"].casefold() != identity.casefold():
            raise FormatError(f"template ID {self.data['id']} != {identity}")
        self.component_rids = [int(value) for value in self.data["componentList"]]
        if len(set(self.component_rids)) != len(self.component_rids):
            raise FormatError("duplicate component RID")
        for rid in self.component_rids:
            self.entry(rid)

    def entry(self, rid, cls=None, namespace=None):
        if rid not in self.refs or rid < 1:
            raise FormatError(f"missing managed reference {rid}")
        entry = self.refs[rid]
        if cls and entry[0] != (cls, namespace, "Gameplay.Beyond"):
            raise FormatError(f"unexpected managed reference type {entry[0]}")
        return entry

    def component(self, classes):
        matches = [
            rid
            for rid in self.component_rids
            if self.entry(rid)[0][0] in classes
            and self.entry(rid)[0][1:] == ("Beyond.Gameplay.Core", "Gameplay.Beyond")
        ]
        if len(matches) > 1:
            raise FormatError(f"ambiguous component {classes}")
        return matches[0] if matches else None

    def describe(self, rid):
        (cls, namespace, assembly), start, end, _ = self.entry(rid)
        return {
            "rid": str(rid),
            "class": cls,
            "namespace": namespace,
            "assembly": assembly,
            "offset": start,
            "length": end - start,
        }

    def bytes(self, start, end):
        return base64.b64encode(self.raw[start:end]).decode("ascii")

    def ability(self):
        rid = self.component(ABILITY_TYPES)
        return (
            (rid, _ability(_fields(self.entry(rid)[3])))
            if rid is not None
            else (None, None)
        )


def character(template):
    t = template
    rid, ability = t.ability()
    if rid is None:
        raise FormatError("character has no ability system")
    data = dict(t.data)
    data["bornTag"] = [tag["tagId"] for tag in data["bornTag"]]
    data["componentList"] = [t.describe(rid) for rid in t.component_rids]
    hurt = t.component({"CharHurtAnimComponentData"})
    if hurt is not None:
        data["hurtAnim"] = _fields(t.entry(hurt)[3])
    # Preserve the existing source format while deriving reference boundaries from schemas.
    references = {}
    pending = []
    for condition in ability["skillDataBundle"]["comboSkillConditions"]:
        pending.extend(
            int(item) for item in condition["comboSkillCheckAction"]["actionData"]
        )
    while pending:
        ref = pending.pop(0)
        if ref <= 0 or str(ref) in references:
            continue
        _, start, end, fields = t.entry(ref)
        decoded = _fields(fields, condition=True)
        references[str(ref)] = {
            **t.describe(ref),
            "decodeStatus": "complete",
            "data": decoded,
            "rawBase64": t.bytes(start, end),
        }
        pending.extend(managed_rids(fields))
    return {
        "format": "character-template-prefix-v1",
        "decodeStatus": "complete",
        "sourceSha256": hashlib.sha256(t.raw).hexdigest(),
        "sourceByteCount": len(t.raw),
        "monoBehaviourName": t.root.data["m_Name"],
        "registryOffset": t.root.child("references").start,
        "root": t.describe(t.root_rid),
        "data": data,
        "abilitySystem": ability,
        "abilitySystemEntry": t.describe(rid),
        "abilitySystemTailOffset": t.entry(rid)[2],
        "abilitySystemTailBase64": "",
        "conditionReferences": references,
    }


def managed_rids(fields):
    for value in fields:
        if value.node.type in ("managedReference", "managedRefArrayItem"):
            rid = value.data["rid"]
            if rid > 0:
                yield rid
        else:
            yield from managed_rids(value.children)


def ability_entity(t):
    data = dict(t.data)
    data["faction"] = data.pop("factionIndex")
    data["bornTag"] = [tag["tagId"] for tag in data["bornTag"]]
    data["surroundingConfig"] = flatten(
        data["surroundingConfig"], ("centerOffset", "normalVector")
    )
    data["gamePlayAbilityEntityFollowMainCharData"] = flatten(
        data["gamePlayAbilityEntityFollowMainCharData"], ("_followOffset",)
    )
    data = flatten(data, ("headBar2DOffset",))
    obstacles = []
    for obstacle in data["navObstacleConfig"]:
        obstacle = flatten(obstacle, ("centerOffset", "rotationOffset"))
        obstacle["shapeRid"] = obstacle.pop("shapeData")
        obstacles.append(obstacle)
    data["navObstacleConfig"] = obstacles
    components, pending = {}, list(managed_rids(t.fields))
    while pending:
        rid = pending.pop(0)
        if str(rid) in components:
            continue
        identity, _, _, fields = t.entry(rid)
        values = _fields(fields)
        if identity[0] in ABILITY_TYPES:
            values = _ability(values)
        elif identity[0] == "AbilityEntityRootComponentData":
            values = flatten(
                values,
                (
                    "mountPointData",
                    "modelParts",
                    "maxStackingCntBB",
                    "durationBB",
                    "maxIgniteNumBB",
                ),
            )
        components[str(rid)] = {"type": f"{identity[1]}.{identity[0]}", "data": values}
        pending.extend(managed_rids(fields))
    ability_rid, ability = t.ability()
    return {
        "prefix": {
            "id": t.identity,
            "template": data,
            "managedReferenceCount": len(t.refs),
            "rootRid": str(t.root_rid),
            "abilitySystem": ability,
            "abilitySystemType": t.entry(ability_rid)[0][0] if ability_rid else None,
        },
        "complete": {"id": t.identity, "template": data, "components": components},
    }


def projectile(t):
    rid = t.component({"ProjectileComponentData"})
    if rid is None:
        raise FormatError("projectile has no projectile component")
    identity, start, end, fields = t.entry(rid)
    data = _fields(fields)
    if data["id"].casefold() != t.identity.casefold():
        raise FormatError("projectile component ID mismatch")
    ability_rid, ability = t.ability()
    if ability_rid is None:
        raise FormatError("projectile has no ability system")
    target = dict(data["targetFilter"])
    for field in ("factionTarget", "targetFactionType", "objectType"):
        target[field] = wrapped(target[field])
    target["tagQuery"] = query(target["tagQuery"])
    # Only callback identity, hit eligibility and blackboards are public here.
    # Motion/collision simulation parameters are not compiler inputs.
    return {
        "$decoded": True,
        "$partial": False,
        "layout": f"{identity[1]}.{identity[0]}",
        "decodeStatus": "complete",
        "offset": start,
        "length": end - start,
        "id": data["id"],
        "factionIndex": t.data["factionIndex"],
        "hitOnReach": data["hitOnReach"],
        "targetFilter": target,
        "colliderShapeData": {
            "shapeType": wrapped(data["colliderShapeData"]["shapeType"])
        },
        "entityBlackboard": ability["entityBlackboard"],
        "abilitySystem": ability,
        "abilitySystemBoundary": {
            "decodeStatus": "complete",
            "offset": t.entry(ability_rid)[1],
            "length": t.entry(ability_rid)[2] - t.entry(ability_rid)[1],
            "nextOffset": t.entry(ability_rid)[2],
            "remainingLength": 0,
            "tailDecodeFailure": None,
        },
    }
