import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "ail-context-compressor" / "scripts" / "ail_mcp.py"
sys.path.insert(0, str(SCRIPT.parent))
