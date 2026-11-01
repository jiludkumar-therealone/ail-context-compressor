"""Checks for the release zip built by scripts/build_release.py."""
import codecs
import hashlib
import importlib.util
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

import ail_mcp
from tests import ROOT

SKILL = "skills/ail-context-compressor"
ALLOWED = [
    f"{SKILL}/LICENSE",
    f"{SKILL}/README.md",
    f"{SKILL}/SECURITY.md",
    f"{SKILL}/SKILL.md",
    f"{SKILL}/mcp.example.json",
    f"{SKILL}/scripts/ail_mcp.py",
]
# Names that must never ship. Stored as rot13 so this file does not trip a plain
# text scan of the repository for the same words.
BANNED = [codecs.decode(w, "rot13") for w in (
    "bhgcbfg", "uhyy", "syrrg", "oyh-fgnef", "bevba", "ncbyyb", "ihypna", "qnl gb qnl", "q2q", "pybhqsyner",
)]
BANNED_RE = re.compile(r"(?i)\b(?:" + "|".join(re.escape(w) for w in BANNED) + r")\b")
# The same credential patterns the encoder redacts. Email is left out because
# a security contact address is expected in SECURITY.md.
SECRET_PATTERNS = [p for kind, p in ail_mcp.REDACTION_PATTERNS if kind != "EMAIL"]


def load_builder():
    spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseZipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = load_builder()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.zip_path, cls.digest = cls.builder.build(Path(cls.tmp.name) / "a")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_version_is_1_0_0_and_named_in_zip(self):
        self.assertEqual(self.builder.version(), "1.0.0")
        self.assertEqual(self.zip_path.name, "ail-context-compressor-v1.0.0.zip")

    def test_build_is_deterministic(self):
        again, digest = self.builder.build(Path(self.tmp.name) / "b")
        self.assertEqual(digest, self.digest)
        self.assertEqual(again.read_bytes(), self.zip_path.read_bytes())

    def test_sha256_file_matches(self):
        line = (self.zip_path.parent / (self.zip_path.name + ".sha256")).read_text(encoding="ascii")
        self.assertEqual(line, f"{hashlib.sha256(self.zip_path.read_bytes()).hexdigest()}  {self.zip_path.name}\n")

    def test_file_list_is_the_allowlist(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            infos = zf.infolist()
        self.assertEqual([i.filename for i in infos], ALLOWED)
        for info in infos:
            self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
            self.assertEqual(info.external_attr >> 16, 0o100644)

    def test_every_tracked_skill_file_is_shipped(self):
        # A new file in the skill folder must be added to the build (or deliberately left out here).
        try:
            out = subprocess.run(["git", "ls-files", SKILL], cwd=ROOT, capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git not available")
        tracked = sorted(out.stdout.split())
        shipped = sorted(n for n in ALLOWED if (ROOT / n).exists())
        self.assertEqual(tracked, shipped)

    def test_no_secrets_or_banned_words(self):
        with zipfile.ZipFile(self.zip_path) as zf:
            for name in zf.namelist():
                text = zf.read(name).decode("utf-8")
                self.assertIsNone(BANNED_RE.search(text), name)
                self.assertIsNone(BANNED_RE.search(name), name)
                for pattern in SECRET_PATTERNS:
                    self.assertIsNone(pattern.search(text), f"{name}: {pattern.pattern}")

    def test_banned_pattern_catches_each_word(self):
        for word in BANNED:
            self.assertTrue(BANNED_RE.search(f"x {word.title()} y"), word)


if __name__ == "__main__":
    unittest.main()
