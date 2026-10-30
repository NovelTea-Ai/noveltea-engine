import os
"""
repair_style_dna.py - Backfill style_dna.content_ratios / pacing_markers /
stylistic_devices / vocabulary_markers / character_catchphrases /
distinctive_style_markers for any delta whose extraction predates the
SPLIT_GROUPS fix (extract_v3.py's "voice" group now requests
style_dna_refinements — previously it was a documented-but-dead schema field
never actually requested from any engine, leaving these style_dna sub-fields
hardcoded at 0/[]/{} forever regardless of which model ran the extraction;
confirmed present in 725/1489 delta files at the time this was built — 49%
of the corpus, across 15 of 18 novels).

Detection: a delta is "affected" if style_dna.content_ratios is present but
every value in it is exactly 0.0 — the fingerprint of the bug (the script
never populates it, so it stays at the schema's hardcoded default). This is
a live scan, not a pre-computed list, so re-running this script later (e.g.
after a similar future bug) picks up whatever's actually broken at that
moment rather than a stale snapshot.

Engine: by default, uses whatever engine the app currently has selected
(generation.agent_engine in ~/.noveltea-engine/config.json) — same as every other
generation action in the app, via repair_chapter_fields -> call_llm's normal
resolution. Pass --nemotron-only to force Nemotron regardless of the app's
selection instead (author's own override, off by default) — this was this
script's ORIGINAL hardcoded behavior, kept as an opt-in: Codex's pooled-
account OAuth tokens expire in ~1hr and need re-login, which broke an
earlier Codex-primary run partway through and stalled the app's own Corpus
Builder extraction job at the same time (both draw on the same account
pool), while Nemotron ran the whole 700+-chapter backfill this script is
based on without a single failure once switched to. When --nemotron-only IS
passed, generation.agent_engine is still reverted to its original value
after every single call, success or failure, so a run never leaves the live
app on a different engine than the author had selected — the override is
about which engine DOES the repair work, not about permanently changing the
user's live setting. When --nemotron-only is NOT passed (the default), the
app's own selection is never touched at all — there's nothing to revert.

Resumable: writes progress to repair_style_dna_progress.json (next to this
script) after every chapter, so a Ctrl-C or crash partway through can just
be re-run and it'll skip what's done — matches extract_v3's own
per-chapter checkpoint discipline.

Usage:
    python repair_style_dna.py                    # scan + repair every novel, using the app's selected engine
    python repair_style_dna.py --nemotron-only     # force Nemotron regardless of the app's selection
    python repair_style_dna.py --novel my_novel
    python repair_style_dna.py --dry-run           # report scope, fix nothing
"""

import json
import argparse
import re
import time
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"
CONFIG_PATH = Path.home() / ".noveltea-engine" / "config.json"
PROGRESS_PATH = Path(__file__).parent / "repair_style_dna_progress.json"

_CH_FILENAME_RE = re.compile(r"^ch(\d+)\.json$")

REPAIR_ENGINE = "nemotron"   # only used when --nemotron-only is passed — see the module docstring's "Engine:" section


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def set_engine(engine: str):
    cfg = read_config()   # re-read fresh each time — never clobber a concurrent write
    cfg.setdefault("generation", {})["agent_engine"] = engine
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def find_affected(novel_filter: str = None) -> list:
    """[(novel_id, chapter_num, path)] for every real (non-test-artifact)
    delta whose style_dna.content_ratios is present but all-zero."""
    out = []
    novel_dirs = [NOVELS_DIR / novel_filter] if novel_filter else sorted(NOVELS_DIR.iterdir())
    for nd in novel_dirs:
        if not nd.is_dir():
            continue
        deltas_dir = nd / "deltas_v3"
        if not deltas_dir.exists():
            continue
        for f in deltas_dir.glob("ch*.json"):
            m = _CH_FILENAME_RE.match(f.name)
            if not m:
                continue   # skip engine-comparison/backup test artifacts (ch3.compare-nemotron.json etc.)
            d = load_json(f, {}) or {}
            if not isinstance(d, dict):
                continue
            cr = (d.get("style_dna") or {}).get("content_ratios")
            if isinstance(cr, dict) and cr and all(v == 0.0 for v in cr.values()):
                out.append((nd.name, int(m.group(1)), f))
    return out


def _load_progress() -> dict:
    p = load_json(PROGRESS_PATH, None)
    return p if isinstance(p, dict) else {"done": [], "failed": [], "fallback_used": []}


def _save_progress(progress: dict):
    PROGRESS_PATH.write_text(json.dumps(progress, indent=2), encoding="utf-8")


def repair_one(novel_id: str, ch_num: int) -> tuple:
    """Returns (ok, error_message). Runs on whatever engine is currently live
    (the app's own selection, or Nemotron if --nemotron-only forced it via
    set_engine() before this call — this function itself is engine-agnostic,
    it just calls repair_chapter_fields and lets call_llm resolve normally)."""
    import extract_v3
    try:
        extract_v3.repair_chapter_fields(novel_id, ch_num, ["style_dna_refinements"])
        return True, ""
    except Exception as e:
        return False, str(e)[:200]


def main():
    parser = argparse.ArgumentParser(description="Backfill style_dna_refinements for affected corpus chapters")
    parser.add_argument("--novel", help="Restrict to one novel ID — omit to scan the whole corpus")
    parser.add_argument("--dry-run", action="store_true", help="Report scope only, fix nothing")
    parser.add_argument("--nemotron-only", action="store_true",
                        help="Force Nemotron regardless of the app's currently-selected engine "
                             "(reverted after every call — see the module docstring's 'Engine:' section)")
    args = parser.parse_args()

    affected = find_affected(args.novel)
    print(f"Found {len(affected)} affected chapter(s)"
          + (f" in {args.novel}" if args.novel else " across the corpus"))
    if args.dry_run or not affected:
        by_novel = {}
        for nid, _, _ in affected:
            by_novel[nid] = by_novel.get(nid, 0) + 1
        for nid, count in sorted(by_novel.items(), key=lambda x: -x[1]):
            print(f"  {nid}: {count}")
        return

    progress = _load_progress()
    done_keys = set(progress.get("done", []))
    remaining = [(n, c, p) for n, c, p in affected if f"{n}/ch{c}" not in done_keys]
    # "already done (this scan)" is near-always 0 by construction, not a bug:
    # a chapter that's genuinely fixed no longer shows up in `affected` at
    # all (find_affected() re-scans live content_ratios each run), so it can
    # never be BOTH in `affected` AND in `done_keys` at the same time except
    # in the rare case of a chapter that was marked done, then somehow
    # reverted to broken. Report total historical progress (done_keys size)
    # separately so "my past runs aren't being tracked" reads correctly as
    # "they ARE — that's why `affected` shrank" instead of looking like 0
    # progress every single run. Confirmed live: this line used to just say
    # "Already done: 0" even after 138 real prior fixes, which repeatedly
    # read as a bug report to the author until the actual math was traced.
    overlap = len(affected) - len(remaining)
    print(f"Total fixed in past runs: {len(done_keys)} (already reflected in the {len(affected)} count above — "
          f"a fixed chapter drops out of the live scan entirely, so it can't show up here again)")
    print(f"Already done (this scan, should normally be 0 — see comment): {overlap} | remaining: {len(remaining)}")

    if args.nemotron_only:
        os.environ["NM_FORCE_ENGINE"] = REPAIR_ENGINE      # pins this process to Nemotron; the app's settings file is not touched
    original_cfg = read_config()
    original_engine = (original_cfg.get("generation") or {}).get("agent_engine", REPAIR_ENGINE)
    if args.nemotron_only:
        print(f"Engine: {REPAIR_ENGINE} (--nemotron-only override — app's own selection is {original_engine}, "
              f"left untouched: only this run is pinned to Nemotron)")
    else:
        print(f"Engine: {original_engine} (the app's currently-selected engine — untouched by this run)")

    t_start = time.time()
    for i, (novel_id, ch_num, _path) in enumerate(remaining, 1):
        key = f"{novel_id}/ch{ch_num}"
        print(f"\n[{i}/{len(remaining)}] {novel_id} ch{ch_num} ...", flush=True)
        ok, err = repair_one(novel_id, ch_num)

        if ok:
            done_list = progress.setdefault("done", [])
            if key not in done_list:
                done_list.append(key)
            # A chapter that now succeeds shouldn't stay listed as failed
            # forever from an earlier attempt — confirmed live this could
            # happen: a chapter fails once (e.g. a transient network blip),
            # gets recorded in "failed", then a later run (this one) retries
            # it successfully, but the stale "failed" entry lingered,
            # misreporting it as still broken.
            failed_list = progress.get("failed", [])
            if key in failed_list:
                failed_list.remove(key)
            print(f"  OK")
        else:
            failed_list = progress.setdefault("failed", [])
            if key not in failed_list:
                failed_list.append(key)
            print(f"  FAILED: {err}")
        _save_progress(progress)

        elapsed = time.time() - t_start
        eta_min = (len(remaining) - i) / (i / elapsed) / 60 if elapsed > 0 and i > 0 else 0
        print(f"  progress: {i}/{len(remaining)} this run | ETA {eta_min:.0f} min")

    done_n = len(progress.get("done", []))
    failed_n = len(progress.get("failed", []))
    print(f"\nDone. {done_n} succeeded, {failed_n} failed.")
    if progress.get("failed"):
        print("Failed:")
        for k in progress["failed"]:
            print(f"  {k}")


if __name__ == "__main__":
    main()
