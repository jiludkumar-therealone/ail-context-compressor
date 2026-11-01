import asyncio
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


class CheckpointTests(unittest.TestCase):
    def test_saves_valid_payload_without_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            ail_mcp.save_checkpoint("!AILv1\n@CTX hello", "s.ail", directory=d)
            self.assertEqual((Path(d) / "s.ail").read_text(), "!AILv1\n@CTX hello")
            with self.assertRaises(FileExistsError):
                ail_mcp.save_checkpoint("!AILv1\n@CTX again", "s.ail", directory=d)

    def test_rejects_paths_and_invalid_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["../x.ail", "/tmp/x.ail", "x.txt", ".hidden.ail", "a/b.ail"]:
                with self.assertRaises(ValueError, msg=name):
                    ail_mcp.save_checkpoint("!AILv1", name, directory=d)
            with self.assertRaises(ValueError):
                ail_mcp.save_checkpoint("not ail", "ok.ail", directory=d)


@unittest.skipUnless(HAVE_MCP, "mcp package not installed")
class McpServerTests(unittest.TestCase):
    def test_tools_registered(self):
        tools = asyncio.run(ail_mcp.build_server().list_tools())
        self.assertEqual({t.name for t in tools}, TOOLS)

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
