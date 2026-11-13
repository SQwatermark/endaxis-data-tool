"""Prepared input failures must not publish a partially extracted snapshot."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from endaxis_data_tool.extract import extract


class BundleValidationTests(unittest.TestCase):
    def test_rejects_inconsistent_prepared_inputs_without_publishing(self):
        cases = (
            ("other", "input.ab", hashlib.sha256(b"fixture").hexdigest(), "version"),
            ("fixture", "input.ab", "00", "digest"),
            ("fixture", "../input.ab", "00", "direct child"),
            ("fixture", "missing.ab", "00", "Missing or duplicate"),
        )
        for version, filename, digest, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "source"
                source.mkdir()
                (source / "input.ab").write_bytes(b"fixture")
                (source / "bundles.json").write_text(
                    json.dumps(
                        {
                            "schemaVersion": 1,
                            "version": version,
                            "bundles": [
                                {"file": filename, "sha256": digest, "assets": []}
                            ],
                        }
                    )
                )
                output = root / "output"
                with self.assertRaisesRegex(ValueError, message):
                    extract(source, output, "fixture")
                self.assertFalse(output.exists())
                self.assertEqual(list(root.glob(".extract-*")), [])
