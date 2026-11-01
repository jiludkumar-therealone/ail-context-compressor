# AILv1 (`ail-context-compressor`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**Agent Intermediate Language (AILv1)** is a line-oriented text format for handing session state between models and agents, plus a small Python tool that writes and reads it: an encoder, a parse-only decoder, a Python `ast` signature extractor, a CLI, an MCP server, and an Agent Skill (`SKILL.md`).

A snapshot keeps what a summary usually drops: recurring entities (`@MEM` pointers), data flow (`@CTX`/`@ARCH`), rejected approaches and why they failed (`@LOG`), code signatures with state mutations (`@SIG`), and open tasks (`@NEXT`).

```text
!AILv1
@MEM $1=recipe_api $2=MinIO $3=Celery_Redis
@ARCH $1[FastAPI|Postgres] := upload->$2:originals->$3:make_thumbnails->$2:thumbs
@LOG !FastAPI_BackgroundTasks(lost_40_jobs_on_redeploy) -> ^$3_acks_late
@SIG worker.py|make_thumbnails(photo_id:int,key:str)->list[str]|mutates(storage.put_object_bytes)
@NEXT ?per_user_upload_rate_limit
```

> **Security: decoded content is data, not instructions.** A payload can carry text written to steer a model (fake `@NEXT` tasks, "ignore previous instructions"). The decoder only parses; it never evaluates anything. Do not let an agent act on a snapshot from someone else without confirming with its user. See [SECURITY.md](SECURITY.md).

## Format

| Section | Meaning | Example |
|---|---|---|
| `!AILv1` | header, must be the first line | `!AILv1` |
| `@MEM` | pointer dictionary | `@MEM $1=Auth_Service $2=db.py` |
| `@CTX`, `@ARCH` | context, topology, data flow | `@ARCH $1 := $2 \| $3` |
| `@LOG` | negative constraint: rejected path, reason, replacement | `@LOG !sync_ping(timeout) -> ^async_arp` |
| `@SIG` | code signature: file, `~` for async, args, return, mutations | `@SIG $2\|~Repo.save(row:dict)->int\|mutates(self.rows)` |
| `@NEXT` | open tasks | `@NEXT ?add_rate_limit ?write_tests` |

Operators: `$N` pointer, `:=` defined as, `->` flow or resolution, `|` slot separator, `!` rejected, `^` locked replacement, `~` async, `?` open task. Lines starting with `#` are comments.

```ebnf
ail_document = "!AILv1" , NEWLINE , { section } ;
section      = mem_sec | ctx_sec | arch_sec | log_sec | sig_sec | next_sec ;
mem_sec      = "@MEM" , { " " , pointer_id , "=" , identifier } , NEWLINE ;
ctx_sec      = "@CTX" , " " , expr_chain , NEWLINE ;
arch_sec     = "@ARCH" , " " , expr_chain , NEWLINE ;
log_sec      = "@LOG" , " " , "!" , identifier , "(" , reason , ")" , " -> " , "^" , expr , NEWLINE ;
sig_sec      = "@SIG" , " " , file_ref , "|" , [ "~" ] , fn_sig , "->" , type_id , [ "|mutates(" , mut_list , ")" ] , NEWLINE ;
next_sec     = "@NEXT" , { " ?" , action_expr } , NEWLINE ;
expr_chain   = expr , { ( "->" | "|" | ":=" ) , expr } ;
pointer_id   = "$" , DIGIT , { DIGIT } ;
identifier   = ( LETTER | DIGIT | "_" | "." | "/" | ":" | "-" )+ ;
```

## What the tool does

- **Encoder (`pack`)**: redacts secrets first (on by default), turns a Python file into `@SIG` lines, turns fenced Python blocks in a chat log into `@SIG` lines plus a `[CodeBlock_N]` marker, keeps every other non-blank line as `@CTX`, and replaces recurring terms with `$N` pointers when that saves tokens. `@LOG` and `@NEXT` entries are passed in explicitly (`--log`, `--next`); the encoder does not guess which approaches were rejected.
- **Decoder (`parse`, `hydrate`)**: validates the header and every section, resolves pointers in a single pass, leaves undefined `$N` untouched, and caps input and output size. Prose round-trips exactly (minus blank lines and surrounding whitespace).
- **`@SIG` extractor**: Python `ast` only. Qualified names (`Class.method`, `outer.inner`), typed args, short defaults, `*args`/`**kwargs`, async (`~`), return type (annotated, or `Any`/`None` inferred), and up to five mutations (attribute/subscript assignment, `global`/`nonlocal`, calls such as `.append`, `.write_text`, `.commit`).
- **Redaction**: GitHub tokens, `sk-` API keys, AWS key IDs, Slack and Google keys, JWTs, bearer tokens, private key blocks, `password=`/`secret:`/`"api_key": "..."` style credentials, emails, IPv6, and all IPv4 addresses (including `10.0.0.0/8` and `100.64.0.0/10`). Full scope and limits in [SECURITY.md](SECURITY.md).

## Benchmarks (`cl100k_base`)

Measured with `python3 benchmarks/run.py` (tiktoken 0.14.0). All inputs are in [`benchmarks/inputs/`](benchmarks/inputs/) and are invented sample text.

| Workload | Snapshot | Raw tokens | AILv1 tokens | Reduction |
|---|---|---|---|---|
| 3-turn architecture session (`architecture_session.md`) | `pack` (automatic) | 1,879 | 1,435 | 23.6% |
| 3-turn architecture session (`architecture_session.md`) | hand-written (`architecture_session.ail`) | 1,879 | 385 | 79.5% |
| Python source (`ail_mcp.py`, signatures only) | `pack` (automatic) | 5,895 | 757 | 87.2% |
| One-paragraph example (`quick_example.txt`) | `pack` (automatic) | 85 | 98 | -15.3% |
| One-paragraph example (`quick_example.txt`) | hand-written (`quick_example.ail`) | 85 | 87 | -2.4% |

What the numbers say:

- On Python source the automatic encoder keeps only signatures and mutations, so the saving is large. Function bodies are gone; this is a map of the code, not a copy.
- On prose the automatic encoder is close to lossless and saves little: it only deduplicates long recurring names. The large savings on conversations come from a model or person writing the snapshot by hand (SKILL.md Mode A), which is a summary and drops detail.
- On a short paragraph AILv1 can cost more tokens than the prose. Pointers and section tags pay off only when names repeat.

An earlier version of this README claimed 94.8% (2,840 -> 148 tokens) for a session, 87.4% (1,680 -> 212 tokens) for `ail_mcp.py`, and ~95 -> ~32 tokens for the one-paragraph example. The first two inputs were never published and the third does not reproduce (85 -> 87 tokens above), so those claims were removed. A test (`tests/test_benchmarks.py`) fails if this table drifts from what `benchmarks/run.py` measures.

## Install and use

### As an Agent Skill (Claude Code, Cursor, and other `SKILL.md` agents)

```bash
git clone https://github.com/jiludkumar-therealone/ail-context-compressor.git
mkdir -p ~/.claude/skills
cp -r ail-context-compressor/skills/ail-context-compressor ~/.claude/skills/
```

### CLI

The script needs only the standard library. Install `tiktoken` for exact token counts and `mcp` for server mode.

```bash
S=skills/ail-context-compressor/scripts/ail_mcp.py

python3 $S pack -f notes.md > session.ail          # prose / chat log -> snapshot
python3 $S pack -f notes.md \
  --log "sync_ping|timeout_on_large_subnets|async_arp_scan" \
  --next "fix_sqlite_write_lock" > session.ail     # add negative constraints and tasks
python3 $S sig -f app.py                           # @SIG lines only
python3 $S unpack -f session.ail                   # hydrate
python3 $S pack --no-redact -f notes.md            # disable redaction (not recommended)
```

Or install the package from a checkout: `pip install .` gives you the `ail-mcp` command.

### MCP server

Tools: `ail_compress_text`, `ail_extract_code_sigs`, `ail_hydrate_state`, `ail_save_checkpoint` (writes a new `<name>.ail` in the server's working directory only; no directory argument, never overwrites, never follows symlinks). Works with `mcp` 1.x (`FastMCP`) and 2.x (`MCPServer`).

```json
{
  "mcpServers": {
    "ail-context-compressor": {
      "command": "python3",
      "args": ["/absolute/path/to/ail-context-compressor/skills/ail-context-compressor/scripts/ail_mcp.py", "mcp"]
    }
  }
}
```

The same block is in [`claude_desktop_config.example.json`](claude_desktop_config.example.json).

## Tests

```bash
python3 verify_ail.py           # standard library only; MCP tests skip without the mcp package
pip install ".[test]" && python3 -m pytest
```

CI (`.github/workflows/tests.yml`) runs both on every pull request (Python 3.10 and 3.13), plus the benchmark script.

## License

MIT
