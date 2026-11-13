import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from unity_fixtures import aligned_string, configuration_bundle

from endaxis_data_tool.decoders.templates import normalize, projectile
from endaxis_data_tool.export import export
from endaxis_data_tool.extract import extract
from endaxis_data_tool.unity.binary import FormatError, Reader
from endaxis_data_tool.unity.bundle import read_bundle
from endaxis_data_tool.unity.compression import lz4
from endaxis_data_tool.unity.serialized_file import SerializedFile
from endaxis_data_tool.unity.serialized_file import TypeNode as N
from endaxis_data_tool.unity.typetree import TypeTreeDecoder, dump_text, float_text


class BinaryAndBlockTests(unittest.TestCase):
    def test_projectile_preserves_complete_ability_system_boundary(self):
        entries = {
            1: (
                ("ProjectileComponentData", "Beyond.Gameplay.Core", "Gameplay.Beyond"),
                20,
                40,
                [],
            ),
            2: (
                ("AbilitySystemData", "Beyond.Gameplay.Core", "Gameplay.Beyond"),
                48,
                80,
                [],
            ),
        }
        template = SimpleNamespace(
            component=lambda _: 1,
            entry=entries.__getitem__,
            ability=lambda: (2, {"entityBlackboard": [], "skillDataBundle": {}}),
            identity="projectile_test",
            data={"factionIndex": 1},
        )
        fields = {
            "id": "projectile_test",
            "hitOnReach": True,
            "targetFilter": {
                "factionTarget": 1,
                "targetFactionType": 0,
                "objectType": 0,
                "tagQuery": {"queryType": 0, "tags": []},
            },
            "colliderShapeData": {"shapeType": 1},
        }
        with patch("endaxis_data_tool.decoders.templates._fields", return_value=fields):
            result = projectile(template)
        self.assertEqual(
            result["abilitySystemBoundary"],
            {
                "decodeStatus": "complete",
                "offset": 48,
                "length": 32,
                "nextOffset": 80,
                "remainingLength": 0,
                "tailDecodeFailure": None,
            },
        )

    def test_bounded_views_reject_overread_and_alignment_outside_payload(self):
        reader = Reader(bytes(16), start=5, length=2)
        with self.assertRaises(FormatError):
            reader.i32()
        with self.assertRaises(FormatError):
            reader.align(4)
        with self.assertRaises(FormatError):
            reader.seek(4)

    def test_lz4_overlap_and_endfield_token_layout(self):
        self.assertEqual(lz4(b"\x32abc\x03\x00", 9), b"abcabcabc")
        self.assertEqual(lz4(b"\x0babc\x00\x03", 9, inverted=True), b"abcabcabc")
        for payload, size in [(b"\x00\0\0", 4), (b"\xf0\xff", 10), (b"\x30abc", 2)]:
            with self.subTest(payload=payload), self.assertRaises(FormatError):
                lz4(payload, size)

    def test_float_dump_uses_roundtrip_float32_without_double_precision_noise(self):
        for value, text in [(0.35, "0.35"), (360, "360"), (0.0001, "0.0001")]:
            decoded = struct.unpack("<f", struct.pack("<f", value))[0]
            self.assertEqual(float_text(decoded, single=True), text)


class TypeTreeTests(unittest.TestCase):
    def test_reference_schema_does_not_read_a_second_registry_inside_payload(self):
        payload = N(
            "Payload",
            "Base",
            children=[
                N("int", "value", 4),
                N(
                    "ManagedReferencesRegistry",
                    "references",
                    children=[N("int", "version", 4)],
                ),
            ],
        )
        root = N(
            "Host",
            "Base",
            children=[N("ReferencedObject", "reference"), N("int", "marker", 4)],
        )
        raw = struct.pack("<q", 42)
        raw += b"".join(
            aligned_string(value) for value in ("Payload", "Test", "TestAssembly")
        )
        raw += struct.pack("<ii", 123, 456)
        decoder = TypeTreeDecoder(
            SimpleNamespace(ref_types={("Payload", "Test", "TestAssembly"): [payload]})
        )
        reader = Reader(raw)
        value = decoder.read(root, reader)
        reader.complete()
        self.assertEqual(value.data["marker"], 456)
        self.assertEqual(value.data["reference"]["data"], {"value": 123})
        self.assertIn("int value = 123", dump_text(value))

    def test_missing_reference_schema_fails_instead_of_skipping_payload(self):
        raw = struct.pack("<q", 42) + b"".join(
            aligned_string(x) for x in ("Absent", "Test", "Assembly")
        )
        with self.assertRaisesRegex(FormatError, "missing managed-reference schema"):
            TypeTreeDecoder(SimpleNamespace(ref_types={})).read(
                N("ReferencedObject", "reference"), Reader(raw)
            )

    def test_boolean_metadata_does_not_turn_byte_enum_into_boolean(self):
        decoder = TypeTreeDecoder(SimpleNamespace(ref_types={}))
        boolean = decoder.read(N("UInt8", "enabled", 1, 0x4100), Reader(b"\1\0\0\0"))
        enum = decoder.read(N("UInt8", "bodyType", 1, 0x4000), Reader(b"\4\0\0\0"))
        self.assertIs(normalize(boolean), True)
        self.assertEqual(normalize(enum), 4)


class ExtractionTests(unittest.TestCase):
    def test_extract_and_publish_configuration_without_native_process(self):
        path_id = 9007199254740993
        data, path = configuration_bundle(path_id)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "bundles"
            source.mkdir()
            (source / "input.ab").write_bytes(data)
            (source / "bundles.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "fixture",
                        "bundles": [
                            {
                                "file": "input.ab",
                                "sha256": hashlib.sha256(data).hexdigest(),
                                "assets": [path],
                            }
                        ],
                    }
                )
            )
            manifest = extract(source, root / "raw", "fixture")
            self.assertEqual(len(manifest["entries"]), 1)
            export(root / "raw/raw-manifest.json", root / "snapshot")
            result = json.loads(
                (root / "snapshot/NativeConfig/skillsetting.json").read_text()
            )
            self.assertEqual(result["pathId"], str(path_id))
            self.assertEqual(result["sourceFile"], "CAB-synthetic")
            self.assertIn("float factor = 0.35", result["text"])
            self.assertEqual(result["consumedByteCount"], result["serializedByteCount"])

    def test_corrupt_object_boundaries_are_rejected(self):
        data, _ = configuration_bundle()
        entry = read_bundle(data)[0]
        for raw in (entry.data[:-1], entry.data[:40]):
            with self.assertRaises(FormatError):
                SerializedFile(entry.name, raw)

    def test_missing_expected_container_does_not_publish(self):
        data, _ = configuration_bundle()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "input.ab").write_bytes(data)
            (root / "bundles.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "version": "fixture",
                        "bundles": [
                            {
                                "file": "input.ab",
                                "sha256": hashlib.sha256(data).hexdigest(),
                                "assets": ["assets/missing.asset"],
                            }
                        ],
                    }
                )
            )
            with self.assertRaisesRegex(FormatError, "not exported"):
                extract(root, root / "out", "fixture")
            self.assertFalse((root / "out").exists())
