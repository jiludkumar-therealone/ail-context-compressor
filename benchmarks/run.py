#!/usr/bin/env python3
"""Reproduce the README token benchmarks (tiktoken cl100k_base).

    pip install tiktoken
    python3 benchmarks/run.py

Rows:
- "pack" rows run the automatic encoder (`ail_mcp.pack`) on the raw input.
- "hand-written" rows measure a snapshot an agent writes by hand following
  SKILL.md Mode A. They show what the format allows, not what `pack` produces.
All inputs live in benchmarks/inputs/ and are invented sample text.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "ail-context-compressor" / "scripts" / "ail_mcp.py"
INPUTS = ROOT / "benchmarks" / "inputs"
sys.path.insert(0, str(SCRIPT.parent))

import tiktoken  # noqa: E402  (required: no heuristic fallback for published numbers)

import ail_mcp  # noqa: E402

ENC = tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


SESSION = "3-turn architecture session (`architecture_session.md`)"
SOURCE = "Python source (`ail_mcp.py`, signatures only)"
QUICK = "One-paragraph example (`quick_example.txt`)"
AUTO = "`pack` (automatic)"


def _row(name: str, method: str, raw: str, ail: str) -> str:
    ail_mcp.parse(ail)  # every measured snapshot must be valid AILv1
    r, a = tokens(raw), tokens(ail)
    return f"| {name} | {method} | {r:,} | {a:,} | {round((1 - a / r) * 100, 1)}% |"


def table_rows() -> list[str]:
    """Markdown rows, exactly as they appear in README.md."""
    read = lambda name: (INPUTS / name).read_text(encoding="utf-8")  # noqa: E731
    session, quick, source = read("architecture_session.md"), read("quick_example.txt"), SCRIPT.read_text(encoding="utf-8")
    return [
        _row(SESSION, AUTO, session, ail_mcp.pack(session)["ail_payload"]),
        _row(SESSION, "hand-written (`architecture_session.ail`)", session, read("architecture_session.ail")),
        _row(SOURCE, AUTO, source, ail_mcp.pack(source, "ail_mcp.py")["ail_payload"]),
        _row(QUICK, AUTO, quick, ail_mcp.pack(quick)["ail_payload"]),
        _row(QUICK, "hand-written (`quick_example.ail`)", quick, read("quick_example.ail")),
    ]


def main() -> None:
    print(f"tiktoken {tiktoken.__version__}, cl100k_base\n")
    print("| Workload | Snapshot | Raw tokens | AILv1 tokens | Reduction |")
    print("|---|---|---|---|---|")
    print("\n".join(table_rows()))


if __name__ == "__main__":
    main()
