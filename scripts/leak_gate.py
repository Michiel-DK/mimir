#!/usr/bin/env python3
"""Blocking leak-gate for anything about to be published to a public surface.

Scans the given files/dirs for secret-shaped content and for YOUR banned terms
(company, client and product names, personal identifiers) and **exits non-zero on
any hit** so a publish step can hard-fail before it pushes.

Two modes:
  * **full** (default) — for prose you write (verdicts, pickup notes, README):
    secret shapes + the patterns in `leakgate.txt`.
  * **--secrets-only** — for third-party SCRAPED data (data/*.jsonl): secret shapes
    only. A public repo whose description contains your product's name is public
    fact, not your leak.

Usage
-----
    python3 scripts/leak_gate.py <path> [<path> ...]
    python3 scripts/leak_gate.py --secrets-only data/daily
    python3 scripts/leak_gate.py --terms=leakgate.example.txt <path>   # CI: alternate banned-term list

Exit 0 = clean. Exit 1 = at least one hit (do not publish). Stdlib only.
"""

import re
import sys
from pathlib import Path


def _load_patterns(name):
    """One regex per line in <repo>/<name>; blank lines and # comments ignored. Missing file = none."""
    p = Path(__file__).resolve().parent.parent / name
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.lstrip().startswith("#")]


# Secret shapes — checked in EVERY mode. Length thresholds are set high enough
# that documentation placeholders (e.g. "tmrr_your_api_key") don't match.
SECRETS = [
    r"ghp_[A-Za-z0-9]{36}",
    r"gho_[A-Za-z0-9]{36}",
    r"xoxb-[0-9]{10,}",
    r"hooks\.slack\.com/services/[A-Z0-9]",
    r"tmrr_[A-Za-z0-9]{16,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"AKIA[0-9A-Z]{16}",
]

# Your business / product / personal terms — full mode only (authored prose).
# One regex per line in leakgate.txt (git-ignored). Word-boundary where a substring would false-positive.
BUSINESS = _load_patterns("leakgate.txt")

# Benign spans to blank out before deciding (e.g. an env var that contains a banned word).
ALLOW = _load_patterns("leakgate.allow.txt")

# Files where an otherwise-banned token is legitimately expected. LICENSE carries
# the author name. This gate's OWN source is skipped by absolute path below (not
# by name) — so a stray *copy* of it in a public target still gets flagged.
SKIP_FILES = {"LICENSE"}
SELF = Path(__file__).resolve()

# Only scan human-readable text; skip binaries/data blobs. `.jsonl` matters:
# the scraped snapshots live there and a leaked secret in a README excerpt
# would ride along in secrets-only mode if we skipped it.
TEXT_SUFFIXES = {".md", ".txt", ".py", ".yml", ".yaml", ".json", ".jsonl",
                 ".html", ".css", ".js", ".ts", ".toml", ".cfg", ".sh", ""}

SECRETS_RE = [re.compile(p, re.IGNORECASE) for p in SECRETS]
BUSINESS_RE = [re.compile(p, re.IGNORECASE) for p in BUSINESS]
ALLOW_RE = [re.compile(p, re.IGNORECASE) for p in ALLOW]


def iter_files(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and ".git/" not in str(f):
                    yield f
        elif p.is_file():
            yield p


def scan_line(line, patterns):
    """Return the patterns hit on this line, after blanking allowed spans."""
    # Blank out allowed spans first.
    masked = line
    for a in ALLOW_RE:
        masked = a.sub(lambda m: "\0" * len(m.group(0)), masked)
    return [p.pattern for p in patterns if p.search(masked)]


def main(argv):
    secrets_only = "--secrets-only" in argv
    terms = next((a.split("=", 1)[1] for a in argv if a.startswith("--terms=")), None)
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        print("usage: leak_gate.py [--secrets-only] <path> [<path> ...]",
              file=sys.stderr)
        return 2
    business_re = BUSINESS_RE
    if terms:  # CI uses the public example list; the real one never leaves the private machine
        business_re = [re.compile(p, re.IGNORECASE) for p in _load_patterns(terms)]
    patterns = SECRETS_RE if secrets_only else SECRETS_RE + business_re
    hits, scanned = [], 0
    for f in iter_files(paths):
        if f.name in SKIP_FILES or f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if f.resolve() == SELF:  # skip only THIS running gate, not stray copies
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        scanned += 1
        for n, line in enumerate(text.splitlines(), 1):
            for pat in scan_line(line, patterns):
                hits.append((f, n, pat, line.strip()[:100]))

    mode = "secrets-only" if secrets_only else "full"
    if not secrets_only and not business_re:
        print("⚠️  leak-gate: no banned-term list loaded — full mode checked secret shapes only", file=sys.stderr)
    if hits:
        print(f"🛑 leak-gate ({mode}): {len(hits)} hit(s) — DO NOT publish:\n")
        for f, n, pat, snippet in hits:
            print(f"  {f}:{n}  /{pat}/  →  {snippet}")
        return 1
    print(f"✓ leak-gate clean ({mode}, {scanned} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
