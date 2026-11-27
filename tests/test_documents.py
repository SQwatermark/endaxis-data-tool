import unittest

from endaxis_data_tool.documents import project


class TemplateDocumentTests(unittest.TestCase):
    def test_entity_document_exposes_template_fields_to_compiler(self):
        root = dict.fromkeys(
            (
                "name",
                "faction",
                "bornTag",
                "lifeType",
                "duration",
                "durationBB",
                "maxDurationForServer",
                "maxStackingCnt",
                "maxStackingCntBB",
                "delayToRecycleTime",
                "delayRecyclePerformTime",
                "sendDieEvent",
                "enableBornFadeIn",
                "fadeInTime",
            ),
            0,
        )
        root.update(id="entity_Test", componentList=[])
        decoded = {
            "prefix": {
                "id": "entity_test",
                "template": root,
                "managedReferenceCount": 1,
                "rootRid": "42",
                "abilitySystem": None,
            },
            "complete": {"id": "entity_test", "template": root, "components": {}},
        }
        document = project("AbilityEntityData", "entity_test", decoded)
        self.assertEqual(document["gameId"], "entity_test")
        self.assertEqual(document["nativeData"]["template"]["id"], "entity_Test")
        self.assertEqual(document["rootRid"], 42)
        self.assertEqual(document["nativeData"]["decodeStatus"], "complete")
        self.assertNotIn("abilityEntityTemplateData", document)
        with self.assertRaises(ValueError):
            project("AbilityEntityData", "other_entity", decoded)
