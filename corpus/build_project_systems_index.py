"""Build/refresh the per-project Systems semantic search index — sibling to
build_blueprint_index.py (same DB/embedding infra), different source:
NovelTeaApp's corpus/projects/{project_id}/project.json's `systems` and
`world_bible` fields, instead of the author's global Blueprint library.

This is Stage 3 of the Blueprint semantic search pipeline: once a PROJECT's
own systems are populated (Power Levels, Techniques, Relationships,
Encounters, World Bible, ...), THIS index lets chapter generation pull the
1-3 items that are actually relevant to what's happening in the current
chapter, on TOP of the always-included blind systems_block dump in
generate.py's _build_chapter_prompt (see _format_systems_block) — that dump
stays as the floor (canon facts: power tier ordering, world rules, etc.);
this index adds sharper, chapter-scoped relevance for large systems where a
blind top-N slice misses the one relationship or encounter that matters here.

Reuses knowledge_index.db's existing `chunks` table AS-IS (no schema change),
distinguished by category="project_system", with a repurposed column mapping:
    novel_id    -> project_id — the CRITICAL scoping key. knowledge_search()
                   must always be called with novel_id=<this project's id> for
                   this category, or one project's systems data leaks into
                   another project's chapter prompt. See corpus.py's
                   knowledge_search() novel_id param docstring.
    novel_title -> the project's title, for readable search-hit logging
    category    -> always "project_system"
    chapter     -> unused (NULL) — a project's systems aren't chapter-scoped
                   the way corpus chunks are; relevance to a given chapter is
                   handled entirely by the semantic query, not this column.
    text        -> name + tags + main prose field, same convention as
                   build_blueprint_index.py's _item_text.
    meta        -> {"system_type", "item_index", "field", "item_name",
                   "text_hash"} — enough to trace a hit back to its exact
                   source list/item, and to render "[relationships] Jiang
                   Chen & Yan Chenyu" style labels in the prompt block.

Incremental, same item-level text_hash skip as build_blueprint_index.py — a
project.json is edited/re-saved as a whole file (via the Project/Systems UI),
not appended to, so "diff by (system_type, field, item_index) -> text_hash"
is the correct incremental strategy here too, not the corpus's
insert-or-ignore append model.

Usage:
    python build_project_systems_index.py                  # every project
    python build_project_systems_index.py <project_id>      # one project
"""
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from knowledge_index import init_db, embed_text, ollama_available, _pack
from llm_client import write_live_status

PROJECTS_DIR = Path(__file__).parent / "projects"

# Throwaway/test projects from earlier feature testing — not real work, and
# their systems data (fictional power levels, techniques, etc.) has nothing
# to do with the actual corpus. Excluded so they don't get embedded into the
# shared knowledge_index.db, where they'd otherwise show up as "novels" in
# the Project Systems Index AND Tuned Embeddings pipeline cards (the latter
# groups chunks by novel_id with no filtering — see corpus.py's
# _compute_tuned_embeddings_progress). 2026-09-27.
_EXCLUDED_PROJECT_IDS = set()      # ids of throwaway test projects to keep out of the index (add your own)

# Same watchdog rationale as build_blueprint_index.py — a stuck embed_text()
# call must never be able to hang the whole run.
_EMBED_TIMEOUT = 45
_embed_pool = ThreadPoolExecutor(max_workers=1)


def _embed_with_watchdog(text: str):
    fut = _embed_pool.submit(embed_text, text)
    try:
        return fut.result(timeout=_EMBED_TIMEOUT)
    except _FutureTimeout:
        raise TimeoutError(f"embed_text exceeded {_EMBED_TIMEOUT}s watchdog (item abandoned, run continues)")


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# project.json's systems.<key> shape mirrors blueprints.py's _SCHEMAS item_key
# per system_type — kept as a flat lookup here for the same reason
# build_blueprint_index.py keeps its own copy (no FastAPI import needed).
# "world_bible" is the one multi-list type and lives at the project's TOP
# LEVEL (project["world_bible"]), not under project["systems"] — every other
# type is project["systems"][system_type][list_field].
_SYSTEMS_LIST_FIELDS = {
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
    "pets_mounts": ["companions"],
    "bosses_monsters": ["monsters"],
    "currency_commerce": ["entities"],
}
_WORLD_BIBLE_LIST_FIELDS = ["factions", "key_locations", "races"]

_TEXT_FIELD = {
    "power_levels": "description", "techniques": "effect", "weapons": "ability",
    "alchemy": "effect", "arrays": "effect", "artifact_forging": "ability",
    "treasures_materials": "description", "wars": "description",
    "relationships": "description", "encounters": "stakes",
    "pets_mounts": "abilities", "bosses_monsters": "abilities",
    "currency_commerce": "description",
    "factions": "description", "key_locations": "importance", "races": "description",
}


def _item_text(item: dict, list_field: str, system_type: str) -> str:
    """Same convention as build_blueprint_index.py's _item_text — name, then
    tags, then the item's main prose field, tags weighted early since these
    items are short and tag-dense."""
    parts = []
    if item.get("name"):
        parts.append(str(item["name"]))
    tags = item.get("tags")
    if isinstance(tags, list) and tags:
        parts.append(", ".join(str(t) for t in tags))
    text_field = _TEXT_FIELD.get(list_field) or _TEXT_FIELD.get(system_type)
    if text_field and item.get(text_field):
        parts.append(str(item[text_field]))
    elif item.get("description"):
        parts.append(str(item["description"]))
    elif item.get("importance"):
        parts.append(str(item["importance"]))
    return " — ".join(parts)


def _collect_candidates(project: dict) -> list:
    """A loaded project.json -> list of (text, meta) tuples, one per item
    across every populated system + world_bible list."""
    out = []
    systems = project.get("systems") or {}
    if isinstance(systems, dict):
        for system_type, list_fields in _SYSTEMS_LIST_FIELDS.items():
            sys_data = systems.get(system_type)
            if not isinstance(sys_data, dict):
                continue
            for list_field in list_fields:
                items = sys_data.get(list_field)
                if not isinstance(items, list):
                    continue
                for idx, item in enumerate(items):
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    text = _item_text(item, list_field, system_type)
                    if not text.strip():
                        continue
                    out.append((text, {
                        "system_type": system_type, "item_index": idx,
                        "field": list_field if len(list_fields) > 1 else None,
                        "item_name": item.get("name", ""),
                    }))

    world = project.get("world_bible")
    if isinstance(world, dict):
        for list_field in _WORLD_BIBLE_LIST_FIELDS:
            items = world.get(list_field)
            if not isinstance(items, list):
                continue
            for idx, item in enumerate(items):
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                text = _item_text(item, list_field, "world")
                if not text.strip():
                    continue
                out.append((text, {
                    "system_type": "world", "item_index": idx,
                    "field": list_field, "item_name": item.get("name", ""),
                }))

    # The author's canon tabs that are safe for the chapter writer to find by search: approved Lore, the Cast, the Foes roster, the
    # Timeline's own events and the Sacred Grounds. The Conspiracy tree and author_secrets are deliberately NOT indexed: this index feeds
    # the chapter writer, and the hidden truths must never reach a chapter through a search result.
    lore = ((project.get("lore") or {}).get("world")) or []
    for idx, e in enumerate(lore):
        if isinstance(e, dict) and e.get("status") == "approved" and e.get("text"):
            out.append((f"{e.get('title', '')} — {e.get('kind', '')} — {e['text']}", {
                "system_type": "lore", "item_index": idx, "field": None, "item_name": e.get("title", "")}))
    for idx, c in enumerate(project.get("character_list") or []):
        if isinstance(c, dict) and c.get("name"):
            out.append((" — ".join(str(x) for x in (c["name"], c.get("role"), c.get("faction"), c.get("archetype"), c.get("motivation")) if x), {
                "system_type": "cast", "item_index": idx, "field": None, "item_name": c["name"]}))
    for idx, e in enumerate(((project.get("antagonists") or {}).get("roster")) or []):
        if isinstance(e, dict) and e.get("name"):
            out.append((" — ".join(str(x) for x in (e["name"], e.get("tier"), e.get("archetype"), e.get("who"), e.get("ties"), e.get("active_chapters")) if x), {
                "system_type": "foes", "item_index": idx, "field": None, "item_name": e["name"]}))
    for idx, e in enumerate(((project.get("timeline") or {}).get("events")) or []):
        if isinstance(e, dict) and e.get("title"):
            span = f"chapters {e.get('chapter')}-{e['end_chapter']}" if e.get("end_chapter") else f"chapter {e.get('chapter')}"
            out.append((f"{e['title']} — {e.get('category', '')} — {span} — {e.get('mc_sees', '')}", {
                "system_type": "timeline", "item_index": idx, "field": None, "item_name": e["title"]}))
    sg = (project.get("systems") or {}).get("sacred_grounds")
    if isinstance(sg, dict):
        for idx, (name, text) in enumerate(sg.items()):
            if isinstance(text, str) and text.strip():
                out.append((f"{name} — {text}", {"system_type": "sacred_grounds", "item_index": idx, "field": None, "item_name": name}))

    return out


def _reindex_project(conn, project_id: str, path: Path) -> tuple:
    """Incremental, item-level — same skip-unchanged / delete-stale model as
    build_blueprint_index.py's _reindex_blueprint, keyed by
    (system_type, field, item_index) within this one project.

    Returns (embedded_count, skipped_count, deleted_count)."""
    project = load_json(path, {}) or {}
    if not isinstance(project, dict):
        return 0, 0, 0
    title = project.get("title", project_id)
    candidates = _collect_candidates(project)

    existing = {}   # (system_type, field, item_index) -> (row_id, text_hash)
    for row_id, meta_json in conn.execute(
        "SELECT id, meta FROM chunks WHERE novel_id = ? AND category = 'project_system'", (project_id,),
    ).fetchall():
        try:
            m = json.loads(meta_json) if meta_json else {}
        except Exception:
            continue
        existing[(m.get("system_type"), m.get("field"), m.get("item_index"))] = (row_id, m.get("text_hash"))

    seen_keys = set()
    embedded, skipped = 0, 0
    COMMIT_EVERY = 5
    since_commit = 0
    for text, meta in candidates:
        key = (meta.get("system_type"), meta.get("field"), meta.get("item_index"))
        seen_keys.add(key)
        h = _text_hash(text)
        prior = existing.get(key)
        if prior and prior[1] == h:
            skipped += 1
            continue
        write_live_status("project_systems_index", novel=project_id, batch_size=1,
                          kind="project_system", preview=text[:200])
        print(f"  [{project_id}/{meta.get('system_type')}] item {meta.get('item_index')} "
              f"'{meta.get('item_name','')}': embedding ({len(text)} chars)…", flush=True)
        try:
            emb = _embed_with_watchdog(text)
            meta_with_hash = dict(meta, text_hash=h)
            if prior:
                conn.execute(
                    "UPDATE chunks SET novel_title=?, text=?, meta=?, embedding=? WHERE id=?",
                    (title, text, json.dumps(meta_with_hash, ensure_ascii=False), _pack(emb), prior[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO chunks (novel_id, novel_title, category, chapter, text, meta, embedding) "
                    "VALUES (?, ?, 'project_system', NULL, ?, ?, ?)",
                    (project_id, title, text, json.dumps(meta_with_hash, ensure_ascii=False), _pack(emb)),
                )
            embedded += 1
            since_commit += 1
            if since_commit >= COMMIT_EVERY:
                conn.commit()
                since_commit = 0
        except Exception as e:
            print(f"  WARN {project_id}/{meta.get('system_type')} item {meta.get('item_index')} "
                  f"embed failed: {str(e)[:150]}", flush=True)

    stale_ids = [row_id for key, (row_id, _h) in existing.items() if key not in seen_keys]
    if stale_ids:
        conn.executemany("DELETE FROM chunks WHERE id = ?", [(i,) for i in stale_ids])

    conn.commit()
    return embedded, skipped, len(stale_ids)


def main():
    if not ollama_available():
        print("ERROR: Ollama not reachable at localhost:11434 — is it running?")
        sys.exit(1)
    if not PROJECTS_DIR.exists():
        print("No projects/ directory yet — nothing to index.")
        return

    args = sys.argv[1:]
    targets = []   # list of (project_id, Path) for every project.json to reindex
    if not args:
        for proj_dir in sorted(PROJECTS_DIR.iterdir()):
            if not proj_dir.is_dir() or proj_dir.name in _EXCLUDED_PROJECT_IDS:
                continue
            f = proj_dir / "project.json"
            if f.exists():
                targets.append((proj_dir.name, f))
    else:
        for arg in args:
            if arg in _EXCLUDED_PROJECT_IDS:
                print(f"  WARN {arg} is in _EXCLUDED_PROJECT_IDS (test data) — skipped; edit the set in this file to override")
                continue
            f = PROJECTS_DIR / arg / "project.json"
            if f.exists():
                targets.append((arg, f))
            else:
                print(f"  WARN {f} not found — skipped")

    if not targets:
        print("Nothing to index.")
        return

    conn = init_db()
    total_embedded = total_skipped = total_deleted = 0
    by_project = {}
    for project_id, path in targets:
        embedded, skipped, deleted = _reindex_project(conn, project_id, path)
        by_project[project_id] = (embedded, skipped, deleted)
        total_embedded += embedded
        total_skipped += skipped
        total_deleted += deleted
        note = f"embedded {embedded}, skipped {skipped} (unchanged)" + (f", removed {deleted} stale" if deleted else "")
        print(f"{project_id}: {note}")
    conn.close()

    print(f"TOTAL: {total_embedded} embedded, {total_skipped} skipped (already up to date)"
          + (f", {total_deleted} stale row(s) removed" if total_deleted else "") + " this run")


if __name__ == "__main__":
    main()
