"""
update_rolling_summary.py - Maintain a compressing, always-current running
summary of each corpus novel's plot, for use as premise-generation grounding.

WHY THIS EXISTS: extract_v3 already writes a per-chapter `summary` field
(2-5 sentences, 99.9% populated across the corpus — confirmed by direct
audit) into every deltas_v3/chNN.json, but nothing ever chains those into a
single running account of "what has this novel's story actually done so
far." narrative_genome.json's `description` is a one-paragraph PATTERN
synthesis (recurring structural tropes), not a plot chronology — a
genuinely different kind of compression. novel_metadata.json's `premise`
field is a short, separately-written hook line (often empty — 2/18 novels
had it blank at the time this was built). Premise generation
(_pick_corpus_samples in NovelTeaApp/backend/routers/generate.py) had NO
access to actual plot-chronology data before this.

ADDITIVE ONLY: this script only ever READS deltas_v3/*.json (never writes to
it or any other existing corpus file) and writes exactly one new file per
novel, novels/<id>/rolling_summary.json. Nothing existing is touched,
modified, or deleted.

MECHANICS — rolling LLM merge, not fixed-batch:
  For each newly-merged chapter since last_chapter_folded, one LLM call:
  (current running summary) + (this chapter's summary) -> updated running
  summary. No length cap (author's explicit call) — the model's own
  summarization judgment naturally compresses less-central earlier material
  as the story grows, rather than being forced under a word ceiling.

  Periodic full rebuild every REBUILD_EVERY chapters (default 100): instead
  of another incremental fold, re-read EVERY chapter summary from scratch
  and rebuild the running summary in one pass. Self-corrects any drift an
  incremental-only approach would otherwise compound forever (an early
  mistake folded in at chapter 5 would otherwise never get revisited across
  hundreds of later updates) — same self-correction philosophy as
  narrative_genome.json's periodic staleness-triggered refresh, just on a
  fixed chapter-count cadence instead of a size-delta threshold (a genome
  reads pattern-level signal that doesn't shift much chapter-to-chapter; a
  plot chronology needs a firmer, more frequent correction point).

Usage:
    python update_rolling_summary.py --novel my_novel
    python update_rolling_summary.py                              # every novel
    python update_rolling_summary.py --novel X --rebuild           # force a full rebuild now

No-args mode matches every other pipeline script's convention (bare script =
process every novel, corpus_builder.py's dashboard launches it that way).
"""

import json
import re
import argparse
import time
from pathlib import Path

NOVELS_DIR = Path(__file__).parent / "novels"
REBUILD_EVERY = 100   # chapters since last full rebuild before the next one triggers

_CH_FILENAME_RE = re.compile(r"^ch(\d+)\.json$")


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _chapter_summaries(novel_id: str) -> dict:
    """{chapter_number: summary_text} for every REAL chapter delta (skips
    engine-comparison/backup test artifacts like ch3.compare-nemotron.json,
    ch51.claude.json, ch18.json.bak — confirmed present in the corpus this
    session, same filename guard as build_knowledge_index.py's summary
    category and the style_dna_refinements backfill script needed)."""
    deltas_dir = NOVELS_DIR / novel_id / "deltas_v3"
    out = {}
    if not deltas_dir.exists():
        return out
    for f in deltas_dir.glob("ch*.json"):
        m = _CH_FILENAME_RE.match(f.name)
        if not m:
            continue
        d = load_json(f, {}) or {}
        if not isinstance(d, dict):
            continue
        s = str(d.get("summary") or "").strip()
        if s:
            out[int(m.group(1))] = s
    return out


def _rolling_path(novel_id: str) -> Path:
    return NOVELS_DIR / novel_id / "rolling_summary.json"


def _load_state(novel_id: str) -> dict:
    existing = load_json(_rolling_path(novel_id), None)
    if existing and isinstance(existing, dict):
        return existing
    return {
        "schema_version": "1.0",
        "novel_id": novel_id,
        "summary": "",
        "last_chapter_folded": 0,
        "last_rebuild_chapter": 0,
        "updated_at": None,
    }


def folded_set(state: dict, chapters) -> set:
    """The chapters already inside the running summary. New format: state["folded_chapters"]. Older state only has the marker
    last_chapter_folded, which proves nothing when chapters were extracted out of order (a novel with ch1-124 and ch224-301
    has marker 301, and ch105-123 extracted afterwards sit BELOW it and were never folded). So the old marker is trusted only
    when it covers a straight run 1..N of chapters we have; otherwise nothing is assumed folded and the summary is rebuilt."""
    fs = state.get("folded_chapters")
    if isinstance(fs, list):
        return {int(x) for x in fs}
    marker = state.get("last_chapter_folded", 0) or 0
    legacy = {c for c in chapters if c <= marker}
    return legacy if legacy == set(range(1, marker + 1)) else set()


def _save_state(novel_id: str, state: dict):
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _rolling_path(novel_id).write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


FOLD_SYSTEM = """You maintain a running plot summary of an ongoing web novel, updated one chapter at a time.
You will be given the CURRENT summary (everything that has happened so far, already compressed) and the
NEW CHAPTER's own summary. Produce an UPDATED summary that folds the new chapter's events into the
existing narrative coherently — a reader who has only read your updated summary should understand the
full story so far, including this new chapter's events.

Rules:
- Integrate, don't just append. Weave the new events into the existing narrative flow.
- Naturally compress less-central earlier material as the story accumulates more chapters — later,
  more significant events deserve more detail than something minor from many chapters ago that no
  longer matters to the current plot. Use your own judgment about what still matters.
- Keep named characters, factions, and central mechanics/hooks consistent with what's already stated.
- Write in plain prose, third person, present or past tense (match whatever the current summary already
  uses). No headers, no bullet points, no chapter-by-chapter breakdown — one continuous narrative.
- Output ONLY the updated summary text. No commentary, no labels."""

FOLD_MANY_SYSTEM = FOLD_SYSTEM.replace(
    "NEW CHAPTER's own summary", "NEW CHAPTERS' own summaries (several, in reading order)").replace(
    "fold the new chapter's events", "fold ALL the new chapters' events, in order,").replace(
    "including this new chapter's events", "including every new chapter's events")

FOLD_BATCH = 5   # chapters folded into the running summary per call (was one call per chapter)

REBUILD_SYSTEM = """You are writing a single running plot summary of a web novel from its complete
chapter-by-chapter summary log. Read every chapter summary below IN ORDER and produce ONE coherent
narrative summary of the whole story so far.

Rules:
- This is a full rebuild from scratch — ignore any prior summary, work only from the chapter log below.
- Naturally compress less-central material — early chapters that set up something later abandoned, minor
  side incidents — while preserving the throughline: protagonist's situation, central conflict, major
  turns, and the current state of the story.
- Write in plain prose, third person. No headers, no bullet points, no chapter-by-chapter breakdown.
- Output ONLY the summary text. No commentary, no labels."""


def unwrap_summary(text: str) -> str:
    """The Nemotron path returns JSON-shaped replies even when the prompt asks for
    plain prose — a run over the corpus stored '{ "summary": "..." }' as the
    summary text in all 18 novels. Pull the prose back out. Falls back to
    stripping the wrapper by hand when the reply isn't strictly valid JSON (one
    novel's had an unescaped quote inside), and returns plain text untouched."""
    s = (text or "").strip()
    if not s.startswith("{"):
        return s
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and isinstance(obj.get("summary"), str):
            return obj["summary"].strip()
    except Exception:
        pass
    m = re.match(r'^\{\s*"summary"\s*:\s*"(.*)"\s*\}?\s*$', s, re.S)
    if m:
        inner = m.group(1)
        try:
            return json.loads('"' + inner + '"').strip()
        except Exception:
            return inner.replace('\\n', '\n').replace('\\"', '"').strip()
    return s


_POOL = None     # set by main() while the agents run


def _live(novel_id: str, kind: str, preview: str):
    """Tell the Corpus Pipeline page what this job is doing right now (same
    llm_client.write_live_status every other pipeline script uses). Never lets
    a status-file hiccup break a summary run."""
    try:
        if _POOL is not None:       # agent row on the card (see agent_pool.py)
            _POOL.step(kind, preview[:160])
            return
        from llm_client import write_live_status
        write_live_status("rolling_summary", novel=novel_id, kind=kind, preview=preview[:200])
    except Exception:
        pass


def _fold_chapter(current_summary: str, chapter_num: int, chapter_summary: str, novel_id: str) -> str:
    from llm_client import call_llm
    _live(novel_id, "fold", f"ch{chapter_num}: {chapter_summary}")
    user = (
        f"CURRENT SUMMARY:\n{current_summary if current_summary else '(none yet — this is the first chapter)'}\n\n"
        f"NEW CHAPTER (Chapter {chapter_num}) SUMMARY:\n{chapter_summary}\n\n"
        f"Produce the updated running summary."
    )
    return unwrap_summary(call_llm(system=FOLD_SYSTEM, user=user, max_tokens=4000, temperature=0.3))


def _fold_chapters(current_summary: str, items: list, novel_id: str) -> str:
    """items: [(chapter_num, summary)] in reading order, folded in ONE call. One chapter keeps the original prompt."""
    if len(items) == 1:
        return _fold_chapter(current_summary, items[0][0], items[0][1], novel_id)
    from llm_client import call_llm
    _live(novel_id, "fold", f"ch{items[0][0]}-{items[-1][0]} ({len(items)} chapters in one call)")
    block = "\n\n".join(f"Chapter {ch}: {s}" for ch, s in items)
    user = (
        f"CURRENT SUMMARY:\n{current_summary if current_summary else '(none yet - these are the first chapters)'}\n\n"
        f"NEW CHAPTERS ({len(items)}, in order), each with its own summary:\n\n{block}\n\n"
        f"Produce the updated running summary."
    )
    return unwrap_summary(call_llm(system=FOLD_MANY_SYSTEM, user=user, max_tokens=4500, temperature=0.3))


def _rebuild_from_scratch(novel_id: str, summaries: dict) -> str:
    from llm_client import call_llm
    ordered = sorted(summaries.items())
    _live(novel_id, "rebuild", f"full rebuild from {len(ordered)} chapter summaries (ch{ordered[0][0]}-{ordered[-1][0]})")
    log_text = "\n\n".join(f"Chapter {ch}: {s}" for ch, s in ordered)
    user = f"CHAPTER SUMMARY LOG ({len(ordered)} chapters):\n\n{log_text}\n\nProduce the running summary."
    return unwrap_summary(call_llm(system=REBUILD_SYSTEM, user=user, max_tokens=6000, temperature=0.3))


def update_novel(novel_id: str, force_rebuild: bool = False):
    summaries = _chapter_summaries(novel_id)
    if not summaries:
        print(f"[SKIP] {novel_id}: no chapter summaries found")
        return

    state = _load_state(novel_id)
    max_chapter = max(summaries.keys())
    last_rebuild = state.get("last_rebuild_chapter", 0)
    folded = folded_set(state, summaries.keys())
    pending = sorted(c for c in summaries if c not in folded)
    # a chapter that belongs BEFORE chapters already in the summary (extracted later, numbered lower): folding it on the end
    # would put it out of order, so the summary is rebuilt from the whole log instead
    gap_fill = bool(folded) and bool(pending) and min(pending) < max(folded)
    untrusted = (not folded) and bool(state.get("summary"))      # an old summary we cannot tell the contents of

    should_rebuild = force_rebuild or (max_chapter - last_rebuild) >= REBUILD_EVERY or gap_fill or (untrusted and bool(pending))

    if should_rebuild:
        why = ("forced" if force_rebuild else
               f"{len([c for c in pending if c < max(folded)])} chapter(s) extracted out of order, below ch{max(folded)}" if gap_fill else
               "the old summary's contents cannot be verified" if untrusted else
               f"{max_chapter - last_rebuild} chapters since last rebuild")
        print(f"[{novel_id}] full rebuild — {len(summaries)} chapters ({why})")
        try:
            new_summary = _rebuild_from_scratch(novel_id, summaries)
        except Exception as e:
            print(f"  [ERROR] rebuild failed: {str(e)[:200]}")
            return
        state["summary"] = new_summary
        state["last_chapter_folded"] = max_chapter
        state["last_rebuild_chapter"] = max_chapter
        state["folded_chapters"] = sorted(summaries)
        _save_state(novel_id, state)
        print(f"  [OK] rebuilt through ch{max_chapter}, {len(new_summary)} chars")
        return

    if "folded_chapters" not in state and folded:          # a trusted old marker: record it in the new format (no LLM call)
        state["folded_chapters"] = sorted(folded)
        _save_state(novel_id, state)

    # Incremental: fold in every chapter after last_chapter_folded, in order.
    to_fold = pending
    if not to_fold:
        print(f"[{novel_id}] up to date ({len(folded)} chapters folded, through ch{max(folded) if folded else 0})")
        return

    print(f"[{novel_id}] folding in {len(to_fold)} new chapter(s): ch{to_fold[0]}-{to_fold[-1]}")
    current = unwrap_summary(state.get("summary", ""))   # tolerate a file saved before unwrapping existed
    # Chunks of up to FOLD_BATCH chapters, sized evenly (10 chapters -> 2 calls of 5; 12 -> 3 calls of 4), one call each.
    n_chunks = -(-len(to_fold) // FOLD_BATCH)
    size, extra = divmod(len(to_fold), n_chunks)
    chunks, i = [], 0
    for k in range(n_chunks):
        j = i + size + (1 if k < extra else 0)
        chunks.append(to_fold[i:j])
        i = j
    for chunk in chunks:
        first, last = chunk[0], chunk[-1]
        try:
            current = _fold_chapters(current, [(c, summaries[c]) for c in chunk], novel_id)
        except Exception as e:
            print(f"  [ERROR] ch{first}-{last} fold failed: {str(e)[:200]} — stopping, {first - 1} folded this run")
            break
        state["summary"] = current
        state["last_chapter_folded"] = max(last, state.get("last_chapter_folded", 0) or 0)
        state["folded_chapters"] = sorted(set(state.get("folded_chapters") or folded) | set(chunk))
        _save_state(novel_id, state)   # save after EVERY call — resumable if interrupted, matches
                                        # extract_v3's per-chapter checkpoint discipline
        print(f"  [OK] ch{first}-{last} folded ({len(chunk)} in one call), {len(current)} chars")


def main():
    parser = argparse.ArgumentParser(description="Maintain rolling_summary.json for one or every corpus novel")
    parser.add_argument("--novel", help="Novel ID (folder name in novels/) — omit to process every novel")
    parser.add_argument("--rebuild", action="store_true", help="Force a full rebuild now (only meaningful with --novel)")
    args = parser.parse_args()

    novel_ids = [args.novel] if args.novel else sorted(p.name for p in NOVELS_DIR.iterdir() if p.is_dir())
    # Same agent method as Chapter Mechanics: one agent per Nvidia key, one novel each (a novel's folds stay in order).
    global _POOL
    from agent_pool import AgentPool
    from llm_client import current_model_label
    todo = []
    for nid in novel_ids:
        if not (NOVELS_DIR / nid).is_dir():
            print(f"[SKIP] {nid}: not a novel directory")
            continue
        todo.append({"novel": nid, "unit": "summary"})
    _POOL = AgentPool("rolling_summary", model=current_model_label(None), want=4)
    _POOL.run(todo, lambda it: update_novel(it["novel"], force_rebuild=args.rebuild and bool(args.novel)))


if __name__ == "__main__":
    main()
