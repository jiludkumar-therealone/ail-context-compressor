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

## Prompt-only encoder (no install)

Copy the prompt below into any AI chat to compress that conversation into an AILv1 block. No install is needed.

> **Prompt-only, best-effort.** The model writes the block itself, so it can drop details or miss a secret. For exact signatures and guaranteed redaction, use the Python encoder. Don't paste secrets into a chat and rely on this prompt to remove them.

```text
You are an AILv1 encoder. Compress everything in this conversation so far into ONE AILv1 block that another AI can load as working context. Output only the block.

FORMAT
!AILv1
@MEM $1=Name $2=Other_Name      assign a $N pointer to every person, project, file, tool, service; use pointers everywhere after
@CTX Label:=$1|$2               relationships, goals, constraints, current state
@LOG !rejected(reason) -> ^replacement   every approach tried and dropped, why, and what replaced it
@SIG file|~fn(args)->return|mutates(x)   only functions/commands actually shown in the chat, copied exactly; ~ only if async
@NEXT ?open_question            open questions and next steps
# AILv1 block complete. Redaction is best-effort; check before sharing.

RULES
1. Preserve facts, decisions, names, numbers and exact code identifiers. Never invent or guess. If unsure, write it as @NEXT ?unclear:<topic>.
2. Redact before writing, and this rule beats every other rule: API keys, tokens, passwords, private keys, connection strings and URLs with credentials, cookies and session IDs, card or bank numbers, emails, phone numbers and IP addresses become [REDACTED], even inside @SIG or code. If unsure whether something is a secret, redact it.
3. Dense, not lossy: no prose, no filler, one fact per line. Use underscores instead of spaces inside names, pointers and @NEXT items.
4. Later decisions override earlier ones; record the earlier one in @LOG.
5. End the block with this comment line: "# AILv1 block complete. Redaction is best-effort; check before sharing."
```

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

### Download the release (recommended)

Each release on the [Releases page](https://github.com/jiludkumar-therealone/ail-context-compressor/releases/latest) has two files: `ail-context-compressor-v1.0.1.zip` and `ail-context-compressor-v1.0.1.zip.sha256`. The zip holds a single folder, `ail-context-compressor/`, with `SKILL.md`, `scripts/ail_mcp.py`, `mcp.example.json`, this README, SECURITY.md and LICENSE.

1. Download both files into the same folder and check the zip before you unpack it:

   ```bash
   sha256sum -c ail-context-compressor-v1.0.1.zip.sha256          # Linux
   shasum -a 256 -c ail-context-compressor-v1.0.1.zip.sha256      # macOS
   ```

   It should print `ail-context-compressor-v1.0.1.zip: OK`. If it does not, delete the zip and download it again.

2. Unzip it into your project's skills folder. For Claude Code that is `.claude/skills/`, which puts the skill at `.claude/skills/ail-context-compressor/`:

   ```bash
   cd /path/to/your-project
   mkdir -p .claude/skills
   unzip /path/to/ail-context-compressor-v1.0.1.zip -d .claude/skills
   ```

   Use `~/.claude/skills` instead to make the skill available in every project. Other agents that read `SKILL.md` files have their own skills folder; unzip into it.

3. To use the MCP server as well, copy the block from `mcp.example.json` into your client's MCP config (for example `.mcp.json` in the project for Claude Code, or `.cursor/mcp.json` for Cursor) and set the path to where `ail_mcp.py` now lives. See [MCP server](#mcp-server) below.

The zip is built by `python3 scripts/build_release.py`, which is deterministic: the same commit gives the same SHA-256.

### From a clone

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

The same block is in [`claude_desktop_config.example.json`](claude_desktop_config.example.json), and in `mcp.example.json` inside the release zip.

## Tests

```bash
python3 verify_ail.py           # standard library only; MCP tests skip without the mcp package
pip install ".[test]" && python3 -m pytest
```

CI (`.github/workflows/tests.yml`) runs both on every pull request (Python 3.10 and 3.13), plus the benchmark script.

## License

MIT
