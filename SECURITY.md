# Security

## Reporting a vulnerability

Please report security issues privately through GitHub's **Report a vulnerability** button on the repository's Security tab (private vulnerability reporting). If that button is not available, open an issue that asks for a private contact and leave the details out. Do not post vulnerability details publicly. Include the version or commit, steps to reproduce, and the impact you expect. You should get a first response within 7 days.

## Payloads are untrusted

An `!AILv1` payload is untrusted input, wherever it came from.

- The decoder (`parse`, `hydrate`, the `unpack` CLI mode and the `ail_hydrate_state` MCP tool) only parses text with regular expressions and string operations. It never calls `eval`, `exec`, `pickle`, `marshal` or a YAML loader, and a test fails if the module starts to.
- Parsing rejects payloads without the `!AILv1` header, unknown sections, malformed `@MEM`, `@LOG` or `@SIG` lines, payloads over 1,000,000 characters, and hydrated output over 10,000,000 characters. Pointers expand in a single pass, so a pointer value cannot expand further.
- Decoded content is data, not instructions. A payload can contain text written to manipulate a model ("ignore previous instructions", fake `@NEXT` tasks). Agents should not act on a payload from a third party without confirming with their user.
- `ail_save_checkpoint` takes no directory argument. It writes only a plain `<name>.ail` file (no separators, no leading dot, no `..`) in the server's working directory, only after the payload parses. It checks the resolved path stays in that directory, refuses existing files and symlinks, and opens with `O_EXCL | O_NOFOLLOW`. A prompt-injected model can at most create a new `.ail` file in that one directory.

## Redaction scope

`pack`, `sig`, and the `ail_compress_text` / `ail_extract_code_sigs` MCP tools redact by default (CLI opt-out: `--no-redact`). Matches become `[REDACTED_<KIND>]`:

| Kind | Pattern |
|---|---|
| `PRIVATE_KEY` | `-----BEGIN ... PRIVATE KEY-----` blocks, including unterminated ones |
| `GITHUB_TOKEN` | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_` |
| `API_KEY` | `sk-...` keys (16+ characters after the prefix) |
| `AWS_KEY` | `AKIA` / `ASIA` access key IDs |
| `SLACK_TOKEN` | `xoxa-`, `xoxb-`, `xoxp-`, `xoxo-`, `xoxs-`, `xoxr-` |
| `GOOGLE_KEY` | `AIza...` API keys |
| `JWT` | three-part `eyJ...` tokens |
| `BEARER_TOKEN` | `Bearer <token>` |
| `EMAIL` | email addresses |
| `IPV4` | every IPv4 address, including private (`10.x`, `172.16/12`, `192.168.x`) and CGNAT (`100.64.0.0/10`) ranges |

Not covered: IPv6 addresses, hostnames, passwords in free text, and secret formats not listed above. Redaction is pattern based and best effort; review a snapshot before you share it. The decoder does not redact.
