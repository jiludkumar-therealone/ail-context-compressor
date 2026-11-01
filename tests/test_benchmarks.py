import importlib.util
import unittest

from tests import ROOT

HAVE_TIKTOKEN = importlib.util.find_spec("tiktoken") is not None


@unittest.skipUnless(HAVE_TIKTOKEN, "tiktoken not installed")
class ReadmeBenchmarkTests(unittest.TestCase):
    def test_readme_table_matches_measurement(self):
        spec = importlib.util.spec_from_file_location("bench_run", ROOT / "benchmarks" / "run.py")
        bench = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bench)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for row in bench.table_rows():
            self.assertIn(row, readme, "README benchmark row is stale; rerun python3 benchmarks/run.py")


if __name__ == "__main__":
    unittest.main()
