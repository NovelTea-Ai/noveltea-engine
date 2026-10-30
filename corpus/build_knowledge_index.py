"""Build/refresh the corpus-wide semantic search index (V4 Phase 4).

Embeds ten kinds of chunks from every novel — reveals (with thread_type),
schemes, symbols (with meaning), glossary terms (techniques/skills/crafted
items), narrative patterns (with chapter_range/gen_guidance), prose samples,
dialogue lines, chapter summaries (the "what happened this chapter" record,
read directly from deltas_v3/ — see _collect_candidates' summary block for
why this one has no merged rollup file to read from instead), and antagonist
templates (recurring antagonist archetypes with real instance history) —
the categories that actually answer "find X across the corpus" style queries.

Incremental by design: existing_keys() reads what's already indexed for a
novel BEFORE embedding anything, so a re-run (e.g. after new chapters are
added via Corpus Builder) only pays the embedding-call cost for genuinely
NEW content — not the old "re-embed everything, let the DB silently
discard duplicates after the fact" behavior, which made even a same-novel
re-run cost as much as the first run.

Round-robin across novels (author's explicit call): earlier versions
finished one novel completely before starting the next, so a search only
had ONE novel's worth of material to draw from for hours at a time even
though 15 others were queued. This version collects every novel's candidate
chunks up front (pure JSON reads, no embedding cost), then embeds one chunk
per novel per round — every novel gets SOME coverage early, instead of one
novel finishing while the rest sit at zero.

Usage: python build_knowledge_index.py [novel_id ...]   (no args = every novel)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_index import init_db, store_chunk, embed_text, ollama_available, existing_keys
from llm_client import write_live_status
import chapter_lookup   # chapter of a record whose merged file lost it, read from deltas_v3/chN.json

NOVELS_DIR = Path(__file__).parent / "novels"


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _normalize_chapter(val):
    """setup_chapters is USUALLY a list of ints, but at least one real corpus
    record has it as a bare int instead — confirmed live: crashed the whole
    index build with "'int' object is not subscriptable" partway through
    my_novel, silently killing hours of progress on later
    novels. Accept either shape."""
    if isinstance(val, list):
        return val[0] if val else None
    return val


COMMIT_EVERY = 25   # progress visibility — used to all land in ONE commit at
                     # the very end, so a progress check could show zero for
                     # 5+ minutes despite real work happening (confirmed live).


def _collect_candidates(novel_dir: Path) -> list:
    """Scan every category for one novel and return candidate chunks as
    (category, text, chapter, meta) tuples — pure JSON reads, no embedding
    calls, so this is cheap to run for all 16 novels up front. Each record is
    wrapped in its own try/except: a single malformed record (unexpected type
    in a field) used to crash the entire multi-hour run — confirmed live —
    so one bad record is now a logged skip, never a lost run."""
    out = []

    # Reveals — thread_type gives real taxonomy to filter search results by
    for r in load_json(novel_dir / "reveals" / "log.json", []) or []:
        if not isinstance(r, dict) or not r.get("content"):
            continue
        try:
            text = f"{r.get('reveal_type', '')}: {r['content']}"
            chapter = (r.get("payoff_chapter") or _normalize_chapter(r.get("setup_chapters"))
                       or chapter_lookup.find(novel_dir, "reveal", r["content"]))
            out.append(("reveal", text, chapter,
                       {"thread_type": r.get("thread_type"), "impact": str(r.get("impact") or "")[:200]}))
        except Exception as e:
            print(f"  WARN reveal record skipped (malformed): {str(e)[:100]}")

    # Schemes
    for r in load_json(novel_dir / "schemes" / "instances.json", []) or []:
        if not isinstance(r, dict) or not r.get("goal"):
            continue
        try:
            text = f"{r['goal']} via {r.get('mechanism', '')}"
            out.append(("scheme", text, _normalize_chapter(r.get("setup_chapter")),
                       {"thread_type": r.get("thread_type"), "status": r.get("status", "")}))
        except Exception as e:
            print(f"  WARN scheme record skipped (malformed): {str(e)[:100]}")

    # Symbols — only genuinely symbolic mentions (has a meaning), not raw candidates
    for entry in load_json(novel_dir / "symbols" / "frequency.json", []) or []:
        if not isinstance(entry, dict):
            continue
        for m in entry.get("mentions", []):
            if not isinstance(m, dict):
                continue
            meaning = m.get("meaning")
            if not meaning:
                continue
            try:
                text = f"{entry.get('symbol', '')}: {meaning}"
                out.append(("symbol", text, _normalize_chapter(m.get("chapter")), {"symbol": entry.get("symbol")}))
            except Exception as e:
                print(f"  WARN symbol mention skipped (malformed): {str(e)[:100]}")

    # Glossary — techniques, skills, crafted items, cultivation realms, etc.
    # No clean category field exists yet (per the Phase 6 research finding —
    # a term/definition pair mixes all of these without a type marker), but
    # that doesn't matter for semantic search: the embedding captures what
    # the term IS regardless of a missing formal type, so "a fire-based
    # martial technique" or "a rare crafted weapon" can still be found.
    for t in load_json(novel_dir / "glossary" / "terms.json", []) or []:
        if not isinstance(t, dict) or not t.get("term") or not t.get("definition"):
            continue
        try:
            text = f"{t['term']}: {t['definition']}"
            out.append(("glossary", text, _normalize_chapter(t.get("first_seen_chapter")), {"term": t.get("term")}))
        except Exception as e:
            print(f"  WARN glossary record skipped (malformed): {str(e)[:100]}")

    # Narrative patterns — recurring structural beats (power_reveal, face_slap,
    # etc.) with their own chapter_range/escalation/gen_guidance. Previously
    # NEVER indexed at all: skeleton generation could only see patterns via
    # _pick_corpus_samples' blind 2-random-novel sample, which has no way to
    # find a pattern that actually fits THIS chapter's purpose — this makes
    # patterns reachable the same way reveals/schemes already are, searchable
    # by what the pattern IS, with chapter_range preserved in meta so a
    # matched pattern can point back to its real source chapters instead of
    # being pure abstract description.
    genome = load_json(novel_dir / "narrative_genome.json", {}) or {}
    genome_patterns = genome.get("patterns", genome if isinstance(genome, list) else [])
    for p in (genome_patterns or []):
        if not isinstance(p, dict) or not p.get("description"):
            continue
        try:
            text = f"{p.get('pattern_type', p.get('pattern_id', 'pattern'))}: {p['description']}"
            chrange = p.get("chapter_range")
            chapter = chrange[0] if isinstance(chrange, list) and chrange else None
            out.append(("pattern", text, chapter, {
                "pattern_id": p.get("pattern_id", ""),
                "pattern_type": p.get("pattern_type", ""),
                "chapter_range": chrange if isinstance(chrange, list) else None,
                "average_chapter_span": p.get("average_chapter_span"),
                "occurrences": p.get("occurrences"),
                "satisfaction": p.get("reader_satisfaction_on_payoff"),
                "gen_guidance": str(p.get("gen_guidance") or "")[:250],
            }))
        except Exception as e:
            print(f"  WARN pattern record skipped (malformed): {str(e)[:100]}")

    # Prose samples — actual excerpts, good for tone/scene-similarity search
    for s in load_json(novel_dir / "prose" / "samples.json", []) or []:
        if not isinstance(s, dict) or not s.get("excerpt"):
            continue
        try:
            text = s["excerpt"][:600]
            # the merged samples store it as source_chapter (reading "chapter" left every prose chunk without one)
            chapter = (_normalize_chapter(s.get("source_chapter") or s.get("chapter"))
                       or chapter_lookup.find(novel_dir, "prose", s["excerpt"]))
            out.append(("prose", text, chapter, {"type": s.get("type", "")}))
        except Exception as e:
            print(f"  WARN prose record skipped (malformed): {str(e)[:100]}")

    # Dialogue lines — entities/*.json's voice_dna.dialogue_samples. Real,
    # verbatim-reusable lines with WHO said them and WHY (voice_notes), so a
    # search for "a passage like THIS one" can find a character voice that
    # actually fits the moment, not just any random corpus line (what
    # Dialogue Shaping's _voice_dna_block was limited to before).
    entities_dir = novel_dir / "entities"
    if entities_dir.exists():
        for f in entities_dir.glob("*.json"):
            if f.stem.startswith("chapter_"):
                continue
            d = load_json(f, {}) or {}
            if not isinstance(d, dict):
                continue
            vd = d.get("voice_dna") or {}
            char_name = d.get("canonical_name", f.stem)
            for s in (vd.get("dialogue_samples") or []):
                if not isinstance(s, dict):
                    continue
                line = str(s.get("line") or "").strip()
                if not line:
                    continue
                try:
                    chapter = (_normalize_chapter(s.get("chapter"))
                               or chapter_lookup.find(novel_dir, "dialogue", line))
                    out.append(("dialogue", line, chapter,
                               {"character": char_name, "context": s.get("context", ""),
                                "voice_notes": str(s.get("voice_notes") or "")[:200]}))
                except Exception as e:
                    print(f"  WARN dialogue sample skipped (malformed, {f.name}): {str(e)[:100]}")

    # Antagonist templates — recurring antagonist archetypes with real
    # instance history and variation notes, merged corpus-wide into
    # templates/antagonists.json (see merge.py's merge_antagonist_templates).
    # Confirmed live: 515 templates across the corpus, genuinely rich data
    # (a real archetype pattern + which entities embodied it + how each
    # instance varied), extracted per-chapter and merged, but never indexed
    # for semantic search and never read by any generation prompt before
    # this — only a passive browse endpoint (corpus.py's /timeline-adjacent
    # antagonist view) read the merged file. Same size/shape class as
    # narrative patterns (323 rows) above, which already proved this
    # dedicated-block treatment works well — arc/chapter-skeleton planning
    # both design antagonists and had zero access to this.
    templates = load_json(novel_dir / "templates" / "antagonists.json", []) or []
    for t in templates:
        if not isinstance(t, dict) or not t.get("pattern"):
            continue
        try:
            instances = t.get("instances") or []
            first_chapter = None
            entity_names = []
            for inst in instances:
                if not isinstance(inst, dict):
                    continue
                if inst.get("entity"):
                    entity_names.append(inst["entity"])
                chs = inst.get("chapters")
                if isinstance(chs, list) and chs:
                    # Extraction sometimes emits a chapter as "5" (str) alongside ints
                    try:
                        c0 = int(chs[0])
                    except (TypeError, ValueError):
                        continue
                    if first_chapter is None or c0 < first_chapter:
                        first_chapter = c0
            text = f"{t.get('template_id', 'antagonist_pattern')}: {t['pattern']}"
            out.append(("antagonist_template", text, first_chapter, {
                "template_id": t.get("template_id", ""),
                "instance_count": len(instances),
                "entities": entity_names[:5],
                "variation_notes": str((instances[0].get("variation_notes") if instances and isinstance(instances[0], dict) else "") or "")[:250],
            }))
        except Exception as e:
            print(f"  WARN antagonist template skipped (malformed): {str(e)[:100]}")

    # Chapter summaries — the "what actually happened this chapter" record
    # (extract_v3's `summary` field, 2-5 sentences, 99.9% populated across
    # the corpus per the audit that led to this category being added), read
    # straight from deltas_v3/*.json rather than a merged rollup file like
    # the other seven categories — no merged summaries.json exists (nothing
    # aggregates this field today; see the rolling_summary.json pipeline for
    # the linear-narrative counterpart to this SEARCHABLE one). Lets a query
    # like "a chapter where the protagonist loses a mentor" surface actual
    # plot beats, which reveals/schemes/patterns don't cover (those are each
    # narrower slices — a reveal, a scheme, a recurring structural pattern —
    # not the chapter's overall events).
    deltas_dir = novel_dir / "deltas_v3"
    if deltas_dir.exists():
        for f in deltas_dir.glob("ch*.json"):
            # Same non-standard-filename guard as backfill_style_dna.py's
            # fix this session — ch3.compare-nemotron.json, ch51.claude.json
            # etc. are engine-comparison/backup test artifacts, not real
            # corpus chapters, and would otherwise get indexed as if they were.
            import re as _re
            if not _re.match(r"^ch\d+\.json$", f.name):
                continue
            d = load_json(f, {}) or {}
            if not isinstance(d, dict):
                continue
            summary = str(d.get("summary") or "").strip()
            if not summary:
                continue
            try:
                out.append(("summary", summary, d.get("chapter_number"),
                           {"chapter_title": d.get("chapter_title", ""),
                            "chapter_function": d.get("chapter_function", "")}))
            except Exception as e:
                print(f"  WARN summary record skipped (malformed, {f.name}): {str(e)[:100]}")

    # Story shape — the novel's WHOLE rolling plot summary (rolling_summary.json,
    # written by update_rolling_summary.py), one chunk per novel. Where the
    # "summary" category above matches single chapters, this matches the overall
    # shape of a story — used by the arc planner to see how comparable novels
    # actually progress. main() replaces a novel's old story_shape row when its
    # summary text changes (the file is periodically rebuilt), so stale versions
    # never pile up as duplicates.
    rolling = load_json(novel_dir / "rolling_summary.json", {}) or {}
    shape = str(rolling.get("summary") or "").strip() if isinstance(rolling, dict) else ""
    if shape:
        out.append(("story_shape", shape, None,
                    {"last_chapter_folded": rolling.get("last_chapter_folded")}))

    # The author's brain (build_author_brain.py): the author's own plan notes. One row per ARC (keyed by its first chapter, so a
    # chapter-range search finds the arcs at the same stage of a book), one per long-running THREAD (keyed by the chapter it was seeded:
    # truth, clues with chapters, misdirection, reveal), and one CRAFT row per novel (engine, book shape, author rules, conspiracy craft).
    out += author_brain_rows(novel_dir)
    return out


def author_brain_rows(novel_dir: Path) -> list:
    brain = load_json(novel_dir / "author_brain.json", {}) or {}
    if not isinstance(brain, dict) or not brain.get("arcs"):
        return []
    rows = []
    for a in brain.get("arcs") or []:
        ch = a.get("chapters") or [None, None]
        seeds = "; ".join(f"ch{x.get('chapter')} {x.get('thread')}: {x.get('what')}" for x in (a.get("seeds") or [])[:6])
        text = (f"Arc ch{ch[0]}-{ch[-1]} '{a.get('label')}'. Promise: {a.get('promise')} Plan: {a.get('plan')} Escalation: {a.get('escalation')} "
                f"Turn: {a.get('turn')} Payoff: {a.get('payoff')} Cost to the hero: {a.get('cost')}" + (f" Seeds for later: {seeds}" if seeds else ""))
        rows.append(("author_arc", text.strip(), _normalize_chapter(ch[0]), {"chapters": ch, "label": a.get("label")}))
    for t in brain.get("threads") or []:
        clues = "; ".join(f"ch{c.get('chapter')}: {c.get('reader_sees')}" for c in (t.get("clues") or [])[:8])
        rev = f"Revealed ch{t.get('reveal_chapter')}: {t.get('how_revealed')}" if t.get("reveal_chapter") else "Still hidden at the end of the extracted chapters."
        text = (f"[{t.get('kind')}] {t.get('name')}. Truth: {t.get('truth')} Seeded ch{t.get('seeded_chapter')}. Clues: {clues}. "
                f"Misdirection: {t.get('misdirection')} {rev} Effect: {t.get('payoff_effect')}")
        rows.append(("author_thread", text.strip(), _normalize_chapter(t.get("seeded_chapter")),
                     {"name": t.get("name"), "kind": t.get("kind"), "reveal_chapter": t.get("reveal_chapter")}))
    craft = " ".join(filter(None, [f"Engine: {brain.get('engine')}", f"Book shape: {brain.get('book_shape')}",
                                   "Author rules: " + " | ".join(brain.get("author_rules") or []),
                                   "Conspiracy craft: " + " | ".join(brain.get("conspiracy_craft") or [])]))
    rows.append(("author_craft", craft, None, {"chapters_covered": brain.get("chapters_covered")}))
    return rows


# Categories this indexer fully owns: a row of one of these that no current candidate matches is STALE (the record it came from was
# changed or removed - a regenerated genome pattern, a deduped glossary term...). mechanics / humor / blueprint / project_system belong
# to other jobs and are never touched here.
OWNED = ("prose", "dialogue", "reveal", "glossary", "summary", "scheme", "antagonist_template", "symbol", "pattern", "story_shape",
         "author_arc", "author_thread", "author_craft")
# Whole-file records that are rebuilt in place (a fresh rolling summary, a rebuilt author brain): their old rows are replaced on every run.
REPLACED = ("story_shape", "author_arc", "author_thread", "author_craft")


def main():
    args = sys.argv[1:]
    status = "--status" in args          # report only: per novel how many chunks are wanted / already indexed / queued / stale (no embedding, no writes)
    prune = "--prune" in args            # also delete the stale rows (index rows only: derived data)
    args = [a for a in args if not a.startswith("--")]
    if not status and not ollama_available():
        print("ERROR: Ollama not reachable at localhost:11434 — is it running?")
        sys.exit(1)
    novel_ids = [n for n in (args or sorted(p.name for p in NOVELS_DIR.iterdir() if p.is_dir()))
                 if (NOVELS_DIR / n).is_dir()]
    conn = init_db()

    # Build one queue per novel: candidates minus what's already indexed —
    # pure JSON scanning, zero embedding cost, so doing this for all 16
    # novels up front is cheap even though most of it won't be needed yet.
    queues = {}
    titles = {}
    skipped_counts = {}
    for novel_id in novel_ids:
        root = NOVELS_DIR / novel_id
        meta = load_json(root / "novel_metadata.json", {}) or {}
        titles[novel_id] = meta.get("title") or novel_id
        candidates = _collect_candidates(root)
        # A refreshed rolling summary has new text, so INSERT-if-unseen would leave
        # the old version behind as a stale near-duplicate. Drop this novel's
        # story_shape rows that no longer match (index rows only — derived data).
        for cat in REPLACED:
            current_shapes = [c[1] for c in candidates if c[0] == cat]
            if current_shapes and not status:
                marks = ",".join("?" * len(current_shapes))
                dropped = conn.execute(
                    f"DELETE FROM chunks WHERE novel_id=? AND category=? AND text NOT IN ({marks})",
                    [novel_id, cat, *current_shapes]).rowcount
                if dropped:
                    conn.commit()
                    print(f"  {novel_id}: replaced {dropped} outdated {cat} chunk(s)")
        known = existing_keys(conn, novel_id)   # {(category, chapter, text), ...}
        new_q = [c for c in candidates if (c[0], c[2], c[1]) not in known]
        queues[novel_id] = new_q
        skipped_counts[novel_id] = len(candidates) - len(new_q)
        if status or prune:
            cand_keys = {(c[0], c[2], c[1]) for c in candidates}
            stale = [k for k in known if k[0] in OWNED and k not in cand_keys]
            if status:
                print("STATUS " + json.dumps({"novel": novel_id, "wanted": len(cand_keys), "queued": len({(c[0], c[2], c[1]) for c in new_q}),
                                              "stale": len(stale)}))
            if prune and stale:
                for cat, ch, text in stale:
                    conn.execute("DELETE FROM chunks WHERE novel_id=? AND category=? AND chapter IS ? AND text=?", (novel_id, cat, ch, text))
                conn.commit()
                print(f"  {novel_id}: pruned {len(stale)} stale chunk(s)")
        print(f"{novel_id}: {len(new_q)} new chunk(s) queued, {skipped_counts[novel_id]} already-indexed")

    if status:
        conn.close()
        return
    indexed_counts = {n: 0 for n in novel_ids}
    total = 0
    n_since_commit = 0
    active = [n for n in novel_ids if queues[n]]
    while active:
        for novel_id in list(active):
            q = queues[novel_id]
            if not q:
                active.remove(novel_id)
                continue
            category, text, chapter, meta = q.pop(0)
            write_live_status("knowledge_index", novel=titles[novel_id], batch_size=1, kind=category, preview=text[:200])
            try:
                emb = embed_text(text)
                store_chunk(conn, novel_id, titles[novel_id], category, text, chapter, meta, emb)
                indexed_counts[novel_id] += 1
                total += 1
                n_since_commit += 1
            except Exception as e:
                print(f"  WARN {novel_id}/{category} embed failed: {str(e)[:100]}")
            if n_since_commit >= COMMIT_EVERY:
                conn.commit()
                n_since_commit = 0
        active = [n for n in active if queues[n]]

    conn.commit()
    conn.close()
    for novel_id in novel_ids:
        print(f"{novel_id}: indexed {indexed_counts[novel_id]} new chunk(s), skipped {skipped_counts[novel_id]} already-indexed")
    print(f"TOTAL: {total} new chunk(s) indexed this run")


if __name__ == "__main__":
    main()
