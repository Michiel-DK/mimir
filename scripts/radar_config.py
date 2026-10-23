"""Load radar.yaml (the profile) so the fetchers read their subjects from it.

Every fetcher keeps a built-in default, so the scripts run without a radar.yaml;
with one present, the `sources` and `tracks` blocks override the defaults.
Set RADAR_YAML to point somewhere else.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_cache = None


def load(reload=False):
    """Return the profile dict (cached). reload=True re-reads RADAR_YAML."""
    global _cache
    if _cache is not None and not reload:
        return _cache
    p = Path(os.environ.get("RADAR_YAML") or ROOT / "radar.yaml")
    if not p.exists():
        _cache = {}
        return _cache
    try:
        import yaml  # PyYAML, in requirements.txt
    except ImportError as e:  # say so, loudly: a silent default would hide a misread profile
        raise SystemExit("radar_config: PyYAML missing (pip install -r requirements.txt)") from e
    _cache = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    print(f"[radar_config] profile: {p}")
    return _cache


def get(*keys, default=None):
    node = load()
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node
