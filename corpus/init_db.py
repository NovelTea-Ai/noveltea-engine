#!/usr/bin/env python3
"""
NovelTea Engine SQLite Migration
===========================
Creates noveltea.db and imports all current JSON data into it.
SQLite becomes the source of truth for queries at 10,000+ chapters.

Usage:
    python init_db.py              # create DB from current JSON
    python init_db.py --sync       # re-sync JSON -> DB (idempotent)
    python init_db.py --query "SELECT novel_id, COUNT(*) FROM chapters GROUP BY novel_id"
"""

import json
import sqlite3
import argparse
import sys
from pathlib import Path


DB_PATH = Path("noveltea.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id    TEXT NOT NULL,
    chapter_num INTEGER NOT NULL,
    title       TEXT,
    function    TEXT,
    summary     TEXT,
    tension_start INTEGER,
    tension_peak  INTEGER,
    tension_end   INTEGER,
    arc_label   TEXT,
    schema_version TEXT DEFAULT '2.0',
    UNIQUE(novel_id, chapter_num)
);

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id    TEXT NOT NULL,
    slug        TEXT NOT NULL,
    name        TEXT,
    type        TEXT,
    role        TEXT,
    notes       TEXT,
    aliases     TEXT,  -- JSON array
    facts       TEXT,  -- JSON array
    UNIQUE(novel_id, slug)
);

CREATE TABLE IF NOT EXISTS humor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id        TEXT NOT NULL,
    source_chapter  INTEGER,
    type            TEXT,
    setup           TEXT,
    payoff          TEXT,
    tone_tags       TEXT,  -- JSON array
    recurrence      TEXT
);

CREATE TABLE IF NOT EXISTS reveals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id        TEXT NOT NULL,
    reveal_type     TEXT,
    content         TEXT,
    setup_chapters  TEXT,  -- JSON array
    payoff_chapter  INTEGER,
    impact          TEXT
);

CREATE TABLE IF NOT EXISTS glossary (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id    TEXT NOT NULL,
    term        TEXT NOT NULL,
    definition  TEXT,
    UNIQUE(novel_id, term)
);

CREATE TABLE IF NOT EXISTS arcs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id    TEXT NOT NULL,
    label       TEXT NOT NULL,
    start_ch    INTEGER,
    end_ch      INTEGER,
    summary     TEXT,
    UNIQUE(novel_id, label)
);

CREATE TABLE IF NOT EXISTS extraction_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT,
    novel_id    TEXT,
    chapter_num INTEGER,
    status      TEXT,
    tokens_in   INTEGER,
    tokens_out  INTEGER,
    cost_usd    REAL,
    time_seconds REAL,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id);
CREATE INDEX IF NOT EXISTS idx_humor_novel ON humor(novel_id);
CREATE INDEX IF NOT EXISTS idx_reveals_novel ON reveals(novel_id);
CREATE INDEX IF NOT EXISTS idx_glossary_novel ON glossary(novel_id);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()
    print(f"✓ Schema initialized in {DB_PATH}")


def sync_novel(conn, novel_id: str):
    nd = Path(f"novels/{novel_id}")
    count = {"chapters": 0, "humor": 0, "reveals": 0, "glossary": 0, "entities": 0}

    # Chapters
    delta_dir = nd / "deltas_v2"
    if delta_dir.exists():
        for delta_path in sorted(delta_dir.glob("ch*.json")):
            try:
                data = json.loads(delta_path.read_text())
                tc = data.get("reader_psychology", {}).get("tension_curve", {})
                conn.execute("""
                    INSERT OR REPLACE INTO chapters
                    (novel_id, chapter_num, title, function, summary,
                     tension_start, tension_peak, tension_end, arc_label, schema_version)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (novel_id, data.get("chapter_number"),
                      data.get("chapter_title"), data.get("chapter_function"),
                      data.get("summary"),
                      tc.get("start"), tc.get("peak"), tc.get("end"),
                      data.get("arc_label_suggestion"),
                      data.get("schema_version", "2.0")))
                count["chapters"] += 1
            except Exception as e:
                print(f"    Warning: skipping {delta_path.name}: {e}")

    # Humor
    humor_path = nd / "humor" / "instances.json"
    if humor_path.exists():
        for h in json.loads(humor_path.read_text()):
            try:
                conn.execute("""
                    INSERT INTO humor (novel_id, source_chapter, type, setup, payoff, tone_tags, recurrence)
                    VALUES (?,?,?,?,?,?,?)
                """, (novel_id, h.get("source_chapter"), h.get("type"),
                      h.get("setup"), h.get("payoff"),
                      json.dumps(h.get("tone_tags", [])),
                      h.get("recurrence")))
                count["humor"] += 1
            except Exception:
                pass

    # Reveals
    reveals_path = nd / "reveals" / "log.json"
    if reveals_path.exists():
        for r in json.loads(reveals_path.read_text()):
            try:
                conn.execute("""
                    INSERT INTO reveals (novel_id, reveal_type, content, setup_chapters, payoff_chapter, impact)
                    VALUES (?,?,?,?,?,?)
                """, (novel_id, r.get("reveal_type"), r.get("content"),
                      json.dumps(r.get("setup_chapters", [])),
                      r.get("payoff_chapter"), r.get("impact")))
                count["reveals"] += 1
            except Exception:
                pass

    # Glossary
    glossary_path = nd / "glossary" / "terms.json"
    if glossary_path.exists():
        for g in json.loads(glossary_path.read_text()):
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO glossary (novel_id, term, definition)
                    VALUES (?,?,?)
                """, (novel_id, g.get("term"), g.get("definition")))
                count["glossary"] += 1
            except Exception:
                pass

    # Entities
    entity_dir = nd / "entities"
    if entity_dir.exists():
        for ef in entity_dir.glob("*.json"):
            try:
                e = json.loads(ef.read_text())
                conn.execute("""
                    INSERT OR REPLACE INTO entities
                    (novel_id, slug, name, type, role, notes, aliases, facts)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (novel_id, ef.stem,
                      e.get("name"), e.get("entity_type"), e.get("role"),
                      e.get("notes"), json.dumps(e.get("aliases", [])),
                      json.dumps(e.get("facts", []))))
                count["entities"] += 1
            except Exception:
                pass

    conn.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description="NovelTea Engine SQLite migration")
    parser.add_argument("--sync", action="store_true", help="Sync JSON to DB")
    parser.add_argument("--query", help="Run a SQL query and print results")
    parser.add_argument("--novel", help="Sync specific novel only")
    args = parser.parse_args()

    conn = get_conn()
    init_schema(conn)

    if args.query:
        rows = conn.execute(args.query).fetchall()
        for row in rows:
            print(dict(row))
        return

    # Load registry
    registry_path = Path("novels/registry.json")
    if not registry_path.exists():
        print("ERROR: novels/registry.json not found")
        sys.exit(1)

    registry = json.loads(registry_path.read_text())
    novels = [n["id"] for n in registry.get("novels", [])]
    if args.novel:
        novels = [args.novel]

    print(f"\nSyncing {len(novels)} novel(s) to {DB_PATH}...\n")
    for novel_id in novels:
        count = sync_novel(conn, novel_id)
        print(f"  ✓ {novel_id}: {count['chapters']} chapters, {count['entities']} entities, "
              f"{count['humor']} humor, {count['reveals']} reveals, {count['glossary']} glossary")

    # Summary stats
    total_ch = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
    total_ent = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    print(f"\n  DB total: {total_ch} chapters, {total_ent} entities")
    print(f"  Location: {DB_PATH.absolute()}")

    conn.close()


if __name__ == "__main__":
    main()
