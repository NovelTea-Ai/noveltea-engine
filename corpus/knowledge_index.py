"""Corpus-wide semantic search — local embeddings via Ollama, no vector-DB
dependency (brute-force cosine similarity over a numpy matrix is entirely
fast enough at this corpus's scale — tens of thousands of chunks, not
millions).

V4 Phase 4 (doc Layers 19/27/28) — the one genuinely new subsystem in the
roadmap; Phases 1-3 were all "wire up already-extracted data," this is real
new infrastructure. Scoped to the 16-novel CORPUS (craft-pattern search
across the author's own past novels), not the author's in-progress project.

Usage:
    from knowledge_index import embed_text, search, init_db, store_chunk
    results = search("find symbolic uses of fire", top_k=5)
"""
import json
import sqlite3
import struct
import urllib.request
from pathlib import Path

DB_PATH = Path(__file__).parent / "knowledge_index.db"
OLLAMA_HOST = "http://127.0.0.1:11434"   # not "localhost": on Windows that costs ~2s per call (IPv6 attempt first; Ollama listens on IPv4 only)
EMBED_MODEL = "nomic-embed-text"
# Second embedding per chunk, from nomic-embed-text fine-tuned on this corpus
# (corpus/embedding_ft/; loaded into Ollama from its GGUF). Searches use BOTH
# models and merge their scores — the two pick different material and cover each
# other's blind spots. Stored in its own column; the base `embedding` column is
# never modified.
EMBED_MODEL_TUNED = "nomic-embed-corpus"
EMBED_DIM = 768
# Categories a search returns only when it asks for them by name. humor's 11k
# beats (build_humor_index.py) would otherwise crowd the unfiltered searches
# (character roster enrichment) that were tuned before it existed.
OPT_IN_CATEGORIES = ("humor", "mechanics")   # mechanics: build_mechanics_deltas.py (chapter/fight/run construction)


def embed_text(text: str, timeout: int = 30, model: str = None) -> list:
    """Returns a 768-float embedding vector via the local Ollama instance
    (the base model unless `model` names another, e.g. EMBED_MODEL_TUNED)."""
    body = json.dumps({"model": model or EMBED_MODEL, "prompt": text[:8000]}).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/embeddings", data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    emb = data.get("embedding")
    if not emb or len(emb) != EMBED_DIM:
        raise RuntimeError(f"unexpected embedding shape from Ollama: {len(emb) if emb else 0} dims")
    return emb


def embed_texts_batch(texts: list, model: str, timeout: int = 300) -> list:
    """Embed many texts in one Ollama /api/embed call (much faster than one call
    per text for a bulk backfill). Returns one 768-float vector per input."""
    body = json.dumps({"model": model, "input": [t[:8000] for t in texts]}).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_HOST}/api/embed", data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        embs = json.loads(resp.read().decode("utf-8")).get("embeddings")
    if not embs or len(embs) != len(texts) or any(len(e) != EMBED_DIM for e in embs):
        raise RuntimeError(f"unexpected batch embedding result from Ollama ({len(embs) if embs else 0} for {len(texts)} texts)")
    return embs


def ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _pack(vec: list) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            novel_id TEXT NOT NULL,
            novel_title TEXT NOT NULL,
            category TEXT NOT NULL,
            chapter INTEGER,
            text TEXT NOT NULL,
            meta TEXT,
            embedding BLOB NOT NULL,
            UNIQUE(novel_id, category, chapter, text)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_novel ON chunks(novel_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON chunks(category)")
    # Additive migration: the tuned model's vector lives in its own nullable column.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
    if "embedding_tuned" not in cols:
        conn.execute("ALTER TABLE chunks ADD COLUMN embedding_tuned BLOB")
    # Which model produced each embedding column. Search refuses to fuse the two if
    # these don't match the models it is about to embed the query with — vectors from
    # different models are meaningless to compare, and (both being 768-dim) a mix-up
    # would degrade results silently instead of failing.
    conn.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT OR IGNORE INTO index_meta (key, value) VALUES ('embedding_model', ?)", (EMBED_MODEL,))
    conn.execute("INSERT OR IGNORE INTO index_meta (key, value) VALUES ('embedding_tuned_model', ?)", (EMBED_MODEL_TUNED,))
    conn.commit()
    return conn


def store_chunk(conn: sqlite3.Connection, novel_id: str, novel_title: str, category: str,
                text: str, chapter, meta: dict, embedding: list, embedding_tuned: list = None):
    """Store one chunk. The tuned-model vector is computed here when the caller
    doesn't supply one, so every indexer (knowledge, blueprint, project-systems)
    keeps the second column filled without each needing its own change. If the
    tuned model isn't available the column stays NULL and the backfill script
    fills it in later — indexing itself never fails because of it."""
    # The UNIQUE key can't catch a twin when chapter is NULL (SQLite treats NULLs as distinct), which let
    # chapter-less chunks pile up 6,987 duplicate copies across the corpus before backfill_index_chapters.py.
    if chapter is None and conn.execute(
            "SELECT 1 FROM chunks WHERE novel_id=? AND category=? AND chapter IS NULL AND text=?",
            (novel_id, category, text)).fetchone():
        return
    if embedding_tuned is None:
        try:
            embedding_tuned = embed_text(text, model=EMBED_MODEL_TUNED)
        except Exception:
            embedding_tuned = None
    try:
        conn.execute(
            "INSERT OR IGNORE INTO chunks (novel_id, novel_title, category, chapter, text, meta, embedding, embedding_tuned) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (novel_id, novel_title, category, chapter, text, json.dumps(meta, ensure_ascii=False), _pack(embedding),
             _pack(embedding_tuned) if embedding_tuned is not None else None),
        )
    except sqlite3.IntegrityError:
        pass


def existing_keys(conn: sqlite3.Connection, novel_id: str) -> set:
    """(category, chapter, text) tuples already indexed for this novel — so a
    re-run (e.g. after new chapters are added) can skip calling embed_text()
    entirely for content that's already there, instead of re-embedding
    everything and relying on the UNIQUE constraint to discard duplicates
    AFTER paying for the (locally free, but not time-free) embedding call.
    Chapter is normalized to a comparable form since SQLite may hand back
    None consistently either way — a plain tuple round-trips fine."""
    rows = conn.execute(
        "SELECT category, chapter, text FROM chunks WHERE novel_id = ?", (novel_id,)
    ).fetchall()
    return {(cat, chapter, text) for cat, chapter, text in rows}


# In-process cache of the whole index as a normalized matrix — rebuilt only
# when the db file's mtime changes, so repeated searches in the same run
# (or the same long-lived backend process) don't re-read/re-parse thousands
# of BLOB rows every call.
_CACHE = {"mtime": None, "matrix": None, "rows": None}


def _load_matrix():
    import numpy as np
    if not DB_PATH.exists():
        return None, None
    mtime = DB_PATH.stat().st_mtime
    if _CACHE["mtime"] == mtime and _CACHE["matrix"] is not None:
        return _CACHE["matrix"], _CACHE["rows"]
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, novel_id, novel_title, category, chapter, text, meta, embedding FROM chunks"
    ).fetchall()
    conn.close()
    if not rows:
        return None, None
    vecs = np.array([_unpack(r[7]) for r in rows], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1e-9
    vecs = vecs / norms
    _CACHE.update(mtime=mtime, matrix=vecs, rows=rows)
    return vecs, rows


def search(query_text: str, top_k: int = 5, category: str = None, exclude_novel_id: str = None) -> list:
    """Embed query_text and return the top_k most semantically similar
    chunks in the corpus: [{novel_id, novel_title, category, chapter, text,
    meta, score}, ...], highest score first.
    category: optional filter ("reveal" | "scheme" | "symbol" | "prose").
    exclude_novel_id: skip one novel (e.g. don't ground a project's own
    reference novel in itself, if it were ever added to the corpus)."""
    import numpy as np
    matrix, rows = _load_matrix()
    if matrix is None:
        return []
    qvec = np.array(embed_text(query_text), dtype=np.float32)
    qnorm = np.linalg.norm(qvec)
    if qnorm == 0:
        return []
    qvec = qvec / qnorm
    sims = matrix @ qvec
    order = np.argsort(-sims)
    out = []
    for i in order:
        row = rows[i]
        _id, novel_id, novel_title, cat, chapter, text, meta_json, _ = row
        if category and cat != category:
            continue
        if not category and cat in OPT_IN_CATEGORIES:
            continue
        if exclude_novel_id and novel_id == exclude_novel_id:
            continue
        out.append({
            "novel_id": novel_id, "novel_title": novel_title, "category": cat,
            "chapter": chapter, "text": text,
            "meta": json.loads(meta_json) if meta_json else {},
            "score": float(sims[i]),
        })
        if len(out) >= top_k:
            break
    return out
