import unittest

import ail_mcp


class SignatureTests(unittest.TestCase):
    def test_async_types_and_mutations(self):
        code = (
            "class StateEngine:\n"
            "    async def commit_batch(self, items: list[str], force: bool = False) -> int:\n"
            "        self.cursor_pos = 0\n"
            "        self.journal.append(items)\n"
            "        return len(items)\n"
        )
        self.assertEqual(
            ail_mcp.extract_signatures(code, "$ENG"),
            ["@SIG $ENG|~StateEngine.commit_batch(items:list[str],force:bool=False)->int"
             "|mutates(self.cursor_pos,self.journal.append)"],
        )

    def test_varargs_kwonly_and_inferred_return(self):
        code = "def f(a, *rest, flag=True, **opts):\n    global COUNTER\n    return a\n"
        self.assertEqual(ail_mcp.extract_signatures(code, "m.py"),
                         ["@SIG m.py|f(a,*rest,flag=True,**opts)->Any|mutates(global:COUNTER)"])

    def test_long_defaults_are_dropped_and_nested_functions_qualified(self):
        code = "def outer(x='a-very-long-default-value'):\n    def inner():\n        pass\n"
        self.assertEqual(ail_mcp.extract_signatures(code, "m.py"),
                         ["@SIG m.py|outer(x)->None", "@SIG m.py|outer.inner()->None"])

    def test_invalid_python_returns_empty(self):
        self.assertEqual(ail_mcp.extract_signatures("def broken(:\n"), [])

    def test_sig_lines_parse(self):
        sigs = ail_mcp.extract_signatures("async def get(url: str | None) -> dict:\n    self.cache[url] = 1\n", "net.py")
        doc = ail_mcp.parse("!AILv1\n" + "\n".join(sigs))
        self.assertEqual(doc["sig"], [{"file": "net.py", "signature": "~get(url:str|None)->dict",
                                       "async": True, "mutates": ["self.cache[url]"]}])


if __name__ == "__main__":
    unittest.main()
