# mimir

Verdicts on new tech relative to your own repos, each with a reopen threshold. What it does, how to run it and the file layout are in
`README.md`.

```sh
python3 -m py_compile scripts/*.py && python3 -m unittest discover -s tests   # the test command (same as .github/workflows/ci.yml)
python3 scripts/leak_gate.py --secrets-only .                                 # the leak gate CI runs on the tree
```

## Lane args

`<HARNESS_DIR>` is `harness`: a pinned ignored clone, see laptop-scheduler README 'Build route'. Nothing under `harness/`,
`.claude/workflows/`, `.claude/agents/` or `.claude/worktrees/` is ever committed here (`.gitignore`); the clone and its links exist only
in a lane worktree. Pass the JSON below explicitly to the lane workflow; written in this file it does nothing. The commands are not
workflow keys; the caller writes them into `brief` and `successCriterion`.

- **test:** `python3 -m py_compile scripts/*.py && python3 -m unittest discover -s tests` (needs `requirements.txt`), green required
- **lint:** none · **build:** none · **default branch:** `main` · **design-audit:** off (no rendered UI)

```json
{
  "baseBranch": "main",
  "sensitivePaths": {
    "full": ["^scripts/leak_gate\\.py$", "^leakgate\\.example\\.txt$", "^\\.github/workflows/"]
  },
  "repoReviewers": [],
  "repoInvariants": [
    "This repo is public: no company, client or product name, personal identifier, internal file name or secret enters a committed file; the leak gate passes on every PR.",
    "Personal configuration (radar.yaml, leakgate.txt, evidence/<id>/) stays git-ignored; examples ship as *.example.* files."
  ],
  "repoLenses": {}
}
```
