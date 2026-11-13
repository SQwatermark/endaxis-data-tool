from __future__ import annotations

import json
from pathlib import Path

COLLECTIONS = (
    "CharacterData",
    "AbilityEntityData",
    "ProjectileData",
    "NativeConfig",
    "GlobalBuffData",
    "EnemyData",
    "GameplayTagData",
)


def project(collection: str, identity: str, decoded: dict) -> dict:
    if collection != "AbilityEntityData":
        return decoded
    prefix = decoded["prefix"]
    root = prefix["template"]
    if prefix["id"] != identity or root["id"] != identity:
        raise ValueError("Ability entity identity mismatch")
    mapping = {
        "gameId": "id",
        "name": "name",
        "factionNativeValue": "faction",
        "bornTagIds": "bornTag",
        "lifeTypeNativeValue": "lifeType",
        "durationSeconds": "duration",
        "durationBlackboard": "durationBB",
        "maxDurationForServerSeconds": "maxDurationForServer",
        "maxStackingCount": "maxStackingCnt",
        "maxStackingCountBlackboard": "maxStackingCntBB",
        "delayToRecycleSeconds": "delayToRecycleTime",
        "delayRecyclePerformSeconds": "delayRecyclePerformTime",
        "sendDieEvent": "sendDieEvent",
        "enableBornFadeIn": "enableBornFadeIn",
        "fadeInSeconds": "fadeInTime",
    }
    template = {key: root[value] for key, value in mapping.items()}
    template.update(
        componentCount=len(root["componentList"]),
        managedReferenceCount=prefix["managedReferenceCount"],
        rootRid=int(prefix["rootRid"]),
    )
    ability = prefix["abilitySystem"]
    if ability:
        bundle = ability["skillDataBundle"]
        template.update(
            skillDataBundle={
                "allActiveSkillIds": bundle["allActiveSkillId"],
                "allPassiveSkillIds": bundle["allPassiveSkillId"],
                "enabledPassiveSkillIds": bundle["enabledPassiveSkills"],
            },
            skillRegistration=bundle,
            entityBlackboard=ability["entityBlackboard"],
            abilitySystemType=prefix["abilitySystemType"],
        )
    if "complete" in decoded:
        template["nativeData"] = {"decodeStatus": "complete", **decoded["complete"]}
    else:
        template["nativeData"] = {
            "decodeStatus": "partial",
            "reason": decoded["partialReason"],
        }
        template["skillRegistration"] = decoded["registration"]["skillDataBundle"]
    return template


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))
