import json
import importlib.util
import unittest
from pathlib import Path
from src.domain import load_domain, load_workbench

class DomainTest(unittest.TestCase):
    def test_fixture_matches_domain(self):
        value = load_domain(Path("fixtures/domain.json"))
        self.assertEqual(value["domain"], "medical-market-access")
        self.assertGreaterEqual(len(value["constraints"]), 2)

    def test_fixture_passes_workbench_validation(self):
        value = load_workbench(Path("fixtures/domain.json"))
        self.assertEqual(value["version"], 2)


class ContractTest(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("jsonschema"),
                         "未安装 jsonschema 时跳过契约校验")
    def test_fixture_matches_json_schema(self):
        import jsonschema
        schema = json.loads(Path("contracts/domain.schema.json").read_text(encoding="utf-8"))
        data = json.loads(Path("fixtures/domain.json").read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)

if __name__ == "__main__":
    unittest.main()
