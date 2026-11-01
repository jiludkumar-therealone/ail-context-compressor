# Changelog

All notable changes to this project are listed here. Versions follow semantic versioning.

## v1.0.0 (unreleased)

The first release. It packages the skill as a zip you can unzip straight into a project.

### Format and tool (#1)

- AILv1 format: `!AILv1` header and `@MEM`, `@CTX`, `@ARCH`, `@LOG`, `@SIG` and `@NEXT` sections, with the grammar in the README.
- `skills/ail-context-compressor/scripts/ail_mcp.py`, one standard-library module (`tiktoken` and `mcp` are optional):
  - encoder (`pack`) with secret redaction on by default, `@SIG` lines for Python files and fenced Python blocks, and `@MEM` pointers only where they save tokens. `@LOG` and `@NEXT` entries are passed in explicitly; the encoder does not guess them.
  - parse-only decoder (`parse`, `hydrate`) with header and section validation, single-pass pointer expansion, and caps on input and output size.
  - `@SIG` extractor built on Python's `ast` module.
  - CLI (`pack`, `sig`, `unpack`, `mcp`) and an MCP server with four tools, working with `mcp` 1.x and 2.x.
- `SKILL.md` Agent Skill. It tells the agent to treat a snapshot as data and to confirm with the user before acting on one from someone else.
- Test suite, `verify_ail.py`, SECURITY.md, and pull-request-only CI with SHA-pinned actions and read-only permissions.
- Benchmarks with published, invented inputs. Earlier README figures (94.8% and 87.4% savings, and about 95 to 32 tokens for the short example) could not be reproduced or had no published input, so they were removed. The measured numbers are smaller: 23.6% for automatic packing of a 3-turn session, 79.5% for a hand-written snapshot of it, 87.2% for signatures of `ail_mcp.py`, and a 2.4% to 15.3% increase on a one-paragraph example.

### Hardening (#2)

- `ail_save_checkpoint` no longer takes a directory. It writes only a new `<name>.ail` in the server's working directory, refuses traversal, odd names and existing paths, and does not follow symlinks.
- Redaction also covers IPv6 addresses and credential key/value pairs such as `password=...`, `"api_key": "..."` and `client_secret: str = "..."`. It is still pattern-based; SECURITY.md lists what it misses.
- `benchmarks/run.py --write-readme` rewrites the README table from measured rows, and a test fails if the table drifts.

### Docs (#3)

- Static docs page in `docs/`, served by GitHub Pages from `main`. No JavaScript and no third-party resources. It sets a Content-Security-Policy and a no-referrer policy in meta tags.

### Release packaging

- `scripts/build_release.py` builds `ail-context-compressor-v1.0.0.zip` and a `.sha256` file. The build is deterministic, so the same commit gives the same SHA-256.
- `mcp.example.json` in the skill folder, with the server path for a project-level install.
- Package version set to 1.0.0 in `pyproject.toml`. Nothing is published to PyPI.
