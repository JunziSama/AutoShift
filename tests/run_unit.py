import json
import sys
from pathlib import Path
import unittest
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
data = {"tests_run": result.testsRun, "success": result.wasSuccessful(),
        "failures": len(result.failures), "errors": len(result.errors)}
(root / ".test-data/unit-results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
raise SystemExit(0 if result.wasSuccessful() else 1)
