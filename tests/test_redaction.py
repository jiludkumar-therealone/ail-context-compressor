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
    "IPV6": ["2001:db8::1", "2001:0db8:85a3:0000:0000:8a2e:0370:7334", "fe80::1ff:fe23:4567:890a",
             "fd12:3456:789a:1::42", "::ffff:192.0.2.128", "2001:db8:0:1:1:1:1:1"],
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

    def test_ipv6_in_context(self):
        for text in ["bind [2001:db8::1]:8080 now", "peer fe80::1ff:fe23:4567:890a%eth0 up",
                     "addr 2001:db8::1.", "(fd12:3456:789a:1::42)"]:
            out, counts = ail_mcp.redact(text)
            self.assertIn("[REDACTED_IPV6]", out, text)
            self.assertNotIn("2001:db8", out)
            self.assertNotIn("fe23", out)
            self.assertNotIn("789a", out)

    def test_key_value_secrets(self):
        pw = "Fake" + "Pass" + "word" + "123"
        cases = [
            f"password={pw}", f"PASSWORD = {pw}", f"db_password: {pw}", f"passwd={pw}",
            f'"password": "{pw}"', f"'secret': '{pw}'", f'client_secret: "{pw}"', f"api_key={pw}",
            f"API-KEY: {pw}", f"apikey = '{pw}'", f'"access_token":"{pw}"', f"auth_token={pw};",
            f"export DB_PASSWORD={pw}", f'password: str = "{pw}"', f"user.password={pw}&next=1",
        ]
        for text in cases:
            out, counts = ail_mcp.redact(text)
            self.assertNotIn(pw, out, text)
            self.assertIn("[REDACTED_SECRET]", out, text)
        out, _ = ail_mcp.redact(f'{{"user": "demo", "password": "{pw}"}}')
        self.assertEqual(out, '{"user": "demo", "password": "[REDACTED_SECRET]"}')

    def test_key_value_secret_in_python_default_is_not_in_sig(self):
        pw = "Fake" + "Pw" + "42"
        code = f'def login(user: str, password: str = "{pw}") -> bool:\n    return True\n'
        sigs = "\n".join(ail_mcp.extract_signatures(code))
        self.assertNotIn(pw, sigs)
        self.assertIn("login(", sigs)

    def test_benign_text_is_untouched(self):
        benign = [
            "x = items[::2]", "std::vector<int> v; Foo::bar()", "a[1::3] and b[10::20]",
            "sha256 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "commit 769608085603d4bf9a46a684e5e13d826b5f4e75", "meet at 12:30:45 today",
            "mac aa:bb:cc:dd:ee:ff", "def login(password: str, secret: bytes = None) -> bool:",
            "password = getpass.getpass()", "secret = os.environ['APP_SECRET']",
            "password: Optional[str] = None", "the password field is required", "secretary=Bob",
            "passwords: list[str]", "if password == expected:",
        ]
        for text in benign:
            out, counts = ail_mcp.redact(text)
            self.assertEqual(out, text, f"false positive: {text!r} -> {out!r}")

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
