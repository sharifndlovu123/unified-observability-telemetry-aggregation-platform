#!/usr/bin/env python3
"""Create .env from .env.example with random secrets. Refuses to overwrite an existing .env.

Every value that starts with "change-me" becomes a fresh random token, so a new clone needs no
manual editing (and no secret ever lives in the repository).
"""
import re
import secrets
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src, dst = root / ".env.example", root / ".env"
if dst.exists():
    sys.exit(".env already exists; leaving it untouched (delete it to regenerate)")

out = []
for line in src.read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        value = re.sub(r"\s+#.*$", "", value).strip()  # drop inline comments: env parsers differ on them
        if value.startswith("change-me"):
            value = secrets.token_urlsafe(48 if "KEY" in key else 18)
        line = f"{key}={value}"
    out.append(line)
dst.write_text("\n".join(out) + "\n")
dst.chmod(0o600)
print(f"wrote {dst} with generated secrets (mode 600)")
