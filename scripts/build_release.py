#!/usr/bin/env python3
"""Build the downloadable plugin zip for a release.

Standard library only. The output is deterministic: entries are sorted,
every entry gets the same timestamp and permissions, and nothing from the
build machine (owner, mtime, extra fields) goes into the archive. The same
commit therefore produces the same SHA-256.

    python3 scripts/build_release.py            # writes dist/
    python3 scripts/build_release.py --out DIR  # writes DIR/

The zip holds one top-level folder, ail-context-compressor/, with SKILL.md
at its root. That is the layout skill marketplaces such as Agensi expect, and
unzipping it into a skills folder (for example .claude/skills/) leaves the
skill at .claude/skills/ail-context-compressor/.
"""
import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = "skills/ail-context-compressor"  # source folder in the repository
TOP = "ail-context-compressor"  # top-level folder inside the zip
FIXED_TIME = (1980, 1, 1, 0, 0, 0)  # earliest time a zip entry can hold
FILE_MODE = 0o100644

# archive path -> source path, relative to the repository root.
# Anything not listed here is not shipped (tests, caches, venvs, dotfiles).
FILES = {
    f"{TOP}/SKILL.md": f"{SKILL}/SKILL.md",
    f"{TOP}/scripts/ail_mcp.py": f"{SKILL}/scripts/ail_mcp.py",
    f"{TOP}/mcp.example.json": f"{SKILL}/mcp.example.json",
    f"{TOP}/LICENSE": "LICENSE",
    f"{TOP}/README.md": "README.md",
    f"{TOP}/SECURITY.md": "SECURITY.md",
}


def version(root=ROOT):
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', text, re.M)
    if not match:
        sys.exit("build_release: no version in pyproject.toml")
    return match.group(1)


def zip_name(ver):
    return f"ail-context-compressor-v{ver}.zip"


def build(out_dir, root=ROOT):
    """Write the zip and its .sha256 file into out_dir. Return (zip_path, sha256)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / zip_name(version(root))
    with zipfile.ZipFile(zip_path, "w") as zf:
        for arcname in sorted(FILES):
            src = root / FILES[arcname]
            if not src.is_file() or src.is_symlink():
                sys.exit(f"build_release: missing or not a regular file: {FILES[arcname]}")
            data = src.read_bytes().replace(b"\r\n", b"\n")  # same bytes on any checkout
            info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, so external_attr is read as a mode
            info.external_attr = FILE_MODE << 16
            zf.writestr(info, data, compresslevel=9)
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    # Same format as sha256sum, so `sha256sum -c` works on it.
    (out_dir / (zip_path.name + ".sha256")).write_text(f"{digest}  {zip_path.name}\n", encoding="ascii")
    return zip_path, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "dist"), help="output directory (default: dist/)")
    args = parser.parse_args(argv)
    zip_path, digest = build(args.out)
    print(f"{digest}  {zip_path}")
    print(f"{zip_path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
