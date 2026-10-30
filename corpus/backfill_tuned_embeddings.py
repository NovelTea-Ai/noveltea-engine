"""
backfill_tuned_embeddings.py - Give every indexed chunk its second embedding, from the
corpus-fine-tuned model (nomic-embed-corpus in Ollama), stored in the chunks table's
embedding_tuned column.

ADDITIVE ONLY: the original `embedding` column, the text and every other column are never
touched — this only fills the new nullable embedding_tuned column. Resumable: it selects
rows where embedding_tuned IS NULL, so a stop/crash/restart continues where it left off.
Search uses both vectors once every candidate row has one, and quietly uses the base
vector alone until then (see routers/corpus.py knowledge_search).

Usage:
    python backfill_tuned_embeddings.py                 # every row still missing one
    python backfill_tuned_embeddings.py --category story_shape    # a subset (also used for testing)
"""
import argparse
import sys
import time

import knowledge_index as ki

BATCH = 32
COMMIT_EVERY_BATCHES = 8   # the app reloads its in-memory index whenever this file changes, so don't commit on every batch


def _live(kind: str, preview: str, novel: str = ""):
    try:
        from llm_client import write_live_status
        write_live_status("tuned_embeddings", novel=novel, kind=kind, batch_size=BATCH, preview=preview[:200])
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", help="only rows of this category")
    args = ap.parse_args()

    if not ki.ollama_available():
        print("ERROR: Ollama not reachable at localhost:11434 — is it running?")
        sys.exit(1)
    try:
        ki.embed_text("test", model=ki.EMBED_MODEL_TUNED)
    except Exception as e:
        print(f"ERROR: tuned model '{ki.EMBED_MODEL_TUNED}' is not available in Ollama ({str(e)[:120]}). "
              f"Create it from embedding_ft's GGUF first.")
        sys.exit(1)

    conn = ki.init_db()   # also adds the embedding_tuned column on first run
    where = "embedding_tuned IS NULL" + (" AND category = ?" if args.category else "")
    params = (args.category,) if args.category else ()
    remaining = conn.execute(f"SELECT COUNT(*) FROM chunks WHERE {where}", params).fetchone()[0]
    print(f"{remaining} chunk(s) need a tuned embedding" + (f" (category={args.category})" if args.category else ""), flush=True)

    done = failed = 0
    since_commit = 0
    t0 = time.time()
    last_id = 0
    while True:
        rows = conn.execute(f"SELECT id, novel_title, text FROM chunks WHERE {where} AND id > ? ORDER BY id LIMIT ?",
                            (*params, last_id, BATCH)).fetchall()
        if not rows:
            break
        last_id = rows[-1][0]
        _live("embedding", rows[0][2], novel=rows[0][1])
        try:
            embs = ki.embed_texts_batch([r[2] for r in rows], ki.EMBED_MODEL_TUNED)
        except Exception as e:
            # One bad text shouldn't sink the batch: retry one by one, skip only the ones that truly fail.
            embs = []
            for r in rows:
                try:
                    embs.append(ki.embed_text(r[2], model=ki.EMBED_MODEL_TUNED))
                except Exception as e2:
                    embs.append(None)
                    print(f"  WARN chunk {r[0]} skipped: {str(e2)[:100]}", flush=True)
        for r, emb in zip(rows, embs):
            if emb is None:
                failed += 1
                continue
            conn.execute("UPDATE chunks SET embedding_tuned = ? WHERE id = ?", (ki._pack(emb), r[0]))
            done += 1
        since_commit += 1
        if since_commit >= COMMIT_EVERY_BATCHES:
            conn.commit()
            since_commit = 0
            rate = done / max(time.time() - t0, 1e-9)
            print(f"  {done}/{remaining} embedded ({rate:.1f}/s, about {(remaining - done - failed) / max(rate, 1e-9) / 60:.0f} min left)", flush=True)
    conn.commit()
    conn.close()
    print(f"DONE. {done} embedded, {failed} failed/skipped, in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
