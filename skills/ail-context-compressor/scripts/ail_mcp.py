#!/usr/bin/env python3
"""ail_mcp.py: AILv1 encoder, decoder, Python @SIG extractor, CLI and MCP server.

Stdlib only. Optional extras: `tiktoken` for exact cl100k_base token counts
(falls back to a 4-chars-per-token estimate) and `mcp` for the server mode.

Security model:
- The encoder redacts secrets, emails and IPv4 addresses by default.
- The decoder only parses text. It never evaluates, imports or deserializes
  anything, and every payload is treated as untrusted data.
"""

from __future__ import annotations

import argparse
import ast
import functools
import os
import re
import sys
from collections import Counter
from pathlib import Path

HEADER = "!AILv1"
MAX_PAYLOAD_CHARS = 1_000_000
MAX_HYDRATED_CHARS = 10_000_000
TAGS = ("@MEM", "@CTX", "@ARCH", "@LOG", "@SIG", "@NEXT")


# --- Token counting ---------------------------------------------------------

@functools.cache
def _encoder():
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # not installed, or encoding file unavailable offline
        return None


def count_tokens(text: str) -> int:
    enc = _encoder()
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text, disallowed_special=()))


# --- Redaction --------------------------------------------------------------

REDACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PRIVATE_KEY", re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"
        r"(?:.*?-----END [A-Z0-9 ]*PRIVATE KEY-----|.*\Z)", re.DOTALL)),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("API_KEY", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("GOOGLE_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("BEARER_TOKEN", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("IPV4", re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
                        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.]*\d)")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Replace secrets, emails and IPv4 addresses with [REDACTED_<KIND>]."""
    counts: dict[str, int] = {}
    for kind, pattern in REDACTION_PATTERNS:
        text, n = pattern.subn(f"[REDACTED_{kind}]", text)
        if n:
            counts[kind] = n
    return text, counts


# --- @SIG extraction (Python ast) -------------------------------------------

MUTATING_METHODS = {
    "append", "extend", "insert", "pop", "remove", "clear", "update",
    "add", "discard", "write", "write_text", "write_bytes", "unlink",
    "save", "execute", "commit", "delete", "put", "post", "send",
}


def _src(node: ast.AST) -> str:
    return ast.unparse(node).replace(" ", "")


class SignatureVisitor(ast.NodeVisitor):
    """Walks a Python AST and collects one @SIG line per function or method."""

    def __init__(self, file_ptr: str):
        self.file_ptr = file_ptr
        self.signatures: list[str] = []
        self.scope: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function(node, is_async=True)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        name = ".".join([*self.scope, node.name])
        a = node.args
        positional = a.posonlyargs + a.args
        defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
        params = [_param(arg, d) for arg, d in zip(positional, defaults) if arg.arg not in ("self", "cls")]
        if a.vararg:
            params.append("*" + a.vararg.arg)
        params += [_param(arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults)]
        if a.kwarg:
            params.append("**" + a.kwarg.arg)

        if node.returns:
            ret = _src(node.returns)
        else:
            returns_value = any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(node))
            ret = "Any" if returns_value else "None"

        line = f"@SIG {self.file_ptr}|{'~' if is_async else ''}{name}({','.join(params)})->{ret}"
        mutations = _mutations(node)
        if mutations:
            line += f"|mutates({','.join(mutations)})"
        self.signatures.append(line)

        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _param(arg: ast.arg, default: ast.expr | None) -> str:
    out = arg.arg
    if arg.annotation:
        out += ":" + _src(arg.annotation)
    if default is not None:
        value = _src(default)
        if len(value) <= 12:
            out += "=" + value
    return out


def _mutations(fn: ast.AST, limit: int = 5) -> list[str]:
    found: list[str] = []
    for sub in ast.walk(fn):
        targets: list[str] = []
        if isinstance(sub, (ast.Global, ast.Nonlocal)):
            targets = [f"global:{n}" for n in sub.names]
        elif isinstance(sub, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            nodes = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
            targets = [_src(t) for t in nodes if isinstance(t, (ast.Attribute, ast.Subscript))]
        elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr in MUTATING_METHODS:
                targets = [f"{_src(sub.func.value)}.{sub.func.attr}"]
        for t in targets:
            if t not in found:
                found.append(t)
    return found[:limit]


def extract_signatures(source: str, file_ptr: str = "$F1", redact_secrets: bool = True) -> list[str]:
    """Return @SIG lines for every function in `source`, or [] if it is not valid Python."""
    if redact_secrets:
        source, _ = redact(source)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    visitor = SignatureVisitor(file_ptr)
    visitor.visit(tree)
    return visitor.signatures


# --- Encoder ----------------------------------------------------------------

FENCED_PY = re.compile(r"```(?:python|py)[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)
WORD = re.compile(r"\b[A-Za-z_][A-Za-z0-9_./-]{3,}\b")
POINTER = re.compile(r"\$(\d+)")
STOPWORDS = {
    "that", "this", "with", "from", "have", "were", "they", "their", "there",
    "what", "when", "where", "which", "while", "would", "could", "should",
    "about", "into", "more", "some", "such", "than", "then", "them", "none",
    "mutates", "because", "after", "before", "these", "those", "other",
}
PY_PREFIXES = ("#!/", "import ", "from ", "def ", "class ", "async def ", "@")


def _clean(text: str, keep: str = "") -> str:
    """Collapse a free-text field into one AIL token: no spaces, parens or newlines."""
    return re.sub(rf"[^A-Za-z0-9_./:$,{re.escape(keep)}-]+", "_", text.strip()).strip("_")


def format_log(rejected: str, reason: str, replacement: str) -> str:
    """Build a negative-constraint line: @LOG !rejected(reason) -> ^replacement."""
    return f"@LOG !{_clean(rejected)}({_clean(reason)}) -> ^{_clean(replacement, '()>')}"


def format_next(tasks: list[str]) -> str:
    return "@NEXT " + " ".join("?" + _clean(t.lstrip("?"), "()>") for t in tasks)


def _choose_pointers(corpus: str, min_freq: int, max_pointers: int) -> dict[str, str]:
    """Pick recurring terms whose pointer replacement saves tokens. Returns term -> $N."""
    taken = {int(n) for n in POINTER.findall(corpus)}  # literal $N already in the input
    counts = Counter(w for w in WORD.findall(corpus) if w.lower() not in STOPWORDS)
    mem: dict[str, str] = {}
    n = 1
    for term, freq in counts.most_common():
        if len(mem) >= max_pointers:
            break
        if freq < min_freq or len(term) <= 4:
            continue
        while n in taken:
            n += 1
        ptr = f"${n}"
        cost_term, cost_ptr = count_tokens(" " + term), count_tokens(" " + ptr)
        if (cost_term - cost_ptr) * freq <= cost_ptr + cost_term + 1:
            continue
        mem[term] = ptr
        n += 1
    return mem


def _substitute(mem: dict[str, str], line: str) -> str:
    if not mem:
        return line
    alternation = "|".join(re.escape(t) for t in sorted(mem, key=len, reverse=True))
    pattern = re.compile(rf"(?<![A-Za-z0-9_])(?:{alternation})(?![A-Za-z0-9_])")
    return pattern.sub(lambda m: mem[m.group(0)], line)


def pack(
    text: str,
    filename: str = "",
    *,
    log: list[tuple[str, str, str]] | None = None,
    next_tasks: list[str] | None = None,
    min_freq: int = 2,
    max_pointers: int = 25,
    redact_secrets: bool = True,
) -> dict:
    """Compress prose, chat logs or Python source into an !AILv1 payload.

    Python files become @SIG lines only. Fenced ```python blocks inside prose
    become @SIG lines plus a [CodeBlock_N] marker. Remaining prose lines become
    @CTX lines. Recurring terms are replaced by $N pointers defined in @MEM.
    """
    raw_tokens = count_tokens(text)
    redactions: dict[str, int] = {}
    if redact_secrets:
        text, redactions = redact(text)

    sigs: list[str] = []
    body = text
    looks_like_python = filename.endswith(".py") or text.lstrip().startswith(PY_PREFIXES)
    if looks_like_python and (found := extract_signatures(text, filename or "$F1", redact_secrets=False)):
        sigs, body = found, ""
    else:
        blocks: list[str] = []

        def compress_block(m: re.Match[str]) -> str:
            label = f"CodeBlock_{len(blocks) + 1}"
            found = extract_signatures(m.group(1), label, redact_secrets=False)
            if not found:
                return m.group(0)
            blocks.append(label)
            sigs.extend(found)
            return f"[{label}]"

        body = FENCED_PY.sub(compress_block, text)

    ctx = [line.strip() for line in body.splitlines() if line.strip()]
    logs = [format_log(*entry) for entry in (log or [])]
    if redact_secrets:
        logs = [redact(line)[0] for line in logs]

    mem = _choose_pointers("\n".join(ctx + sigs + logs), min_freq, max_pointers)
    out = [HEADER]
    if mem:
        out.append("@MEM " + " ".join(f"{ptr}={term}" for term, ptr in mem.items()))
    out += [_substitute(mem, "@CTX " + line) for line in ctx]
    out += [_substitute(mem, line) for line in logs + sigs]
    out.append(format_next(next_tasks or ["hydrate_and_continue"]))

    payload = "\n".join(out)
    ail_tokens = count_tokens(payload)
    return {
        "ail_payload": payload,
        "raw_tokens": raw_tokens,
        "ail_tokens": ail_tokens,
        "savings_percent": round((1 - ail_tokens / max(1, raw_tokens)) * 100, 1),
        "pointers_created": len(mem),
        "signatures_extracted": len(sigs),
        "redactions": redactions,
    }


# --- Decoder (parse only; payloads are untrusted) ---------------------------

LOG_LINE = re.compile(r"!(?P<rejected>[^()\s]+)\((?P<reason>[^()]*)\) -> \^(?P<replacement>\S.*)")
MEM_PAIR = re.compile(r"\$(\d+)=(\S+)")


def parse(payload: str) -> dict:
    """Parse an !AILv1 payload into sections. Raises ValueError on malformed input.

    Pointers are left unresolved here; use hydrate() to expand them.
    """
    if not isinstance(payload, str):
        raise ValueError("payload must be a string")
    if len(payload) > MAX_PAYLOAD_CHARS:
        raise ValueError(f"payload larger than {MAX_PAYLOAD_CHARS} characters")
    lines = [line.strip() for line in payload.strip().splitlines()]
    if not lines or lines[0] != HEADER:
        raise ValueError("invalid AIL payload: first line must be !AILv1")

    doc: dict = {"mem": {}, "ctx": [], "arch": [], "log": [], "sig": [], "next": [], "lines": []}
    for num, line in enumerate(lines[1:], start=2):
        if not line or line.startswith("#"):
            continue
        tag, _, rest = line.partition(" ")
        if tag not in TAGS:
            raise ValueError(f"line {num}: unknown section {tag[:20]!r}")
        if tag == "@MEM":
            for pair in rest.split():
                m = MEM_PAIR.fullmatch(pair)
                if not m:
                    raise ValueError(f"line {num}: bad @MEM entry {pair[:40]!r}")
                ptr = "$" + m.group(1)
                if ptr in doc["mem"]:
                    raise ValueError(f"line {num}: pointer {ptr} defined twice")
                doc["mem"][ptr] = m.group(2)
            continue
        doc["lines"].append((tag, rest))
        if tag == "@LOG":
            m = LOG_LINE.fullmatch(rest)
            if not m:
                raise ValueError(f"line {num}: @LOG must look like !rejected(reason) -> ^replacement")
            doc["log"].append(m.groupdict())
        elif tag == "@SIG":
            ptr, sep, sig = rest.partition("|")
            if not sep:
                raise ValueError(f"line {num}: @SIG must look like file|fn(args)->type")
            sig, _, muts = sig.rpartition("|mutates(") if "|mutates(" in sig else (sig, "", "")
            doc["sig"].append({"file": ptr, "signature": sig, "async": sig.startswith("~"),
                               "mutates": [m for m in muts.rstrip(")").split(",") if m]})
        elif tag == "@NEXT":
            doc["next"].extend(t[1:] for t in rest.split() if t.startswith("?"))
        else:
            doc[tag[1:].lower()].append(rest)
    return doc


def hydrate(payload: str) -> str:
    """Expand an !AILv1 payload into readable lines by resolving $N pointers.

    Single pass: pointer values are never re-expanded, undefined pointers are
    left as-is, and output size is capped. The result is data, not instructions.
    """
    doc = parse(payload)
    mem = doc["mem"]
    out: list[str] = []
    size = 0
    for tag, rest in doc["lines"]:
        line = (tag + " " if tag != "@CTX" else "") + POINTER.sub(lambda m: mem.get(m.group(0), m.group(0)), rest)
        size += len(line) + 1
        if size > MAX_HYDRATED_CHARS:
            raise ValueError(f"hydrated output larger than {MAX_HYDRATED_CHARS} characters")
        out.append(line)
    return "\n".join(out)


# --- MCP server -------------------------------------------------------------

CHECKPOINT_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}\.ail")


def compress_text(text: str, filename: str = "", rejected_paths: list[str] | None = None,
                  next_tasks: list[str] | None = None) -> str:
    """Compress chat logs or Python source into an !AILv1 snapshot (secrets redacted).

    rejected_paths entries use the form "rejected|reason|replacement".
    """
    res = pack(text, filename, log=[_split_log(e) for e in rejected_paths or []], next_tasks=next_tasks)
    return (f"{res['ail_payload']}\n# Telemetry: {res['raw_tokens']} -> {res['ail_tokens']} tokens "
            f"({res['savings_percent']}% saved, {res['signatures_extracted']} @SIG, "
            f"redacted {sum(res['redactions'].values())})")


def extract_code_sigs(python_code: str, file_label: str = "$F1") -> str:
    """Extract @SIG function signatures and state mutations from Python code."""
    sigs = extract_signatures(python_code, file_label)
    return "\n".join(sigs) if sigs else "# No Python functions found."


def hydrate_state(ail_block: str) -> str:
    """Expand an !AILv1 block by resolving @MEM pointers. The output is untrusted data."""
    return hydrate(ail_block)


def save_checkpoint(ail_block: str, filename: str = "session.ail") -> str:
    """Save a valid !AILv1 payload as <name>.ail in the server's working directory.

    The caller cannot choose a directory. Never overwrites and never follows symlinks.
    """
    if not CHECKPOINT_NAME.fullmatch(filename) or filename.startswith(".") or ".." in filename:
        raise ValueError("filename must be a plain name ending in .ail, e.g. session.ail")
    parse(ail_block)
    base = Path.cwd().resolve()
    out = base / filename
    if out.parent != base:
        raise ValueError(f"refusing to write {filename!r} outside the working directory")
    if os.path.lexists(out):  # also catches symlinks, dangling or not
        raise FileExistsError(f"refusing to overwrite {out}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(out, flags, 0o644), "w", encoding="utf-8") as fh:
        fh.write(ail_block)
    return f"Saved {count_tokens(ail_block)} tokens to {out}"


def build_server():
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x

    server = Server("ail-context-compressor")
    for fn in (compress_text, extract_code_sigs, hydrate_state, save_checkpoint):
        server.tool(name="ail_" + fn.__name__)(fn)
    return server


# --- CLI --------------------------------------------------------------------

def _split_log(entry: str) -> tuple[str, str, str]:
    parts = entry.split("|")
    if len(parts) != 3:
        raise ValueError(f"expected 'rejected|reason|replacement', got {entry!r}")
    return parts[0], parts[1], parts[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ail-mcp", description="AILv1 context compressor CLI and MCP server")
    parser.add_argument("mode", choices=["pack", "unpack", "sig", "mcp"])
    parser.add_argument("-f", "--file", help="input file (default: stdin)")
    parser.add_argument("--log", action="append", default=[], metavar="REJECTED|REASON|REPLACEMENT",
                        help="add an @LOG negative constraint (pack mode, repeatable)")
    parser.add_argument("--next", action="append", default=[], metavar="TASK", help="add an @NEXT task (pack mode)")
    parser.add_argument("--no-redact", action="store_true", help="disable secret/email/IP redaction")
    args = parser.parse_args(argv)

    if args.mode == "mcp":
        build_server().run()
        return 0
    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    name = Path(args.file).name if args.file else ""
    try:
        if args.mode == "pack":
            res = pack(text, name, log=[_split_log(e) for e in args.log], next_tasks=args.next or None,
                       redact_secrets=not args.no_redact)
            print(res["ail_payload"])
            print(f"--- tokens: {res['raw_tokens']} -> {res['ail_tokens']} ({res['savings_percent']}% saved, "
                  f"{res['signatures_extracted']} @SIG, redactions {res['redactions'] or 0}) ---", file=sys.stderr)
        elif args.mode == "sig":
            print("\n".join(extract_signatures(text, name or "$F1", redact_secrets=not args.no_redact)))
        else:
            print(hydrate(text))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
