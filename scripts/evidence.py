"""Fetch the evidence a triage row must cite, and save it under evidence/<date>/.

The radar-triage skill forbids a verdict stronger than PARKED on a repo until every
LICENSE/COPYING file at every tree depth has been read, and forbids numbers that do
not come from a fetched artefact. This script does those fetches so the rule is a
function call instead of a hope.

Item kinds (detected from the argument):
  arXiv      2610.18813 · arxiv.org/abs/2610.18813 · arxiv.org/pdf/2610.18813v2
             → title, authors, date, abstract from the abs page
  HF model   hf:org/name · huggingface.co/org/name
             → licence (cardData + tags), downloads, pipeline tag, gated flag, card head
  HF blog    huggingface.co/blog/...
             → page text (first ~6k chars), no benchmark is trusted
  GitHub     owner/repo · github.com/owner/repo
             → created_at, pushed_at, stars, default branch, API licence key,
               README head, and EVERY licence-ish file at every depth with its first lines

Run:  python3 scripts/evidence.py 2610.18813 mozilla-ai/otari hf:ibm-granite/granite-4.1-8b
      python3 scripts/evidence.py --date 2026-10-21 owner/repo
      GITHUB_TOKEN=... python3 scripts/evidence.py owner/repo    # higher rate limit, private repos

Writes one markdown file per item and prints its path. Network errors are written
into the file as "⚠️ UNVERIFIED: <error>" rather than crashing the run, because a
missing fetch must stay visible in the row.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"
UA = {"User-Agent": "mimir-radar/0.1 (+https://github.com/Michiel-DK/mimir)"}
TIMEOUT = 45

ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf|html)/)?(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?/?$")
HF_MODEL_RE = re.compile(r"^(?:hf:|https?://huggingface\.co/)([\w.\-]+/[\w.\-]+?)/?$")
HF_BLOG_RE = re.compile(r"^https?://huggingface\.co/blog/\S+$")
GH_RE = re.compile(r"^(?:https?://github\.com/)?([\w.\-]+)/([\w.\-]+?)(?:\.git|/.*)?$")
LICENCE_PATH_RE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|COPYRIGHT|NOTICE|UNLICENSE)(\.|-|_|$)", re.I)
SPDX_HINTS = [
    ("Apache-2.0", r"Apache License\s+Version 2\.0"), ("MIT", r"MIT License"),
    ("BSD-3-Clause", r"Redistribution and use in source and binary forms.*neither the name", ),
    ("BSD-2-Clause", r"Redistribution and use in source and binary forms"),
    ("GPL-3.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 3"), ("GPL-2.0", r"GNU GENERAL PUBLIC LICENSE\s+Version 2"),
    ("AGPL-3.0", r"GNU AFFERO GENERAL PUBLIC LICENSE"), ("LGPL", r"GNU LESSER GENERAL PUBLIC LICENSE"),
    ("MPL-2.0", r"Mozilla Public License,? Version 2\.0"), ("Unlicense", r"This is free and unencumbered software"),
    ("CC-BY-NC", r"NonCommercial"), ("CC-BY", r"Creative Commons Attribution"),
    ("BUSL-1.1", r"Business Source License"), ("SSPL", r"Server Side Public License"),
    ("Elastic-2.0", r"Elastic License 2\.0"), ("Llama", r"LLAMA .{0,20}COMMUNITY LICENSE"),
    ("Gemma", r"Gemma Terms of Use"), ("LFM", r"LFM Open License"),
]


def detect(item: str) -> tuple[str, str]:
    """Return (kind, key). Order matters: HF and arXiv URLs also match the GitHub owner/repo shape."""
    s = item.strip()
    if HF_BLOG_RE.match(s):
        return "hfblog", s
    m = HF_MODEL_RE.match(s)
    if m and (s.startswith("hf:") or "huggingface.co" in s):
        return "hfmodel", m.group(1)
    m = ARXIV_RE.search(s)
    if m and ("arxiv" in s or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", s)):
        return "arxiv", m.group(1)
    m = GH_RE.match(s)
    if m and (not s.startswith("http") or "github.com" in s):
        return "github", f"{m.group(1)}/{m.group(2)}"
    raise ValueError(f"cannot classify {item!r}: use an arXiv id, hf:org/name, a HF blog URL, or owner/repo")


def _get(url: str, headers: dict | None = None, **kw) -> requests.Response:
    h = dict(UA)
    if headers:
        h.update(headers)
    r = requests.get(url, headers=h, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def spdx_guess(text: str) -> str:
    head = text[:4000]
    for name, pat in SPDX_HINTS:
        if re.search(pat, head, re.I | re.S):
            return name
    return "unrecognised (read the file)"


# ---------------------------------------------------------------- arXiv
def fetch_arxiv(aid: str) -> str:
    url = f"https://arxiv.org/abs/{aid}"
    try:
        html = _get(url).text
    except Exception as e:  # noqa: BLE001
        return f"# arXiv {aid}\n\n⚠️ UNVERIFIED: fetch failed — {e}\n"
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1.title")
        title = title.get_text(" ", strip=True).replace("Title:", "", 1).strip() if title else "?"
        abstract = soup.select_one("blockquote.abstract")
        abstract = abstract.get_text(" ", strip=True).replace("Abstract:", "", 1).strip() if abstract else "?"
        authors = soup.select_one("div.authors")
        authors = authors.get_text(" ", strip=True).replace("Authors:", "", 1).strip() if authors else "?"
        dateline = soup.select_one("div.dateline")
        dateline = dateline.get_text(" ", strip=True) if dateline else "?"
        comments = soup.select_one("td.tablecell.comments")
        comments = comments.get_text(" ", strip=True) if comments else ""
    except Exception as e:  # noqa: BLE001
        return f"# arXiv {aid}\n\n{url}\n\n⚠️ UNVERIFIED: parse failed — {e}\n\n```\n{html[:3000]}\n```\n"
    return (f"# arXiv {aid} — {title}\n\n{url}\n\n- authors: {authors}\n- {dateline}\n"
            + (f"- comments: {comments}\n" if comments else "")
            + f"- evidence scope: (abstract) — body not read by this script\n\n## Abstract\n\n{abstract}\n")


# ---------------------------------------------------------------- Hugging Face
def fetch_hf_model(mid: str) -> str:
    url = f"https://huggingface.co/api/models/{mid}"
    try:
        d = _get(url).json()
    except Exception as e:  # noqa: BLE001
        return f"# HF model {mid}\n\n⚠️ UNVERIFIED: fetch failed — {e}\n"
    card = d.get("cardData") or {}
    tags = d.get("tags") or []
    lic_tags = [t for t in tags if t.startswith("license:")]
    lic = card.get("license") or (lic_tags[0].split(":", 1)[1] if lic_tags else "⚠️ not stated in card/tags")
    lic_name = card.get("license_name")
    lic_link = card.get("license_link")
    out = [f"# HF model {mid}", "", f"https://huggingface.co/{mid}", "",
           f"- licence (cardData.license): **{lic}**" + (f" · license_name: {lic_name}" if lic_name else "")
           + (f" · license_link: {lic_link}" if lic_link else ""),
           f"- licence tags: {', '.join(lic_tags) or 'none'}",
           f"- gated: {d.get('gated')} · private: {d.get('private')} · disabled: {d.get('disabled')}",
           f"- pipeline_tag: {d.get('pipeline_tag')} · library: {d.get('library_name')}",
           f"- downloads (30d): {d.get('downloads')} · likes: {d.get('likes')} · created: {str(d.get('createdAt') or '')[:10]} · last modified: {str(d.get('lastModified') or '')[:10]}",
           f"- base_model: {card.get('base_model')}" if card.get("base_model") else "",
           f"- evidence scope: (model card API; any benchmark in the card is the vendor's)", ""]
    if lic and str(lic).lower() == "other":
        out.append(f"⚠️ licence is `other`" + (f" (named {lic_name!r})" if lic_name else "") +
                   ": UNKNOWN until the licence file is read — "
                   f"https://huggingface.co/{mid}/blob/main/{lic_link or 'LICENSE'}")
    try:
        readme = _get(f"https://huggingface.co/{mid}/raw/main/README.md").text
        body = re.sub(r"^---.*?---\s*", "", readme, count=1, flags=re.S)
        out += ["", "## Card head (first 3000 chars after front-matter)", "", "```", body[:3000], "```"]
    except Exception as e:  # noqa: BLE001
        out += ["", f"⚠️ card README not fetched — {e}"]
    return "\n".join(x for x in out if x is not None) + "\n"


def fetch_hf_blog(url: str) -> str:
    try:
        html = _get(url).text
    except Exception as e:  # noqa: BLE001
        return f"# HF blog\n\n{url}\n\n⚠️ UNVERIFIED: fetch failed — {e}\n"
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "nav", "footer"]):
            t.decompose()
        title = soup.title.get_text(strip=True) if soup.title else url
        main = soup.select_one("main") or soup.body or soup
        text = re.sub(r"\n{3,}", "\n\n", main.get_text("\n", strip=True))
    except Exception as e:  # noqa: BLE001
        return f"# HF blog\n\n{url}\n\n⚠️ UNVERIFIED: parse failed — {e}\n"
    return (f"# HF blog — {title}\n\n{url}\n\n- evidence scope: (post read; benchmarks are the vendor's)\n\n"
            f"```\n{text[:6000]}\n```\n")


# ---------------------------------------------------------------- GitHub
def _gh_headers() -> dict:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    h = {"Accept": "application/vnd.github+json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def fetch_github(slug: str) -> str:
    api = f"https://api.github.com/repos/{slug}"
    hdr = _gh_headers()
    try:
        d = _get(api, hdr).json()
    except Exception as e:  # noqa: BLE001
        return f"# GitHub {slug}\n\n⚠️ UNVERIFIED: repo fetch failed — {e}\n"
    branch = d.get("default_branch") or "main"
    out = [f"# GitHub {slug}", "", f"https://github.com/{slug}", "",
           f"- description: {d.get('description')}",
           f"- created_at: {str(d.get('created_at') or '')[:10]} · pushed_at: {str(d.get('pushed_at') or '')[:10]} · default branch: {branch}",
           f"- stars: {d.get('stargazers_count')} · forks: {d.get('forks_count')} · open issues: {d.get('open_issues_count')} · archived: {d.get('archived')} · fork: {d.get('fork')}",
           f"- language: {d.get('language')} · topics: {', '.join(d.get('topics') or []) or 'none'}",
           f"- API licence key: **{(d.get('license') or {}).get('spdx_id') or 'none'}** "
           f"(`NOASSERTION`/`other`/none = unknown until the files below are read)", ""]

    # every licence-ish file at every depth
    out += ["## Licence files at every depth", ""]
    try:
        tree = _get(f"{api}/git/trees/{branch}?recursive=1", hdr).json()
        paths = [t["path"] for t in tree.get("tree", []) if t.get("type") == "blob" and LICENCE_PATH_RE.search(t["path"])]
        if tree.get("truncated"):
            out.append("⚠️ tree listing was TRUNCATED by the API; deeper licence files may exist. Clone to be sure.")
        if not paths:
            out.append("⚠️ NO licence file found at any depth → all rights reserved until the author says otherwise.")
        found = []
        for p in paths[:25]:
            try:
                c = _get(f"{api}/contents/{p}?ref={branch}", hdr).json()
                txt = base64.b64decode(c.get("content") or b"").decode("utf-8", "replace") if c.get("encoding") == "base64" else ""
            except Exception as e:  # noqa: BLE001
                txt = f"⚠️ UNVERIFIED: could not read — {e}"
            guess = spdx_guess(txt) if txt and not txt.startswith("⚠️") else "?"
            found.append(guess)
            head = "\n".join(txt.splitlines()[:6])
            out += [f"### `{p}` → {guess}", "", "```", head, "```", ""]
        if len(paths) > 25:
            out.append(f"⚠️ {len(paths) - 25} more licence-ish files not shown.")
        distinct = sorted(set(g for g in found if g and g != "?"))
        if len(distinct) > 1:
            out += ["", f"⚠️ MIXED licences across the tree: {', '.join(distinct)} — per-directory split, read before any verdict.", ""]
        elif distinct:
            out += ["", f"All licence files read as: {distinct[0]} ({len(paths)} file(s)).", ""]
    except Exception as e:  # noqa: BLE001
        out.append(f"⚠️ UNVERIFIED: tree fetch failed — {e}")

    # README head
    try:
        r = _get(f"{api}/readme", hdr).json()
        txt = base64.b64decode(r.get("content") or b"").decode("utf-8", "replace")
        out += ["## README head (first 4000 chars)", "", "```", txt[:4000], "```", ""]
    except Exception as e:  # noqa: BLE001
        out += [f"⚠️ README not fetched — {e}", ""]
    out += ["- evidence scope: (README + licence files, not run)"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main
FETCHERS = {"arxiv": fetch_arxiv, "hfmodel": fetch_hf_model, "hfblog": fetch_hf_blog, "github": fetch_github}


def safe_name(kind: str, key: str) -> str:
    k = re.sub(r"^https?://huggingface\.co/blog/", "", key)
    k = re.sub(r"[^\w.\-]+", "-", k).strip("-")
    return f"{kind}-{k}.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("items", nargs="+", help="arXiv ids, hf:org/name, HF blog URLs, owner/repo or URLs")
    ap.add_argument("--date", default=date.today().isoformat(), help="evidence/<date>/ folder (default today)")
    ap.add_argument("--out-dir", default=str(EVIDENCE_DIR))
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir) / args.date
    rc = 0
    for item in args.items:
        try:
            kind, key = detect(item)
        except ValueError as e:
            print(f"[evidence] {e}", file=sys.stderr)
            rc = 2
            continue
        text = FETCHERS[kind](key)
        if args.stdout:
            print(text)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / safe_name(kind, key)
        p.write_text(text, encoding="utf-8")
        flag = " ⚠️" if "⚠️" in text else ""
        print(f"[evidence] {kind:7s} {key} → {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}{flag}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
