"""Build/refresh the Blueprint semantic search index — sibling to
build_knowledge_index.py (V4 Phase 4's corpus index), same DB/embedding
infra, different source: corpus/blueprints/{system_type}/{blueprint_id}.json
instead of novels/*.

Reuses knowledge_index.db's existing `chunks` table AS-IS (no schema
change) with a repurposed column mapping, distinguished by category="blueprint":
    novel_id    -> system_type (e.g. "power_levels") — the natural grouping key,
                   shown as the Corpus Pipeline page's per-row grouping for this job
    novel_title -> the blueprint's display_name (e.g. "a reference novel")
    category    -> always "blueprint" (new value, alongside the corpus's
                   dialogue/glossary/prose/reveal/scheme/symbol categories —
                   knowledge_search(category="blueprint") already works for
                   free once this runs, no search-side code changes needed)
    chapter     -> unused (NULL) for blueprints, BUT SQLite treats NULL as
                   distinct-from-itself in a UNIQUE constraint (confirmed:
                   two rows with the exact same (novel_id, category, NULL,
                   text) both insert successfully) — so incremental dedup
                   here does NOT use the same "INSERT OR IGNORE + UNIQUE
                   constraint" trick build_knowledge_index.py relies on.
                   Blueprints are also edited/re-saved as WHOLE files, not
                   incrementally appended to like corpus chapters, so
                   "delete this blueprint's old rows, then insert fresh" is
                   both simpler and more correct here (an item removed from
                   an edited Blueprint must also disappear from the index,
                   which the corpus's additive-only model never needs to
                   handle).
    text        -> name + tags + description/importance concatenated, so a
                   query for "romantic rival mentor" hits an item whose TAGS
                   say exactly that even if its description prose doesn't
                   repeat those words — Blueprint items are short/tag-dense,
                   not narrative-dense like corpus prose, so this matters
                   more here than for corpus chunks.
    meta        -> {"blueprint_id", "item_index", "field": "factions"|
                   "key_locations"|"races"|None} — enough to trace a search
                   hit back to its exact source file/item/list.

Usage:
    python build_blueprint_index.py                # every blueprint file
    python build_blueprint_index.py power_levels    # just this system_type
    python build_blueprint_index.py power_levels/my_novel   # one file
"""
import hashlib
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_index import init_db, embed_text, ollama_available, _pack
from llm_client import write_live_status

BLUEPRINTS_DIR = Path(__file__).parent / "blueprints"

# Confirmed live (this session): embed_text's own urlopen(timeout=30) did NOT
# reliably bound a call — a real run hung for 10+ minutes on a single item
# with near-zero CPU time consumed (not doing real work, genuinely stuck),
# while the exact same item embedded fine (~3s) called in isolation. Rather
# than chase the exact cause further, wrap every call in a hard watchdog:
# run it on a worker thread and give up waiting after _EMBED_TIMEOUT — the
# stuck call's thread leaks (Python can't force-kill a thread), but the MAIN
# process moves on instead of hanging forever, and a leaked thread here costs
# nothing since the process exits when the run finishes anyway.
_EMBED_TIMEOUT = 45
_embed_pool = ThreadPoolExecutor(max_workers=1)


def _embed_with_watchdog(text: str):
    fut = _embed_pool.submit(embed_text, text)
    try:
        return fut.result(timeout=_EMBED_TIMEOUT)
    except _FutureTimeout:
        raise TimeoutError(f"embed_text exceeded {_EMBED_TIMEOUT}s watchdog (item abandoned, run continues)")


def _text_hash(text: str) -> str:
    """Short, stable hash of an item's embedded text — lets a re-run tell
    'this exact item is already indexed with this exact content' apart from
    'this item is new or its text changed since last time' WITHOUT paying an
    embedding call just to find out. Stored in each row's meta so it survives
    process restarts (unlike an in-memory cache)."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# The Blueprint list-fields that carry {name, description|importance, tags}
# items per system_type — mirrors ProjectView.jsx's ENGINE_FIELDS/listKey and
# blueprints.py's _SCHEMAS item_key, kept here as a flat lookup since this
# script has no reason to import the FastAPI router module. "world" is the
# one multi-list type (factions/key_locations/races all in one file); every
# other type has exactly one list under item_key.
_LIST_FIELDS = {
    "world": ["factions", "key_locations", "races"],
    "power_levels": ["levels"],
    "techniques": ["techniques"],
    "weapons": ["weapons"],
    "alchemy": ["pills"],
    "arrays": ["formations"],
    "artifact_forging": ["artifacts"],
    "treasures_materials": ["treasures"],
    "wars": ["wars"],
    "relationships": ["relationships"],
    "encounters": ["encounters"],
    "character_templates": ["characters"],
    "pets_mounts": ["companions"],
    "bosses_monsters": ["monsters"],
    "currency_commerce": ["entities"],
}

# Best-effort per-item text field to embed alongside name/tags — the item's
# own "main prose" field, when it has one. Falls back to trying description
# then importance if a system_type isn't listed (covers any future system
# added to blueprints.py without a matching entry here needing to be added
# immediately — degrades gracefully instead of embedding an empty string).
_TEXT_FIELD = {
    "power_levels": "description", "techniques": "effect", "weapons": "ability",
    "alchemy": "effect", "arrays": "effect", "artifact_forging": "ability",
    "treasures_materials": "description", "wars": "description",
    "relationships": "description", "encounters": "stakes",
    "character_templates": "description",
    "factions": "description", "key_locations": "importance", "races": "description",
    "pets_mounts": "abilities", "bosses_monsters": "abilities",
    "currency_commerce": "description",
}


def _item_text(item: dict, list_field: str, system_type: str) -> str:
    """Concatenate name + tags + the item's main prose field + every OTHER
    populated string field into one string to embed — tags FIRST (right
    after name) so a short tag-heavy item still gets its tags weighted
    meaningfully in the embedding, not diluted by a much longer prose field.

    Was: only the single _TEXT_FIELD-mapped field (e.g. "description" for
    character_templates). Confirmed live this silently dropped substantial,
    genuinely distinct content from search entirely — a character_templates
    item's powers_items (709 chars, MORE content than its own description)
    never appeared in the embedded text at all, so a query naming a specific
    technique/item that field held would never match that character. Same
    gap hit wars (cause/outcome/factions_involved/impact all excluded),
    relationships (status/participants), treasures_materials
    (known_owners) — confirmed via a live audit across every system_type's
    real saved blueprint data, not just character_templates. Now includes
    every string field with real content (>1 char after stripping),
    excluding name/tags (already handled above) and pure bookkeeping keys
    that were never prose to begin with."""
    parts = []
    if item.get("name"):
        parts.append(str(item["name"]))
    tags = item.get("tags")
    if isinstance(tags, list) and tags:
        parts.append(", ".join(str(t) for t in tags))
    text_field = _TEXT_FIELD.get(list_field) or _TEXT_FIELD.get(system_type)
    primary = text_field if (text_field and item.get(text_field)) else (
        "description" if item.get("description") else
        "importance" if item.get("importance") else None)
    if primary:
        parts.append(str(item[primary]))
    # Every other populated string field — lists (factions_involved) joined,
    # scalars (status, known_owners, cause, outcome, impact, archetype,
    # powers_items, participants, tier, ...) appended as-is. name/tags/the
    # primary field already handled above, never repeated here.
    _SKIP_KEYS = {"name", "tags", primary} if primary else {"name", "tags"}
    for key, val in item.items():
        if key in _SKIP_KEYS or val in (None, "", []):
            continue
        if isinstance(val, str):
            parts.append(val)
        elif isinstance(val, list) and all(isinstance(v, str) for v in val):
            parts.append(", ".join(val))
    return " — ".join(parts)


def _collect_candidates(path: Path, system_type: str) -> list:
    """One blueprint file -> list of (text, meta) tuples, one per item across
    all its list fields (world_bible has 3 lists; every other type has 1)."""
    out = []
    d = load_json(path, {}) or {}
    if not isinstance(d, dict):
        return out
    blueprint_id = d.get("standard_id", path.stem)
    display_name = d.get("display_name", path.stem)
    for list_field in _LIST_FIELDS.get(system_type, []):
        items = d.get(list_field)
        if not isinstance(items, list):
            continue
        for idx, item in enumerate(items):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            text = _item_text(item, list_field, system_type)
            if not text.strip():
                continue
            out.append((text, {
                "blueprint_id": blueprint_id, "display_name": display_name,
                "item_index": idx, "field": list_field if len(_LIST_FIELDS.get(system_type, [])) > 1 else None,
            }))
    return out, display_name


def _reindex_blueprint(conn: sqlite3.Connection, system_type: str, path: Path) -> tuple:
    """Incremental, item-level: an item whose (field, item_index, text_hash)
    already has a stored row is SKIPPED entirely (no embed call) — only new
    or actually-changed items pay the embedding cost. An item that no longer
    exists in the file (removed, or index shifted past the file's current
    length) has its stale row deleted. This is the same "existing_keys()
    skip before embedding" philosophy build_knowledge_index.py already uses
    for the corpus, applied per-item here instead of per-chunk, since a
    Blueprint file is edited as a whole rather than append-only like a
    novel's chapters.

    Returns (embedded_count, skipped_count, deleted_count)."""
    d = load_json(path, {}) or {}
    blueprint_id = d.get("standard_id", path.stem) if isinstance(d, dict) else path.stem
    candidates, display_name = _collect_candidates(path, system_type)

    # What's already stored for this exact blueprint file — keyed by
    # (field, item_index) since that's the item's stable identity within
    # the file; text_hash tells us whether ITS content actually changed.
    existing = {}   # (field, item_index) -> (row_id, text_hash)
    for row_id, meta_json in conn.execute(
        "SELECT id, meta FROM chunks WHERE novel_id = ? AND category = 'blueprint' "
        "AND json_extract(meta, '$.blueprint_id') = ?", (system_type, blueprint_id),
    ).fetchall():
        try:
            m = json.loads(meta_json) if meta_json else {}
        except Exception:
            continue
        existing[(m.get("field"), m.get("item_index"))] = (row_id, m.get("text_hash"))

    seen_keys = set()
    embedded, skipped = 0, 0
    COMMIT_EVERY = 5   # visibility + resilience — see build_blueprint_index.py's module docstring reasoning
    since_commit = 0
    for text, meta in candidates:
        key = (meta.get("field"), meta.get("item_index"))
        seen_keys.add(key)
        h = _text_hash(text)
        prior = existing.get(key)
        if prior and prior[1] == h:
            skipped += 1
            continue   # unchanged since last index — no embed call needed
        write_live_status("blueprint_index", novel=system_type, batch_size=1,
                          kind="blueprint", preview=text[:200])
        print(f"  [{system_type}] item {meta.get('item_index')}: embedding ({len(text)} chars)…", flush=True)
        try:
            emb = _embed_with_watchdog(text)
            meta_with_hash = dict(meta, text_hash=h)
            if prior:
                conn.execute(
                    "UPDATE chunks SET novel_title=?, text=?, meta=?, embedding=? WHERE id=?",
                    (display_name, text, json.dumps(meta_with_hash, ensure_ascii=False), _pack(emb), prior[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO chunks (novel_id, novel_title, category, chapter, text, meta, embedding) "
                    "VALUES (?, ?, 'blueprint', NULL, ?, ?, ?)",
                    (system_type, display_name, text, json.dumps(meta_with_hash, ensure_ascii=False), _pack(emb)),
                )
            embedded += 1
            since_commit += 1
            if since_commit >= COMMIT_EVERY:
                conn.commit()
                since_commit = 0
        except Exception as e:
            print(f"  WARN {system_type}/{blueprint_id} item {meta.get('item_index')} embed failed: {str(e)[:150]}", flush=True)

    # Rows for items no longer present in the file (removed, or the list
    # shrank past that index) — delete them so the index doesn't keep
    # serving stale/deleted content.
    stale_ids = [row_id for key, (row_id, _h) in existing.items() if key not in seen_keys]
    if stale_ids:
        conn.executemany("DELETE FROM chunks WHERE id = ?", [(i,) for i in stale_ids])

    conn.commit()
    return embedded, skipped, len(stale_ids)


def main():
    if not ollama_available():
        print("ERROR: Ollama not reachable at localhost:11434 — is it running?")
        sys.exit(1)
    if not BLUEPRINTS_DIR.exists():
        print("No blueprints/ directory yet — nothing to index.")
        return

    args = sys.argv[1:]
    targets = []   # list of (system_type, Path) for every blueprint file to reindex
    if not args:
        for type_dir in sorted(BLUEPRINTS_DIR.iterdir()):
            if not type_dir.is_dir():
                continue
            for f in sorted(type_dir.glob("*.json")):
                targets.append((type_dir.name, f))
    else:
        for arg in args:
            if "/" in arg or "\\" in arg:
                system_type, blueprint_id = Path(arg).parts[-2:] if len(Path(arg).parts) >= 2 else (Path(arg).parent.name, Path(arg).stem)
                f = BLUEPRINTS_DIR / system_type / f"{Path(blueprint_id).stem}.json"
                if f.exists():
                    targets.append((system_type, f))
                else:
                    print(f"  WARN {f} not found — skipped")
            else:
                type_dir = BLUEPRINTS_DIR / arg
                if not type_dir.is_dir():
                    print(f"  WARN {type_dir} not found — skipped")
                    continue
                for f in sorted(type_dir.glob("*.json")):
                    targets.append((arg, f))

    if not targets:
        print("Nothing to index.")
        return

    conn = init_db()
    total_embedded = total_skipped = total_deleted = 0
    by_type = {}
    for system_type, path in targets:
        embedded, skipped, deleted = _reindex_blueprint(conn, system_type, path)
        by_type[system_type] = by_type.get(system_type, (0, 0, 0))
        by_type[system_type] = tuple(a + b for a, b in zip(by_type[system_type], (embedded, skipped, deleted)))
        total_embedded += embedded
        total_skipped += skipped
        total_deleted += deleted
        note = f"embedded {embedded}, skipped {skipped} (unchanged)" + (f", removed {deleted} stale" if deleted else "")
        print(f"{system_type}/{path.stem}: {note}")
    conn.close()

    for system_type, (e, s, d) in sorted(by_type.items()):
        print(f"{system_type}: {e} embedded, {s} skipped" + (f", {d} removed" if d else ""))
    print(f"TOTAL: {total_embedded} embedded, {total_skipped} skipped (already up to date)"
          + (f", {total_deleted} stale row(s) removed" if total_deleted else "") + " this run")


if __name__ == "__main__":
    main()
