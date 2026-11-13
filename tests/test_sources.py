import json
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

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

    def test_service_reports_bound_port_and_serves_versioned_inputs(self):
        (self.tables / "CharacterTable.json").write_text('{"fixture":true}')
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "endaxis_data_tool",
                "serve",
                "--port",
                "0",
                "--json-root",
                str(self.json),
                "--table-root",
                str(self.tables),
                "--supplemental-root",
                str(self.extra),
                "--version",
                "1.6.4",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        ready = queue.Queue()
        reader = threading.Thread(
            target=lambda: ready.put(process.stdout.readline()), daemon=True
        )
        reader.start()
        try:
            line = ready.get(timeout=10)
            self.assertTrue(line.startswith("ENDAXIS_SOURCE_READY "), line)
            address = json.loads(line.removeprefix("ENDAXIS_SOURCE_READY "))
            self.assertEqual(address["version"], "1.6.4")
            self.assertGreater(address["port"], 0)
            with urlopen(
                f"http://127.0.0.1:{address['port']}/api/data/TableCfg-current/CharacterTable.json",
                timeout=5,
            ) as response:
                self.assertEqual(json.load(response), {"fixture": True})
                self.assertEqual(response.headers["X-Endaxis-Version"], "1.6.4")
                self.assertEqual(
                    response.headers["X-Endaxis-Provider"], "ake-data-tool"
                )
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            reader.join(timeout=5)
            process.stdout.close()
            process.stderr.close()

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
