"""Redaction is on by default. Every value below is invented and assembled at
runtime so secret scanners never see a token-shaped literal in this file."""

import unittest

import ail_mcp

ALNUM = "FAKEfakeTESTtest0123456789" * 3  # invented, low entropy on purpose
FAKES = {
    "GITHUB_TOKEN": ["ghp" + "_" + ALNUM[:36], "github" + "_pat_" + ALNUM + "_" + ALNUM[:20], "gho" + "_" + ALNUM[:36]],
    "API_KEY": ["sk" + "-" + ALNUM[:32], "sk" + "-ant-api03-" + ALNUM[:30], "sk" + "-proj-" + ALNUM[:28]],
    "AWS_KEY": ["AKIA" + "FAKE" + "EXAMPLE0" + "1234"],
    "SLACK_TOKEN": ["xox" + "b-1111-2222-" + ALNUM[:20]],
    "GOOGLE_KEY": ["AIza" + ALNUM[:35]],
    "JWT": ["eyJ" + ALNUM[:12] + "." + ALNUM[:16] + "." + ALNUM[:16]],
    "EMAIL": ["jane.doe@example.com", "ops+alerts@test.example.org"],
    "IPV4": ["10.20.30.40", "10.0.0.1", "100.64.0.1", "100.127.255.254", "192.0.2.10", "203.0.113.77"],
}
KEY_BODY = "MIIEpAIBAAKCAQEA" + ALNUM * 3
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----\n" + KEY_BODY + "\n-----END " + "RSA PRIVATE KEY-----"
OPENSSH_KEY = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n" + KEY_BODY + "\n-----END " + "OPENSSH PRIVATE KEY-----"
ALL_VALUES = [v for vals in FAKES.values() for v in vals]


def leaks(text: str) -> list[str]:
    found = [v for v in ALL_VALUES if v in text]
    if KEY_BODY in text or "PRIVATE KEY" in text:
        found.append("private key block")
    return found


class RedactionTests(unittest.TestCase):
    def test_each_kind_is_redacted(self):
        for kind, values in FAKES.items():
            for value in values:
                out, counts = ail_mcp.redact(f"config value {value} here")
                self.assertNotIn(value, out, kind)
                self.assertIn(f"[REDACTED_{kind}]", out, value)
                self.assertEqual(counts, {kind: 1}, value)

    def test_private_key_blocks(self):
        for block in (PRIVATE_KEY, OPENSSH_KEY, PRIVATE_KEY.split("-----END")[0]):
            out, _ = ail_mcp.redact("key:\n" + block + "\nafter")
            self.assertEqual(leaks(out), [])

    def test_pack_redacts_by_default_in_prose(self):
        text = "\n".join(f"The deploy_service uses {v} for the deploy_service." for v in ALL_VALUES)
        text += "\n" + PRIVATE_KEY
        res = ail_mcp.pack(text)
        self.assertEqual(leaks(res["ail_payload"]), [])
        self.assertEqual(leaks(ail_mcp.hydrate(res["ail_payload"])), [])
        self.assertGreater(sum(res["redactions"].values()), len(ALL_VALUES) - 1)

    def test_pack_redacts_python_defaults_and_logs(self):
        code = f"def connect(host='{FAKES['IPV4'][0]}', key='{FAKES['AWS_KEY'][0][:12]}'):\n    pass\n"
        self.assertEqual(leaks(ail_mcp.pack(code, "client.py")["ail_payload"]), [])
        self.assertNotIn(FAKES["IPV4"][0], "\n".join(ail_mcp.extract_signatures(code)))
        res = ail_mcp.pack("notes", log=[(f"call {FAKES['IPV4'][2]}", f"mail {FAKES['EMAIL'][0]}", "use dns")])
        self.assertEqual(leaks(res["ail_payload"]), [])

    def test_fenced_code_in_chat_is_redacted(self):
        text = f"Here:\n```python\ndef auth(token='{FAKES['GITHUB_TOKEN'][0]}'):\n    pass\n```\n"
        self.assertEqual(leaks(ail_mcp.pack(text)["ail_payload"]), [])

    def test_opt_out_keeps_values(self):
        res = ail_mcp.pack("reach me at jane.doe@example.com", redact_secrets=False)
        self.assertIn("jane.doe@example.com", res["ail_payload"])

    def test_versions_and_plain_numbers_are_not_ips(self):
        out, counts = ail_mcp.redact("python 3.10.12 and release 1.2.3 and 999.1.1.1")
        self.assertEqual(counts, {})


if __name__ == "__main__":
    unittest.main()
