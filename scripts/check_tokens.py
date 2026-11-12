"""Gate: every hex colour in ui/src and ui/tailwind.config.js must be a token from DESIGN.md. Exit 1 + list otherwise."""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parent.parent
hexre = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
allowed = {h.lower() for h in hexre.findall((root / "DESIGN.md").read_text())}
bad = []
for p in [*(root / "ui" / "src").rglob("*"), root / "ui" / "tailwind.config.js"]:
    if p.is_file() and p.suffix in {".css", ".js", ".jsx", ".ts", ".tsx", ".html"}:
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            for h in hexre.findall(line):
                if h.lower() not in allowed:
                    bad.append(f"{p.relative_to(root)}:{i} {h}")
print("\n".join(bad) or "tokens ok")
sys.exit(1 if bad else 0)
