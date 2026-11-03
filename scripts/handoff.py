"""Hand each lane's new pickup block to the repo it belongs to, as an issue or a docs PR.

Triage writes `pickup/<lane id>.md` inside this repo. That is where the loop used to stop:
the note sat here and someone had to remember to carry it over. This script carries it.
For every lane that gained a block from the given triage date, it opens one GitHub issue
(default) or one docs PR on the lane's repo, with the block, the lane's question and a
link back to the verdict section. Triage still opens no work: the issue is a reading
note, and whoever owns the repo closes it.

Judgement stays in the agent session; this step is deterministic and runs after it.

Reads:   radar.yaml            `handoff:` block (mode, repos map, pr_path, labels) + lanes[].repo
         pickup/<lane id>.md   blocks headed `## <date> — from triage <date>`
Writes:  data/handoff/<triage date>.json   ledger: what was opened where (re-runs skip it)

Run:  python3 scripts/handoff.py --date 2026-11-03 --dry-run     # print every note, send nothing
      python3 scripts/handoff.py --date 2026-11-03               # open issues (or PRs) via `gh`
      python3 scripts/handoff.py --date 2026-11-03 --lane ticket-agent-evals
      python3 scripts/handoff.py --date 2026-10-19 --dry-run --pickup-dir examples/2026-10-19/pickup   # demo on the shipped fixture

radar.yaml:
    handoff:
      mode: issue                 # issue | pr
      repos:                      # lane.repo label → GitHub owner/name; unmapped lanes are skipped, loudly
        support-agent: example-labs/support-agent
      pr_path: docs/pickup        # pr mode only: file lands at <pr_path>/<date>-<lane id>.md
      verdicts_url: https://github.com/you/your-private-radar/blob/main/VERDICTS.md   # optional link target
      labels: [mimir]             # issue mode only, optional; labels must already exist on the repo

Needs `gh` authenticated with write access to the target repos (locally: `gh auth status`;
in Actions: a token with issues/contents/pull-requests write on those repos). Every body
passes the leak gate (full mode, your leakgate.txt) before it leaves the machine.

Exit 0 = everything sent or nothing to send. Exit 1 = config error or a `gh` call failed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICKUP_DIR = ROOT / "pickup"
LEDGER_DIR = ROOT / "data" / "handoff"
LEAK_GATE = ROOT / "scripts" / "leak_gate.py"

# `## 2026-11-03 — from triage 2026-11-03`; the dash may be an em dash, en dash or hyphen.
BLOCK_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*[—–-]+\s*from triage\s+(\d{4}-\d{2}-\d{2})\s*$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# ----------------------------------------------------------------------------- parsing

def parse_blocks(text: str) -> list[dict]:
    """Split a pickup file into blocks: {written, triage, body}. Body excludes the heading."""
    blocks: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = BLOCK_RE.match(line)
        if m:
            current = {"written": m.group(1), "triage": m.group(2), "body": []}
            blocks.append(current)
            continue
        if line.startswith("## ") and current is not None:  # a heading that is not a pickup block ends it
            current = None
            continue
        if current is not None:
            current["body"].append(line)
    for b in blocks:
        b["body"] = "\n".join(b["body"]).strip("\n")
    return blocks


def blocks_for(pickup_dir: Path, triage: str, only_lane: str | None = None) -> dict[str, dict]:
    """lane id → the block written from `triage` (the last one if there are several)."""
    out: dict[str, dict] = {}
    if not pickup_dir.is_dir():
        return out
    for p in sorted(pickup_dir.glob("*.md")):
        lane = p.stem
        if only_lane and lane != only_lane:
            continue
        hits = [b for b in parse_blocks(p.read_text(encoding="utf-8")) if b["triage"] == triage]
        if hits:
            out[lane] = hits[-1]
    return out


# ----------------------------------------------------------------------------- config

def handoff_config(cfg: dict) -> dict:
    h = cfg.get("handoff")
    if not isinstance(h, dict):
        raise SystemExit("handoff: radar.yaml has no `handoff:` block (see radar.example.yaml)")
    mode = str(h.get("mode", "issue")).lower()
    if mode not in ("issue", "pr"):
        raise SystemExit(f"handoff: mode must be issue or pr, got {mode!r}")
    repos = h.get("repos") or {}
    if not isinstance(repos, dict) or not repos:
        raise SystemExit("handoff: `handoff.repos` must map lane repo labels to owner/name")
    for label, full in repos.items():
        if not isinstance(full, str) or not REPO_RE.match(full):
            raise SystemExit(f"handoff: repos[{label!r}] must be owner/name, got {full!r}")
    labels = h.get("labels") or []
    if not isinstance(labels, list):
        raise SystemExit("handoff: `handoff.labels` must be a list")
    return {
        "mode": mode,
        "repos": repos,
        "pr_path": str(h.get("pr_path") or "docs/pickup").strip("/"),
        "labels": [str(x) for x in labels],
        "source": h.get("source"),  # optional: URL of this mimir repo for the link back
        "verdicts_url": h.get("verdicts_url"),  # optional: where VERDICTS.md lives if not <source>/blob/main/VERDICTS.md
    }


def lanes_by_id(cfg: dict) -> dict[str, dict]:
    return {str(l.get("id")): l for l in (cfg.get("lanes") or []) if isinstance(l, dict) and l.get("id")}


def resolve_repo(lane: dict, hcfg: dict) -> str | None:
    label = lane.get("repo")
    if not label:
        return None
    if label in hcfg["repos"]:
        return hcfg["repos"][label]
    if REPO_RE.match(str(label)):  # lane.repo already written as owner/name
        return str(label)
    return None


# ----------------------------------------------------------------------------- rendering

def source_url(hcfg: dict, run) -> str | None:
    if hcfg.get("source"):
        return str(hcfg["source"]).rstrip("/")
    try:
        r = run(["git", "-C", str(ROOT), "remote", "get-url", "origin"])
    except Exception:  # no remote, no link; the body says so
        return None
    url = (r.stdout or "").strip()
    if not url:
        return None
    url = re.sub(r"^git@github\.com:", "https://github.com/", url)
    url = re.sub(r"\.git$", "", url)
    return url if url.startswith("http") else None


def title_for(triage: str, lane_id: str) -> str:
    return f"mimir pickup {triage}: {lane_id}"


def render_body(lane_id: str, lane: dict, block: dict, triage: str, src: str | None,
                verdicts_url: str | None = None) -> str:
    q = str(lane.get("question", "")).strip()
    status = lane.get("status")
    head = [f"Pickup from mimir triage **{triage}**, lane `{lane_id}`" + (f" (status: {status})." if status else ".")]
    if q:
        head.append("")
        head.append(f"> {q}")
    verdicts = verdicts_url or (f"{src}/blob/main/VERDICTS.md" if src else "VERDICTS.md next to the pickup notes")
    tail = [
        "---",
        f"Opened by mimir `scripts/handoff.py`. Verdict rows and evidence scope: {verdicts} (section {triage}).",
        "Triage opens no work; this is a reading note. Close it when the lane's list is updated or the item is rejected.",
    ]
    return "\n".join(head + ["", block["body"], ""] + tail) + "\n"


# ----------------------------------------------------------------------------- gh plumbing

def default_run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, text=True, capture_output=True, **kw)


def gate_body(body: str, run) -> None:
    """Full leak gate on the rendered body; raises SystemExit on a hit."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
        tmp = f.name
    try:
        r = run([sys.executable, str(LEAK_GATE), tmp])
    finally:
        os.unlink(tmp)
    if r.returncode != 0:
        raise SystemExit(f"handoff: leak gate blocked the body:\n{r.stdout}{r.stderr}")


def existing_issue(repo: str, title: str, run) -> str | None:
    # A plain list, not `--search`: GitHub's search index lags issue creation by seconds, and a
    # re-run inside that window opened a duplicate once. The list endpoint is read-after-write.
    r = run(["gh", "issue", "list", "--repo", repo, "--state", "all", "--json", "title,url", "--limit", "500"])
    if r.returncode != 0:
        raise SystemExit(f"handoff: gh issue list failed for {repo}: {r.stderr.strip()}")
    try:
        rows = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        rows = []
    for row in rows:
        if row.get("title") == title:
            return row.get("url")
    return None


def open_issue(repo: str, title: str, body: str, labels: list[str], run) -> str:
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for lab in labels:
        cmd += ["--label", lab]
    r = run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"handoff: gh issue create failed for {repo}: {r.stderr.strip()}")
    return (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""


def existing_pr(repo: str, branch: str, run) -> str | None:
    r = run(["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "all", "--json", "url", "--limit", "5"])
    if r.returncode != 0:
        raise SystemExit(f"handoff: gh pr list failed for {repo}: {r.stderr.strip()}")
    try:
        rows = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        rows = []
    return rows[0].get("url") if rows else None


def open_pr(repo: str, branch: str, rel_path: str, title: str, body: str, run) -> str:
    """Shallow clone, write the note, push the branch, open the PR. One temp dir per lane."""
    work = Path(tempfile.mkdtemp(prefix="mimir-handoff-"))
    steps = [
        ["gh", "repo", "clone", repo, str(work), "--", "--depth", "1", "--quiet"],
        ["git", "-C", str(work), "checkout", "-b", branch],
    ]
    for cmd in steps:
        r = run(cmd)
        if r.returncode != 0:
            raise SystemExit(f"handoff: {' '.join(cmd[:3])} failed for {repo}: {r.stderr.strip()}")
    target = work / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    steps = [
        ["git", "-C", str(work), "add", rel_path],
        ["git", "-C", str(work), "-c", "user.name=mimir handoff", "-c", "user.email=mimir@users.noreply.github.com",
         "commit", "-m", title, "-q"],
        ["git", "-C", str(work), "push", "-u", "origin", branch, "--quiet"],
        ["gh", "pr", "create", "--repo", repo, "--head", branch, "--title", title, "--body", body],
    ]
    out = ""
    for cmd in steps:
        r = run(cmd)
        if r.returncode != 0:
            raise SystemExit(f"handoff: {' '.join(cmd[:3])} failed for {repo}: {r.stderr.strip()}")
        out = r.stdout or out
    return out.strip().splitlines()[-1] if out.strip() else ""


# ----------------------------------------------------------------------------- ledger

def load_ledger(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------------- main

def uncommitted_outputs(run, pickup_dir: Path = PICKUP_DIR) -> list[str]:
    """Porcelain lines for the pickup dir and the VERDICTS.md beside it (empty = committed or not a git checkout)."""
    base = Path(pickup_dir).resolve().parent
    try:
        r = run(["git", "-C", str(base), "status", "--porcelain", "--", "VERDICTS.md", Path(pickup_dir).name])
    except Exception:  # noqa: BLE001
        return []
    if r.returncode != 0:
        return []
    return [l for l in (r.stdout or "").splitlines() if l.strip()]


def handoff(cfg: dict, triage: str, *, dry_run: bool = False, only_lane: str | None = None, allow_dirty: bool = False,
            pickup_dir: Path = PICKUP_DIR, ledger_dir: Path = LEDGER_DIR, run=default_run,
            out=print) -> dict:
    """Returns {'sent': [...], 'skipped': [...], 'unmapped': [...], 'none': bool}."""
    hcfg = handoff_config(cfg)
    lanes = lanes_by_id(cfg)
    blocks = blocks_for(pickup_dir, triage, only_lane)
    result = {"sent": [], "skipped": [], "unmapped": [], "none": not blocks}
    if not blocks:
        out(f"[handoff] no pickup block from triage {triage}" + (f" in lane {only_lane}" if only_lane else "") + "; nothing to hand off")
        return result

    if not dry_run and not allow_dirty:
        dirty = uncommitted_outputs(run, pickup_dir)
        if dirty:
            raise SystemExit("handoff: VERDICTS.md / pickup/ have uncommitted changes; the notes link to main. "
                             "Commit and push first, or pass --allow-dirty:\n  " + "\n  ".join(dirty))
    ledger_path = ledger_dir / f"{triage}.json"
    ledger = load_ledger(ledger_path)
    src = source_url(hcfg, run)

    for lane_id, block in blocks.items():
        lane = lanes.get(lane_id)
        if lane is None:
            out(f"::warning::[handoff] pickup/{lane_id}.md has no lane `{lane_id}` in radar.yaml; skipped")
            result["unmapped"].append(lane_id)
            continue
        repo = resolve_repo(lane, hcfg)
        if repo is None:
            out(f"::warning::[handoff] lane `{lane_id}` repo {lane.get('repo')!r} is not in handoff.repos; skipped")
            result["unmapped"].append(lane_id)
            continue
        if lane_id in ledger:
            out(f"[handoff] {lane_id} → {repo}: already handed off ({ledger[lane_id].get('url', '?')}); skipped")
            result["skipped"].append(lane_id)
            continue

        title = title_for(triage, lane_id)
        body = render_body(lane_id, lane, block, triage, src, hcfg.get("verdicts_url"))
        branch = f"mimir/pickup-{triage}-{lane_id}"
        rel_path = f"{hcfg['pr_path']}/{triage}-{lane_id}.md"

        if dry_run:
            out(f"\n[handoff] DRY RUN {hcfg['mode']} → {repo}\n  title: {title}" +
                (f"\n  branch: {branch}\n  file:   {rel_path}" if hcfg["mode"] == "pr" else "") +
                "\n" + "\n".join("  | " + l for l in body.splitlines()))
            result["sent"].append(lane_id)
            continue

        gate_body(body, run)
        if hcfg["mode"] == "issue":
            url = existing_issue(repo, title, run)
            if url:
                out(f"[handoff] {lane_id} → {repo}: issue already exists ({url}); recorded, not reopened")
                ledger[lane_id] = {"repo": repo, "kind": "issue", "url": url, "at": _now(), "note": "pre-existing"}
                save_ledger(ledger_path, ledger)
                result["skipped"].append(lane_id)
                continue
            url = open_issue(repo, title, body, hcfg["labels"], run)
            kind = "issue"
        else:
            url = existing_pr(repo, branch, run)
            if url:
                out(f"[handoff] {lane_id} → {repo}: PR already exists ({url}); recorded, not reopened")
                ledger[lane_id] = {"repo": repo, "kind": "pr", "url": url, "at": _now(), "note": "pre-existing"}
                save_ledger(ledger_path, ledger)
                result["skipped"].append(lane_id)
                continue
            url = open_pr(repo, branch, rel_path, title, body, run)
            kind = "pr"
        ledger[lane_id] = {"repo": repo, "kind": kind, "url": url, "at": _now()}
        save_ledger(ledger_path, ledger)  # after every send, so a later failure loses nothing
        out(f"[handoff] {lane_id} → {repo}: {kind} opened {url}")
        result["sent"].append(lane_id)

    out(f"[handoff] {triage}: {len(result['sent'])} {'would be ' if dry_run else ''}sent, "
        f"{len(result['skipped'])} already done, {len(result['unmapped'])} unmapped")
    return result


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", required=True, help="triage date whose pickup blocks to hand off (YYYY-MM-DD)")
    ap.add_argument("--lane", help="only this lane id")
    ap.add_argument("--dry-run", action="store_true", help="print every note, send nothing, write no ledger")
    ap.add_argument("--allow-dirty", action="store_true", help="send even if VERDICTS.md / pickup/ are uncommitted")
    ap.add_argument("--pickup-dir", type=Path, default=PICKUP_DIR,
                    help="read pickup/<lane>.md blocks from here instead of the repo's pickup/ (demos, tests)")
    ap.add_argument("--ledger-dir", type=Path, default=LEDGER_DIR,
                    help="write the sent-ledger here instead of data/handoff/")
    a = ap.parse_args(argv)
    try:
        date.fromisoformat(a.date)
    except ValueError:
        ap.error("--date must be YYYY-MM-DD")
    sys.path.insert(0, str(ROOT / "scripts"))
    import radar_config  # noqa: E402
    cfg = radar_config.load()
    if not cfg:
        print("handoff: no radar.yaml found (set RADAR_YAML or copy radar.example.yaml)", file=sys.stderr)
        return 1
    try:
        res = handoff(cfg, a.date, dry_run=a.dry_run, only_lane=a.lane, allow_dirty=a.allow_dirty,
                      pickup_dir=a.pickup_dir, ledger_dir=a.ledger_dir)
    except SystemExit as e:
        if e.code and not isinstance(e.code, int):
            print(e.code, file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
