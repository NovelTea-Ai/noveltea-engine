"""Build/refresh the humor search index (Pipeline tab → Humor Index (nomic)).

Embeds every corpus humor beat (novels/*/humor/instances.json) with
nomic-embed-text, plus the corpus-tuned nomic-embed-corpus, into
knowledge_index.db as category "humor", so the project Humor tab can search the
corpus's setups, payoffs and running gags by idea.

humor is an OPT-IN category: a search that doesn't name a category (chapter
prompts' corpus grounding, the character roster) skips it, so adding it changes
nothing those return. This only ever adds rows; the one update it makes is to
humor rows' own meta, refreshed every run because gag-family sizes change as
Corpus Builder re-links callbacks.

Each chunk's text is "<type>: <setup> → <payoff>" (what the joke IS, to search
by idea; older beats' context/excerpt/description fields count as setup and
payoff, see beat_parts). meta has the beat's id, type, setup, payoff,
participants, recurrence, tone tags, function, and family_size: how many
distinct beats its gag family has once broken callback links are filtered out
(same filter as the backend's _humor_setup_stats). 2+ means the joke became a
running gag. Beats a re-merged chapter appended twice index once (same chapter
and text = the table's UNIQUE key).

Incremental (already-indexed beats are skipped, so a re-run after new chapters
only embeds the new ones) and batched (64 texts per Ollama call per model),
round-robin across novels like build_knowledge_index.py.

Usage: python build_humor_index.py [novel_id ...]   (no args = every novel)
"""
import json
import chapter_lookup   # chapter of a beat the merged log lost, read from deltas_v3/chN.json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_index import (init_db, store_chunk, embed_texts_batch, ollama_available,
                             EMBED_MODEL, EMBED_MODEL_TUNED)
from llm_client import write_live_status

NOVELS_DIR = Path(__file__).parent / "novels"
CATEGORY = "humor"
BATCH = 64
_CITE_RE = re.compile(r"\bch(?:apter)?s?\.?\s*(\d+)", re.I)


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _chapter(h):
    try:
        return int(h.get("source_chapter"))
    except Exception:
        return None


def beat_parts(h: dict) -> tuple:
    """(setup, payoff) of one beat, across the schemas the humor logs hold:
    setup/payoff (extract_v3), context/excerpt (older a reference novel beats),
    description (several others). The backend's corpus.py _humor_beat_parts
    mirrors this exactly."""
    setup = str(h.get("setup") or h.get("context") or h.get("description") or "").strip()
    payoff = str(h.get("payoff") or h.get("excerpt") or h.get("example_text") or "").strip()
    return setup, payoff


def humor_chunk_text(h: dict) -> str:
    """The indexed text for one beat ("" = nothing to index). The backend's
    corpus.py _humor_chunk_text mirrors this exactly, to count what a complete
    index holds for the Pipeline tab's progress bar."""
    kind = str(h.get("type") or "humor").replace("_", " ")
    setup, payoff = beat_parts(h)
    body = f"{setup} → {payoff}" if setup and payoff else (setup or payoff)
    return f"{kind}: {body}"[:700] if body else ""


def beat_key(h: dict) -> tuple:
    """One beat however many times a re-merged chapter appended it to the log
    (several logs hold each beat 2-4 times under different ids)."""
    setup, payoff = beat_parts(h)
    return (_chapter(h), setup.lower()[:200], payoff.lower()[:200])


def family_sizes(beats: list) -> dict:
    """{beat key: distinct beats in its gag family}, over the callback links that
    pass the backend's checks (same as its _humor_setup_stats): not linked to
    itself or an identical beat, pointing backward, both chapters known, and any
    chapter its text cites matching the target's (within one)."""
    by_id = {h.get("id"): h for h in beats if h.get("id")}
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for h in beats:
        t = by_id.get(h.get("callback_to_id"))
        a, b = _chapter(h), (_chapter(t) if t else None)
        if t is None or t is h or a is None or b is None or b > a:
            continue
        if beat_parts(t) == beat_parts(h):
            continue
        raw = h.get("callback_to")
        cites = [int(c) for c in _CITE_RE.findall(f"ch {raw}" if isinstance(raw, int) else str(raw or ""))]
        if cites and not any(abs(c - b) <= 1 for c in cites):
            continue
        parent[find(beat_key(h))] = find(beat_key(t))
    size = {}
    for k in list(parent):
        size[find(k)] = size.get(find(k), 0) + 1
    return {k: size[find(k)] for k in parent}


def collect(novel_dir: Path) -> list:
    """(text, chapter, meta) for each of one novel's humor beats — JSON reads
    only. A malformed beat is a logged skip, never a lost run."""
    beats = [h for h in (load_json(novel_dir / "humor" / "instances.json", []) or []) if isinstance(h, dict)]
    fam = family_sizes(beats)
    out = []
    for h in beats:
        try:
            text = humor_chunk_text(h)
            if not text:
                continue
            setup, payoff = beat_parts(h)
            people = h.get("participants") or h.get("characters_involved") or []
            tones = h.get("tone_tags") or ([h["tone"]] if isinstance(h.get("tone"), str) else [])
            chapter = _chapter(h)
            if chapter is None:     # the merged log lost it: the beat's own delta file has it
                chapter = chapter_lookup.find(novel_dir, "humor", f"{setup} → {payoff}" if setup and payoff else "", payoff or setup)
            out.append((text, chapter, {
                "id": h.get("id"),
                "type": h.get("type"),
                "setup": setup[:400],
                "payoff": payoff[:400],
                "participants": [p for p in (people if isinstance(people, list) else []) if isinstance(p, str)][:6],
                "recurrence": h.get("recurrence") if isinstance(h.get("recurrence"), str) else None,
                "tone_tags": [t for t in (tones if isinstance(tones, list) else []) if isinstance(t, str)][:6],
                "function": str(h.get("function") or "")[:300],
                "family_size": fam.get(beat_key(h), 1),
            }))
        except Exception as e:
            print(f"  WARN humor beat skipped (malformed): {str(e)[:100]}")
    return out


def main():
    args = sys.argv[1:]
    status = "--status" in args          # report only: wanted / queued / stale per novel; no embedding, no writes
    prune = "--prune" in args            # also delete humor rows no beat wants any more (index rows only: derived data)
    args = [a for a in args if not a.startswith("--")]
    if not status and not ollama_available():
        print("ERROR: Ollama not reachable at 127.0.0.1:11434 — is it running?")
        sys.exit(1)
    novel_ids = [n for n in (args or sorted(p.name for p in NOVELS_DIR.iterdir() if p.is_dir()))
                 if (NOVELS_DIR / n / "humor" / "instances.json").exists()]
    conn = init_db()
    conn.execute("PRAGMA busy_timeout = 30000")   # the Knowledge Index job may be writing too

    queues, titles, refreshed = {}, {}, 0
    for nid in novel_ids:
        root = NOVELS_DIR / nid
        titles[nid] = (load_json(root / "novel_metadata.json", {}) or {}).get("title") or nid
        known = {(ch, text): meta for ch, text, meta in conn.execute(
            "SELECT chapter, text, meta FROM chunks WHERE novel_id = ? AND category = ?", (nid, CATEGORY))}
        seen, queue = set(), []
        for text, ch, meta in collect(root):
            key = (ch, text)
            if key in seen:      # same chapter + text twice = one chunk (the table's UNIQUE key)
                continue
            seen.add(key)
            if key in known:
                mj = json.dumps(meta, ensure_ascii=False)
                if known[key] != mj and not status:
                    conn.execute("UPDATE chunks SET meta = ? WHERE novel_id = ? AND category = ? "
                                 "AND chapter IS ? AND text = ?", (mj, nid, CATEGORY, ch, text))
                    refreshed += 1
            else:
                queue.append((text, ch, meta))
        queues[nid] = queue
        stale = [k for k in known if k not in seen]
        if status:
            print("STATUS " + json.dumps({"novel": nid, "wanted": len(seen), "queued": len(queue), "stale": len(stale)}))
        if prune and stale:
            for ch, text in stale:
                conn.execute("DELETE FROM chunks WHERE novel_id=? AND category=? AND chapter IS ? AND text=?", (nid, CATEGORY, ch, text))
            print(f"  {nid}: pruned {len(stale)} stale humor chunk(s)")
        print(f"{nid}: {len(queue)} new humor beat(s) queued, {len(seen) - len(queue)} already indexed")
    conn.commit()
    if status:
        conn.close()
        return
    if refreshed:
        print(f"refreshed gag-family info on {refreshed} indexed beat(s)")

    total, failed = 0, 0
    active = [n for n in novel_ids if queues[n]]
    while active:
        for nid in list(active):
            batch, queues[nid] = queues[nid][:BATCH], queues[nid][BATCH:]
            texts = [b[0] for b in batch]
            write_live_status("humor_index", novel=titles[nid], batch_size=len(batch),
                              kind=batch[0][2].get("type") or "humor", preview=texts[0][:200])
            try:
                base = embed_texts_batch(texts, EMBED_MODEL)
            except Exception as e:
                failed += len(batch)
                print(f"  WARN {nid}: batch of {len(batch)} failed to embed ({str(e)[:100]}); a re-run retries it")
                continue
            try:
                tuned = embed_texts_batch(texts, EMBED_MODEL_TUNED)
            except Exception:
                tuned = [None] * len(batch)   # store_chunk retries one by one; Tuned Embeddings backfills the rest
            for (text, ch, meta), emb, emb_t in zip(batch, base, tuned):
                store_chunk(conn, nid, titles[nid], CATEGORY, text, ch, meta, emb, emb_t)
            conn.commit()
            total += len(batch)
        active = [n for n in active if queues[n]]
    conn.close()
    print(f"TOTAL: {total} new humor beat(s) indexed this run" + (f", {failed} failed (re-run to retry)" if failed else ""))


if __name__ == "__main__":
    main()
