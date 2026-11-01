import asyncio
import contextlib
import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path

import ail_mcp
from tests import SCRIPT

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False

TOOLS = {"ail_compress_text", "ail_extract_code_sigs", "ail_hydrate_state", "ail_save_checkpoint"}


@contextlib.contextmanager
def in_temp_dir():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        try:
            yield Path(d).resolve()
        finally:
            os.chdir(old)


class CheckpointTests(unittest.TestCase):
    def test_saves_valid_payload_in_cwd_without_overwrite(self):
        with in_temp_dir() as d:
            ail_mcp.save_checkpoint("!AILv1\n@CTX hello", "s.ail")
            self.assertEqual((d / "s.ail").read_text(), "!AILv1\n@CTX hello")
            with self.assertRaises(FileExistsError):
                ail_mcp.save_checkpoint("!AILv1\n@CTX again", "s.ail")

    def test_caller_cannot_choose_directory(self):
        params = inspect.signature(ail_mcp.save_checkpoint).parameters
        self.assertEqual(list(params), ["ail_block", "filename"])

    def test_rejects_traversal_separators_and_bad_names(self):
        bad = ["../x.ail", "..\\x.ail", "/tmp/x.ail", "a/b.ail", "a\\b.ail", "x.txt", ".hidden.ail",
               "..ail", "...ail", "a..b.ail", "x.ail\x00", "x.ail/", "", "~/x.ail", "C:x.ail"]
        with in_temp_dir() as d:
            for name in bad:
                with self.assertRaises(ValueError, msg=name):
                    ail_mcp.save_checkpoint("!AILv1", name)
            self.assertEqual(list(d.iterdir()), [])
            with self.assertRaises(ValueError):
                ail_mcp.save_checkpoint("not ail", "ok.ail")

    def test_symlink_cannot_escape_cwd(self):
        with in_temp_dir() as d, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "escaped.ail"
            (d / "link.ail").symlink_to(target)  # dangling link pointing outside cwd
            with self.assertRaises((ValueError, OSError)):
                ail_mcp.save_checkpoint("!AILv1\n@CTX x", "link.ail")
            self.assertFalse(target.exists())
            existing = Path(outside) / "existing.ail"
            existing.write_text("original")
            (d / "link2.ail").symlink_to(existing)
            with self.assertRaises((ValueError, OSError)):
                ail_mcp.save_checkpoint("!AILv1\n@CTX x", "link2.ail")
            self.assertEqual(existing.read_text(), "original")


@unittest.skipUnless(HAVE_MCP, "mcp package not installed")
class McpServerTests(unittest.TestCase):
    def test_tools_registered(self):
        tools = {t.name: t for t in asyncio.run(ail_mcp.build_server().list_tools())}
        self.assertEqual(set(tools), TOOLS)
        save = tools["ail_save_checkpoint"]
        schema = save.input_schema if hasattr(save, "input_schema") else save.inputSchema  # mcp 2.x / 1.x
        save_params = schema["properties"]
        self.assertEqual(set(save_params), {"ail_block", "filename"})

    def test_stdio_round_trip(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def run():
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT), "mcp"])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    packed = await session.call_tool("ail_compress_text", {
                        "text": "The cache_layer feeds the cache_layer stats to the cache_layer owner at ops@example.com",
                        "rejected_paths": ["lru_only|cold_starts|warm_preload"],
                    })
                    payload = packed.content[0].text
                    hydrated = await session.call_tool("ail_hydrate_state", {"ail_block": payload})
                    return names, payload, hydrated.content[0].text

        names, payload, hydrated = asyncio.run(run())
        self.assertEqual(names, TOOLS)
        self.assertIn("@LOG !lru_only(cold_starts) -> ^warm_preload", payload)
        self.assertNotIn("ops@example.com", payload)
        self.assertIn("cache_layer", hydrated)


if __name__ == "__main__":
    unittest.main()
