"""
author_brain_claude.py - the author-level pass of the AUTHOR BRAIN, done by Claude Code with tools (no cloud LLM pipeline calls).

build_author_brain_local.py builds a novel's author brain with Python + local semantic search (arcs, threads, milestones, rhythm) and
writes a digest. This step then runs the Claude Code CLI headless (subscription accounts, like the app's other Claude calls) inside
the corpus folder with a small tool set:
  - Read / Grep / Glob over the corpus files (chapter summaries in deltas_v3, the digest, the rolling summary),
  - curl to the app's knowledge search (POST http://127.0.0.1:7432/api/corpus/knowledge-search with category / novel / chapter-range
    filters) and mechanics search (/api/reference/search),
  - Write / Edit on ONE file: novels/<id>/author_brain/author_notes.json.
Claude checks the Python threads against the summaries (grep for the names, filtered searches for the real seed, clues and reveal),
adds the big secrets Python missed, drops weak or duplicate threads, and writes the author's engine, book shape, rules and conspiracy
craft. Python then folds the notes into author_brain.json (build_author_brain_local.apply_notes), so the Arc planner, Conspiracy and
Timeline read them.

A novel is skipped while its notes are current (written when it had no fewer than 20 chapters less than now). The previous notes are
kept as author_notes.prev.json.

Usage (needs numpy, e.g. py -3.12):
    py -3.12 author_brain_claude.py --novel my_novel
    py -3.12 author_brain_claude.py                       # every novel whose notes are missing or stale
    options: --model claude-sonnet-5-5  --force
"""
import argparse
import os
import subprocess
import time
from pathlib import Path

import build_author_brain_local as B

HERE = Path(__file__).resolve().parent
EXAMPLE = ""          # id of a finished author_notes.json to show Claude as a worked example (optional; none ships)
APP = os.environ.get("NM_APP_URL", "http://127.0.0.1:7432")

INSTRUCTIONS = """You are writing the AUTHOR'S NOTES for the corpus web novel "{title}" (novel id {nid}), chapters {first}-{last}, as the
author who planned it. Work in this folder with the tools you have, then write ONE file: {notes_path}

WHAT YOU HAVE
- {digest_path}: the Python pass: arcs (chapter ranges, the author's per-chapter intent), threads (secrets clustered by meaning, with
  seed chapter, clue chapters and the reveal found by meaning; ids t1, t2...), and the measured rhythm.
- novels/{nid}/rolling_summary.json: the whole story so far ("summary").
- novels/{nid}/deltas_v3/ch<N>.json: each chapter's extraction. "summary" is the chapter summary; "reveals", "knowledge_state",
  "scheme_instances", "author_intent" are there too. Grep them for names: names are exact where meaning is fuzzy.
- The app's semantic search (filters are what make it useful):
    curl -s -X POST {app}/api/corpus/knowledge-search -H "Content-Type: application/json" -d '{{"query": "...", "category": "reveal", "novel_id": "{nid}", "chapter_from": 100, "chapter_to": 240, "top_k": 5}}'
  categories: summary (chapter summaries), reveal, scheme, knowledge, glossary, story_shape, antagonist_template.
    curl -s -X POST {app}/api/reference/search -H "Content-Type: application/json" -d '{{"query": "...", "novel_id": "{nid}", "kind": "fight", "top_k": 5}}'
  kinds: chapter, beat, fight, run, cast, device.
{example_line}
WHAT TO DO
1. Read the digest and the rolling summary. Note the story's two to four BIGGEST secrets (hidden identities, a hidden mastermind, a
   hidden power, a hidden history). Check whether the digest's threads cover them.
2. For every big secret the threads miss: grep the summaries for its names to find where it first appears, and use the reveal search
   (novel filter, chapter range after the seed) to find where and how it comes out. Collect 3-6 dated clues the reader actually sees.
   Add each as an "add_threads" entry.
3. For the digest's threads: give the real ones a short "name", a plain "truth", the "misdirection" (how the author kept readers from
   guessing) and the "payoff_effect". Mark weak, duplicate or merely generic ones {{"drop": true}} (e.g. "his cultivation improved").
   Use the thread ids exactly as in the digest.
4. Write the author-level notes: "engine" (one sentence), "book_shape" (3-5 sentences on how chapters {first}-{last} are paced, with
   chapter numbers), "author_rules" (8-12 specific, usable rules this author follows) and "conspiracy_craft" (5-8 rules for how this
   author hides truths, plants clues, misdirects and times reveals, with the chapter numbers that show it).
5. Only fix an arc ("arcs": {{"<first>-<last>": {{"label", "promise", "turn", "payoff", "cost"}}}}) when the digest's version is clearly
   wrong; leave the rest.
Every chapter number must come from the files or the searches, never a guess. Use this novel's own names.

THE FILE ({notes_path}), valid JSON:
{{"by": "Claude Code (author brain pass)", "source_chapter_count": {count}, "engine": "...", "book_shape": "...", "author_rules": ["..."],
  "conspiracy_craft": ["..."], "add_threads": [{{"name", "kind", "truth", "hidden_from", "seeded_chapter", "clues": [{{"chapter", "reader_sees"}}],
  "misdirection", "reveal_chapter", "how_revealed", "payoff_effect"}}], "threads": {{"t1": {{"name", "truth", "misdirection", "payoff_effect"}}, "t7": {{"drop": true}}}},
  "arcs": {{}}}}
kind is one of: identity, conspiracy, mystery, power, romance, rivalry, world, promise.
When the file is written, reply with one line: DONE and how many threads you added and dropped."""


def _notes_current(nid: str, count: int) -> bool:
    n = B.load_json(B.NOVELS_PATH / nid / "author_brain" / "author_notes.json")
    return bool(n) and count - int(n.get("source_chapter_count") or 0) < 20


def _cli():
    """The app's own Claude CLI resolution (bypasses the Windows .cmd shim) and subscription env (no API key)."""
    import llm_client as L
    argv = L._cli_argv()
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_API_KEY")}
    return argv, env, L


def run(nid: str, model: str, force: bool = False, timeout: int = 2400) -> bool:
    brain = B.build(nid)                                 # fresh Python pass + digest (folds any existing notes)
    if not brain:
        return False
    count = brain["source_chapter_count"]
    if not force and _notes_current(nid, count):
        print(f"[SKIP] {nid}: author notes current", flush=True)
        return True
    wd = B.NOVELS_PATH / nid / "author_brain"
    notes = wd / "author_notes.json"
    notes_rel = f"novels/{nid}/author_brain/author_notes.json"
    if notes.exists():
        (wd / "author_notes.prev.json").write_bytes(notes.read_bytes())
    ex_id = EXAMPLE if nid != EXAMPLE else None
    ex_file = B.NOVELS_PATH / (ex_id or "_") / "author_brain" / "author_notes.json"
    example_line = (f"- novels/{ex_id}/author_brain/author_notes.json: a finished example for another novel. Match its shape and its level of detail.\n"
                    if ex_id and ex_file.exists() else "")
    prompt = INSTRUCTIONS.format(example_line=example_line, title=brain["title"], nid=nid, first=brain["chapters_covered"][0], last=brain["chapters_covered"][1],
                                 notes_path=notes_rel, digest_path=f"novels/{nid}/author_brain/digest.md", app=APP,
                                 count=count)
    argv, env, L = _cli()
    tools = ["Read", "Grep", "Glob", f"Bash(curl -s -X POST {APP}/api/corpus/knowledge-search:*)",
             f"Bash(curl -s -X POST {APP}/api/reference/search:*)", f"Write({notes_rel})", f"Edit({notes_rel})"]
    args = argv + ["-p", "--model", model, "--output-format", "text", "--max-turns", "60", "--allowedTools", *tools]
    print(f"[{nid}] Claude Code author pass ({model}): reading the digest, grepping and searching...", flush=True)
    try:        # the Corpus Pipeline card shows what is being done right now
        from llm_client import write_live_status
        write_live_status("author_brain", novel=nid, kind="Claude author pass", preview=f"{brain['title']}: grep + filtered search, then the author's notes")
    except Exception:
        pass
    t0 = time.time()
    before = notes.stat().st_mtime if notes.exists() else None
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        r = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(HERE), env=env, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired:
        print(f"[ERROR] {nid}: the Claude pass timed out after {timeout // 60} min", flush=True)
        return False
    tail = (r.stdout or r.stderr or "").strip().splitlines()[-1:] or [""]
    print(f"[{nid}] Claude replied in {time.time() - t0:.0f}s: {tail[0][:200]}", flush=True)
    if not notes.exists() or notes.stat().st_mtime == before:
        print(f"[ERROR] {nid}: no author notes were written (exit {r.returncode}): {(r.stderr or r.stdout or '')[-300:]}", flush=True)
        return False
    data = B.load_json(notes)
    if not isinstance(data, dict) or not data.get("author_rules"):
        print(f"[ERROR] {nid}: the notes file is not usable JSON; the previous notes are kept", flush=True)
        prev = wd / "author_notes.prev.json"
        if prev.exists():
            notes.write_bytes(prev.read_bytes())
        else:
            notes.unlink()
        return False
    data.setdefault("source_chapter_count", count)
    B.save_json(notes, data)
    brain = B.build(nid)                                 # fold the notes in
    print(f"[OK] {nid}: author notes folded in ({len(data.get('add_threads') or [])} threads added, "
          f"{sum(1 for v in (data.get('threads') or {}).values() if isinstance(v, dict) and v.get('drop'))} dropped)", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser(description="Claude Code author pass for the author brains")
    ap.add_argument("--novel", help="one novel id (omit for every novel whose notes are missing or stale)")
    ap.add_argument("--model", default=None, help="Claude model id (default: the app's Claude model)")
    ap.add_argument("--force", action="store_true", help="rewrite the notes even when current")
    args = ap.parse_args()
    import llm_client as L
    model = args.model or getattr(L, "DEFAULT_MODEL", "claude-sonnet-5-5")
    novels = [args.novel] if args.novel else [p.name for p in sorted(B.NOVELS_PATH.iterdir()) if p.is_dir()]
    ok = 0
    for n in novels:
        try:
            ok += bool(run(n, model, force=args.force))
        except Exception as e:
            print(f"[ERROR] {n}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"\n[DONE] {ok}/{len(novels)} novel(s) have current author notes", flush=True)


if __name__ == "__main__":
    os.chdir(HERE)
    main()
