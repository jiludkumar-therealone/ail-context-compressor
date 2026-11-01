# AILv1 (`ail-context-compressor`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compatible](https://img.shields.io/badge/MCP-FastMCP-green.svg)](https://modelcontextprotocol.io)
[![Agent Skills](https://img.shields.io/badge/Agent_Skills-SKILL.md-purple.svg)](https://agentskills.io)

**Agent Intermediate Language (AILv1)** is a deterministic context serialization protocol, Python AST signature extractor, and Model Context Protocol (MCP) server designed for zero-loss state handoffs across **Claude, Gemini, Grok, and local CLI agents**.

When a coding or architecture session approaches the context window limit, `ail-context-compressor` compacts conversation state and source code by **85% to 95%** while preserving entity relationships, function signatures, state mutations, and rejected debugging paths.

## Why AILv1?

* **BPE Tokenizer Aligned:** Eliminates JSON-RPC syntax bloat (quotes, braces, repeated keys) and avoids multi-byte Unicode symbols in favor of single-token ASCII operators (`@`, `$`, `:=`, `->`, `|`, `!`, `^`, `?`, `~`).
* **Sub-Linear Pointer Scaling (`@MEM`):** Defines recurring filenames, services, and concepts once as `$1`, `$2`, `$3` and binds them across the context graph.
* **First-Class Negative Constraints (`@LOG`):** Explicitly logs failed approaches and why they failed (`!sync_ping(timeout) -> ^async_scapy`) so downstream models never repeat dead-end suggestions.
* **Automated AST Code Compression (`@SIG`):** Walks Python AST trees to extract class hierarchies, typed arguments, async modifiers (`~`), and state/IO mutations (`mutates(...)`), stripping 90% of implementation boilerplate.

## Verified Benchmarks (`cl100k_base`)

| Workload | Raw Input Tokens | `!AILv1` Snapshot Tokens | Reduction | Retained Fidelity |
|---|---|---|---|---|
| **Multi-Turn Architecture Session** | 2,840 tokens | **148 tokens** | **94.8%** | 100% of entities, 4 rejected paths, 4 signatures |
| **Python Source (`ail_mcp.py`)** | 1,680 tokens | **212 tokens** | **87.4%** | 16 AST `@SIG` definitions + state mutations |

## Quick Example

**Raw Session Summary (~95 tokens):**
> We are building an automated network scanner service in Python using FastAPI. It runs inside a Docker container on an Ubuntu host and scans local subnets for IP cameras and switches. Earlier, we tried using standard synchronous ping sweeps, but it timed out on large subnets, so we rejected that and switched to asynchronous ARP scanning with Scapy. Next, we need to fix the SQLite database lock issue when writing scan results concurrently.

**Equivalent `!AILv1` State (~32 tokens):**
```text
!AILv1
@MEM $1=NetScanner_App $2=FastAPI_Py $3=Docker_Ubuntu $4=Subnets $5=SQLite_DB
@CTX $1[$2,$3]->scan($4:IPCam,Switch)
@LOG !sync_ping(timeout_large_$4) -> ^async_ARP_Scapy
@NEXT ?fix($5:concurrent_write_lock)
```

## Installation & Usage

### 1. Install as an Agent Skill (Claude Code, Cursor, Gemini)
Copy the skill folder into your global or project skills directory:

```bash
git clone [https://github.com/](https://github.com/)<YOUR_GITHUB_USERNAME>/ail-context-compressor.git
mkdir -p ~/.claude/skills/ail-context-compressor
cp -r ail-context-compressor/SKILL.md ail-context-compressor/scripts ~/.claude/skills/ail-context-compressor/
```

### 2. Run the Standalone CLI
```bash
# Compress a chat log or Python script into an .ail snapshot
python3 scripts/ail_mcp.py pack -f app.py > session.ail

# Extract only AST @SIG lines and state mutations from Python code
python3 scripts/ail_mcp.py sig -f scripts/ail_mcp.py

# Hydrate an .ail snapshot back into expanded text
python3 scripts/ail_mcp.py unpack -f session.ail

# Run the automated verification suite
python3 verify_ail.py
```

### 3. Register as an MCP Server (Claude Desktop / Cursor)
Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ail-context-compressor": {
      "command": "python3",
      "args": ["/absolute/path/to/ail-context-compressor/scripts/ail_mcp.py", "mcp"]
    }
  }
}
```

## Formal EBNF Grammar

```ebnf
ail_document   = "!AILv1" , NEWLINE , { section } ;
section        = mem_sec | ctx_sec | arch_sec | log_sec | sig_sec | next_sec ;

mem_sec        = "@MEM" , { " " , pointer_id , "=" , identifier } , NEWLINE ;
ctx_sec        = "@CTX" , " " , expr_chain , NEWLINE ;
arch_sec       = "@ARCH" , " " , expr_chain , NEWLINE ;
log_sec        = "@LOG" , " " , "!" , identifier , "(" , reason , ")" , " -> " , "^" , expr , NEWLINE ;
sig_sec        = "@SIG" , " " , pointer_id , "|" , [ "~" ] , fn_sig , "->" , type_id , [ "|mutates(" , mut_list , ")" ] , NEWLINE ;
next_sec       = "@NEXT" , { " ?" , action_expr } , NEWLINE ;
```

## License
MIT License
