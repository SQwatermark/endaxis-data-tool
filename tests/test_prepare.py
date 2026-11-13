import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from endaxis_data_tool.prepare import prepare


class PreparedVfsTests(unittest.TestCase):
    def test_reads_ake_vfs_with_patch_precedence_and_publishes_exact_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key = root / "key"
            key.write_bytes(bytes(32))

            class Entry:
                def __init__(self, name, data):
                    self.name, self.data = name, data

                def read(self, secret, verify=False):
                    self.assert_key = secret
                    if not verify:
                        raise AssertionError("verification disabled")
                    return self.data

            class Vfs:
                def __init__(self, source, secret):
                    pass

                def block(self, kind):
                    return {
                        "BundleManifest": [
                            Entry("Data/Bundles/Windows/manifest.hgmmap", b"manifest")
                        ],
                        "InitialBundle": [
                            Entry("Data/Bundles/Windows/main/a.ab", b"old")
                        ],
                        "Bundle": [Entry("Data/Bundles/Windows/main/a.ab", b"current")],
                    }[kind]

            module = SimpleNamespace(BLOCKS={}, Vfs=Vfs)
            selected = [
                (
                    "assets/beyond/dynamicassets/gamedata/characterdata/data_chr_test.asset",
                    "main/a.ab",
                ),
                (
                    "assets/beyond/dynamicassets/gameplay/globalbuff/buff_test.asset",
                    "main/a.ab",
                ),
                ("assets/unrelated.asset", "missing.ab"),
            ]
            with (
                patch("endaxis_data_tool.prepare.assets", return_value=iter(selected)),
                patch(
                    "endaxis_data_tool.prepare.importlib.import_module",
                    return_value=module,
                ),
            ):
                output = root / "bundles"
                self.assertEqual(prepare(root, root, key, output, "fixture"), 1)
                self.assertEqual(next(output.glob("*.ab")).read_bytes(), b"current")
                report = json.loads((output / "bundles.json").read_text())
                self.assertEqual(len(report["bundles"][0]["assets"]), 2)
                with self.assertRaises(ValueError):
                    prepare(root, root, key, output, "fixture")
