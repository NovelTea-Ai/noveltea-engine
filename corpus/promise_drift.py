"""Promise Drift detection (V4 Phase 2, doc Layer 4 "Story Promise Engine").

Pure processing over data extract_v3.py already produces per chapter —
reader_psychology (payoff_categories, reader_emotions, tension_curve) and
novel_metadata_hints.genre_signals (aggregated per-novel into
novel_metadata.json's genre_signals: {signal: [chapter_numbers]}). No new
LLM extraction call; this only aggregates/compares what's already on disk.

genre_signals is free-vocabulary and — confirmed against real corpus data —
mostly one-off per-chapter tags (a 100-chapter novel can have 300+ distinct
signals), so literal tag-overlap is used only as a coarse/qualitative check,
never as the primary drift score. payoff_categories and reader_emotions use
a small fixed vocabulary and are far more reliable for comparison.

Usage: python promise_drift.py [novel_id ...]   (no args = every novel)
Output: novels/<id>/promises/drift_report.json
"""
import json
import sys
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"
WINDOW = 5          # rolling window size — matches query.get_tension_targets's lookback convention
DROP_THRESHOLD = 4  # a payoff/emotion scoring this much lower than baseline counts as "dropped"
EMERGE_THRESHOLD = 5


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _avg_dict(dicts: list) -> dict:
    """Average a list of {label: number} dicts, ignoring keys missing from a given dict."""
    sums, counts = {}, {}
    for d in dicts:
        for k, v in (d or {}).items():
            if isinstance(v, (int, float)):
                sums[k] = sums.get(k, 0) + v
                counts[k] = counts.get(k, 0) + 1
    return {k: round(sums[k] / counts[k], 1) for k in sums}


def compute_drift(novel_id: str) -> dict:
    root = NOVELS_DIR / novel_id
    psych = load_json(root / "reader_psychology" / "chapters.json", [])
    meta = load_json(root / "novel_metadata.json", {}) or {}
    if not isinstance(psych, list):
        psych = []
    psych = sorted((p for p in psych if isinstance(p, dict) and isinstance(p.get("chapter"), int)),
                    key=lambda p: p["chapter"])

    if len(psych) < WINDOW + 2:
        return {"novel_id": novel_id, "status": "insufficient_data", "chapters_available": len(psych)}

    baseline_ch = psych[0]
    recent_window = psych[-WINDOW:]

    # Invert the aggregate genre_signals dict ({signal: [chapters]}) to
    # chapter -> signals, once, rather than re-reading every delta file.
    genre_by_chapter: dict = {}
    for signal, chapters in (meta.get("genre_signals") or {}).items():
        if not isinstance(chapters, list):
            continue
        for ch in chapters:
            genre_by_chapter.setdefault(ch, []).append(signal)

    baseline_genres = set(genre_by_chapter.get(baseline_ch["chapter"], []))
    recent_genres = set()
    for p in recent_window:
        recent_genres |= set(genre_by_chapter.get(p["chapter"], []))
    genre_overlap = baseline_genres & recent_genres

    recent_avg_payoff = _avg_dict([p.get("payoff_categories") for p in recent_window])
    recent_avg_emotions = _avg_dict([p.get("reader_emotions") for p in recent_window])
    recent_avg_tension = _avg_dict([p.get("tension_curve") for p in recent_window])

    def _dropped(baseline_dict, recent_avg):
        out = []
        for k, v in (baseline_dict or {}).items():
            if not isinstance(v, (int, float)) or v < EMERGE_THRESHOLD:
                continue
            rv = recent_avg.get(k, 0)
            if v - rv >= DROP_THRESHOLD:
                out.append({"label": k, "baseline": v, "recent_avg": rv})
        return out

    def _emerged(baseline_dict, recent_avg):
        baseline_keys = set((baseline_dict or {}).keys())
        return [{"label": k, "recent_avg": v} for k, v in recent_avg.items()
                if k not in baseline_keys and v >= EMERGE_THRESHOLD]

    dropped_payoffs = _dropped(baseline_ch.get("payoff_categories"), recent_avg_payoff)
    emerged_payoffs = _emerged(baseline_ch.get("payoff_categories"), recent_avg_payoff)
    dropped_emotions = _dropped(baseline_ch.get("reader_emotions"), recent_avg_emotions)
    emerged_emotions = _emerged(baseline_ch.get("reader_emotions"), recent_avg_emotions)

    warnings = []
    if dropped_payoffs:
        warnings.append(
            f"Opening promised {', '.join(d['label'] for d in dropped_payoffs)} "
            f"— largely absent across the last {len(recent_window)} tracked chapters "
            f"({', '.join(str(p['chapter']) for p in recent_window)}).")
    if emerged_payoffs:
        warnings.append(
            f"Recent chapters lean into {', '.join(e['label'] for e in emerged_payoffs)} "
            f"— not part of chapter {baseline_ch['chapter']}'s opening promise.")
    if baseline_genres and not genre_overlap:
        warnings.append(
            f"None of chapter {baseline_ch['chapter']}'s genre signals "
            f"({', '.join(sorted(baseline_genres))}) recur in the recent window — possible tonal drift "
            f"(genre_signals is free-vocabulary and noisy — treat this as a hint to check manually, not a hard verdict).")

    return {
        "novel_id": novel_id,
        "status": "drift_detected" if warnings else "consistent",
        "baseline_chapter": baseline_ch["chapter"],
        "recent_window": [p["chapter"] for p in recent_window],
        "baseline_payoff_categories": baseline_ch.get("payoff_categories") or {},
        "recent_avg_payoff_categories": recent_avg_payoff,
        "baseline_reader_emotions": baseline_ch.get("reader_emotions") or {},
        "recent_avg_reader_emotions": recent_avg_emotions,
        "baseline_genre_signals": sorted(baseline_genres),
        "recent_genre_signals": sorted(recent_genres),
        "genre_signal_overlap": sorted(genre_overlap),
        "dropped_payoffs": dropped_payoffs,
        "emerged_payoffs": emerged_payoffs,
        "dropped_emotions": dropped_emotions,
        "emerged_emotions": emerged_emotions,
        "tension_shift": {"baseline": baseline_ch.get("tension_curve") or {}, "recent_avg": recent_avg_tension},
        "warnings": warnings,
    }


def main():
    novel_ids = sys.argv[1:] or [p.name for p in NOVELS_DIR.iterdir() if p.is_dir()]
    for novel_id in novel_ids:
        root = NOVELS_DIR / novel_id
        if not (root / "reader_psychology" / "chapters.json").exists():
            continue
        report = compute_drift(novel_id)
        out_dir = root / "promises"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "drift_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        status = report.get("status")
        n_warn = len(report.get("warnings", []))
        print(f"{novel_id}: {status}" + (f" ({n_warn} warning{'s' if n_warn != 1 else ''})" if n_warn else ""))


if __name__ == "__main__":
    main()
