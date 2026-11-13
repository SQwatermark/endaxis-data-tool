import json
import tempfile
import unittest
from pathlib import Path

from endaxis_data_tool.export import export
from endaxis_data_tool.server import SourceFiles


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.json, self.tables, self.extra = [
            self.root / n for n in ("json", "tables", "extra")
        ]
        for p in (self.json, self.tables, self.extra):
            p.mkdir()
        (self.extra / "snapshot.json").write_text(json.dumps({"version": "1.6.4"}))
        self.files = SourceFiles(self.json, self.tables, self.extra, "1.6.4")

    def test_standard_data_and_extra_are_owned_by_different_roots(self):
        (self.json / "SkillData").mkdir()
        (self.json / "SkillData" / "a.json").write_text('{"a":1}')
        (self.extra / "CharacterData").mkdir()
        (self.extra / "CharacterData" / "chr_a.runtime-template.json").write_text(
            '{"id":"chr_a"}'
        )
        self.assertEqual(json.loads(self.files.read("SkillData/a.json")), {"a": 1})
        self.assertEqual(
            json.loads(self.files.read("CharacterData/manifest.json")),
            [{"contentFile": "/api/data/CharacterData/chr_a.runtime-template.json"}],
        )
        self.assertEqual(
            json.loads(self.files.read("SkillData/manifest.json")),
            [{"contentFile": "/api/data/SkillData/a.json"}],
        )

    def test_invalid_paths_and_wrong_versions_are_rejected(self):
        for path in (
            "../snapshot.json",
            "SkillData/a:secret.json",
            "SkillData/../snapshot.json",
        ):
            with self.assertRaises(ValueError):
                self.files.read(path)
        with self.assertRaises(ValueError):
            SourceFiles(self.json, self.tables, self.extra, "other")

    def test_failed_export_does_not_publish_partial_snapshot(self):
        raw = self.root / "raw.bin"
        raw.write_bytes(b"data")
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "version": "1.6.4",
                    "entries": [
                        {
                            "collection": "CharacterData",
                            "id": "chr_a",
                            "path": "raw.bin",
                            "sha256": "wrong",
                        }
                    ],
                }
            )
        )
        output = self.root / "published"
        with self.assertRaises(ValueError):
            export(manifest, output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.glob(".export-*")), [])
