"""The corpus AUTHOR BRAINS (corpus/build_author_brain.py) put to work: how the authors of comparable published novels PLANNED.

Each corpus novel's author_brain.json holds its author's reconstructed plan notes: arcs (promise, plan, escalation, turn, payoff, cost,
seeds for later), long-running threads (the truth, the seed chapter, the clues with chapters, the misdirection, the reveal), on-page
milestones chapter by chapter, the author's rules and conspiracy craft, and the measured rhythm. The knowledge index carries one row
per arc (keyed by its first chapter), per thread (keyed by its seed chapter) and one craft row per novel, so a search finds the right
STAGE of the right story.

Three readers, each getting what it needs:
  - arc planner:   the comparable authors' arcs at the same stage of their books (by chapter range while the corpus covers it, by
                   meaning past that), their rules, and the corpus rhythm (arc lengths, events per 20 chapters);
  - conspiracy:    the comparable authors' long-running threads with their seed -> clue -> misdirection -> reveal timing, their
                   conspiracy craft, and the corpus timing figures;
  - timeline:      the comparable authors' on-page milestones over the same stretch, and the rhythm of fights, breakthroughs, reveals...
Learning material only: every block says to learn the planning and never reuse names, characters or events.
The novels chosen on the Author DNA tab (voice source) rank first wherever they have a brain.
"""
import json
import statistics as st
from pathlib import Path
from typing import Optional

_CACHE: dict = {}          # novel_id -> (mtime, brain)
_RHYTHM: dict = {}         # (sorted mtimes) -> corpus rhythm


def _G():
    from routers.generation import generate
    return generate


def _novels_dir() -> Path:
    return _G().CORPUS_PATH / "novels"


def brain(novel_id: str) -> Optional[dict]:
    p = _novels_dir() / novel_id / "author_brain.json"
    try:
        m = p.stat().st_mtime
    except OSError:
        return None
    hit = _CACHE.get(novel_id)
    if hit and hit[0] == m:
        return hit[1]
    try:
        b = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    _CACHE[novel_id] = (m, b)
    return b


def all_brains() -> dict:
    d = _novels_dir()
    out = {}
    if d.is_dir():
        for n in sorted(x.name for x in d.iterdir() if x.is_dir()):
            b = brain(n)
            if b and b.get("arcs"):
                out[n] = b
    return out


def _cut(s, n: int) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _log(project_id, msg, level="info"):
    if project_id:
        try:
            _G()._progress_log(project_id, msg, level)
        except Exception:
            pass


def preferred(project: dict) -> list:
    """The Author DNA tab's voice-source novels, when they have a brain."""
    vs = ((project or {}).get("author_profile") or {}).get("voice_source") or {}
    return [n for n in (vs.get("novels") or []) if brain(n)] if vs.get("mode") in ("novel", "mix") else []


def covered() -> int:
    """The last chapter the corpus brains reach (most cover chapters 1-240)."""
    tops = [int((b.get("chapters_covered") or [0, 0])[-1] or 0) for b in all_brains().values()]
    return max(tops) if tops else 0


def _search(query: str, category: str, top_k: int, chapter_from=None, chapter_to=None) -> list:
    if not (query or "").strip():
        return []
    try:
        from routers.corpus_tools.corpus import knowledge_search
        return knowledge_search(query.strip(), top_k=top_k, category=category, chapter_from=chapter_from, chapter_to=chapter_to)
    except Exception:
        return []


def corpus_rhythm() -> dict:
    """Medians across every brain: arc length, seed-to-reveal gap, share of threads still open, events per 20 chapters."""
    brains = all_brains()
    key = tuple(sorted((n, _CACHE[n][0]) for n in brains if n in _CACHE))
    if key in _RHYTHM:
        return _RHYTHM[key]
    lens, gaps, open_, total, per20 = [], [], 0, 0, {}
    for b in brains.values():
        for a in b.get("arcs") or []:
            ch = a.get("chapters") or []
            if len(ch) == 2 and isinstance(ch[0], int) and isinstance(ch[1], int):
                lens.append(ch[1] - ch[0] + 1)
        for t in b.get("threads") or []:
            total += 1
            s, r = t.get("seeded_chapter"), t.get("reveal_chapter")
            if isinstance(s, int) and isinstance(r, int) and r >= s:
                gaps.append(r - s)
            elif not r:
                open_ += 1
        for k, v in ((b.get("rhythm") or {}).get("milestones_per_20_chapters") or {}).items():
            per20.setdefault(k, []).append(float(v or 0))
    out = {"novels": len(brains), "arc_length_median": st.median(lens) if lens else None,
           "arc_length_range": [min(lens), max(lens)] if lens else None,
           "reveal_gap_median": st.median(gaps) if gaps else None, "reveal_gap_p75": (sorted(gaps)[int(len(gaps) * 0.75)] if gaps else None),
           "reveal_gap_max": max(gaps) if gaps else None, "threads_open_share": round(open_ / total, 2) if total else None,
           "per_20": {k: round(st.mean(v), 1) for k, v in per20.items()}}
    _RHYTHM.clear()
    _RHYTHM[key] = out
    return out


def _rhythm_line(r: dict) -> str:
    if not r.get("novels"):
        return ""
    per = ", ".join(f"{k} {v}" for k, v in sorted((r.get("per_20") or {}).items(), key=lambda kv: -kv[1]) if v)
    return (f"MEASURED ACROSS {r['novels']} PUBLISHED NOVELS (their first ~{covered()} chapters): arcs run {r['arc_length_median']} chapters "
            f"(median; {r['arc_length_range'][0]}-{r['arc_length_range'][1]}); a long-running secret is seeded {r['reveal_gap_median']} chapters "
            f"before it is revealed (median; a quarter wait {r['reveal_gap_p75']}+, the longest {r['reveal_gap_max']}), and "
            f"{int((r['threads_open_share'] or 0) * 100)}% of the big threads are still open at the end of that stretch. "
            f"On-page events per 20 chapters: {per}.") if r.get("arc_length_range") else ""


def _stage_arcs(novel: str, first: int, last: int) -> list:
    """A novel's own arcs that overlap chapters first-last (positional), from its brain."""
    out = []
    for a in (brain(novel) or {}).get("arcs") or []:
        ch = a.get("chapters") or []
        if len(ch) == 2 and isinstance(ch[0], int) and ch[0] <= last and ch[1] >= first:
            out.append(a)
    return out


def _arc_text(a: dict) -> str:
    ch = a.get("chapters") or ["?", "?"]
    seeds = "; ".join(f"ch{s.get('chapter')}: {s.get('what')}" for s in (a.get("seeds") or [])[:4])
    return (f"Arc ch{ch[0]}-{ch[-1]} '{a.get('label')}'. Promise: {a.get('promise')} Plan: {a.get('plan')} Escalation: {a.get('escalation')} "
            f"Turn: {a.get('turn')} Payoff: {a.get('payoff')} Cost: {a.get('cost')}" + (f" Seeded for later: {seeds}" if seeds else ""))


def arc_block(project: dict, first: int, last: int, query: str, project_id: str = None, cap: int = 5200) -> str:
    """For the arc planner: how comparable authors planned THIS stage of their books."""
    if not all_brains():
        return ""
    top = covered()
    staged = first <= top
    rows = _search(query, "author_arc", 6, chapter_from=max(1, first - 30) if staged else None, chapter_to=last if staged else None)
    picks, seen = [], set()
    for n in preferred(project):                         # the Author DNA novel(s) first, at the same chapters when covered
        arcs = _stage_arcs(n, first, last) if staged else []
        for a in arcs[:2]:
            picks.append((brain(n).get("title") or n, _arc_text(a)))
            seen.add(n)
    for r in rows:
        if len(picks) >= 5:
            break
        if r.get("novel_id") in seen or (r.get("novel_id"), r.get("chapter")) in seen:   # the Author DNA novel is already shown at this stage
            continue
        seen.add((r.get("novel_id"), r.get("chapter")))
        picks.append((r.get("novel_title") or r.get("novel_id"), r.get("text") or ""))
    if not picks:
        return ""
    _log(project_id, f"AUTHOR BRAIN (arc ch{first}-{last}): {len(picks)} comparable arc plan(s): " + "; ".join(t for t, _ in picks[:4]), "success")
    novels = [r.get("novel_id") for r in rows if r.get("novel_id")]
    rule_from = list(dict.fromkeys(preferred(project) + novels))[:2]
    rules = []
    for n in rule_from:
        b = brain(n) or {}
        if b.get("author_rules"):
            rules.append(f"  [{b.get('title') or n}] " + " | ".join(_cut(x, 200) for x in b["author_rules"][:6]))
    lines = [("HOW THE AUTHORS OF COMPARABLE PUBLISHED NOVELS PLANNED " + (f"THIS STAGE OF THEIR BOOKS (chapters near {first}-{last})" if staged
              else "ARCS LIKE THIS ONE") + " - their own plan notes, reconstructed: the promise each arc makes the reader, how it escalates, "
              "where it turns, how it pays off, what it costs the hero and what it seeds for later. Plan this arc with the same craft and the "
              "same discipline (a clear promise, a turn, a payoff, seeds for later arcs), but design an ORIGINAL arc: never reuse their names, "
              "characters, events or plot points:")]
    lines += [f"  [{t}]: {_cut(x, 900)}" for t, x in picks]
    if rules:
        lines += ["THOSE AUTHORS' OWN RULES:"] + rules
    rl = _rhythm_line(corpus_rhythm())
    if rl:
        lines.append(rl)
    return "\n".join(lines)[:cap]


def thread_block(project: dict, query: str, project_id: str = None, top_k: int = 6, cap: int = 5200) -> str:
    """For the conspiracy tree: how comparable authors ran their long secrets, seed to reveal, with chapter timing."""
    if not all_brains():
        return ""
    rows = _search(query, "author_thread", top_k + 2)
    picks = []
    for n in preferred(project):                         # the Author DNA novel's two longest-kept threads
        ts = sorted((t for t in (brain(n) or {}).get("threads") or [] if t.get("clues")),
                    key=lambda t: -((t.get("reveal_chapter") or 10**4) - (t.get("seeded_chapter") or 0)))
        for t in ts[:2]:
            clues = "; ".join(f"ch{c.get('chapter')}: {c.get('reader_sees')}" for c in (t.get("clues") or [])[:6])
            rev = f"Revealed ch{t['reveal_chapter']}: {t.get('how_revealed')}" if t.get("reveal_chapter") else "Still hidden."
            picks.append((brain(n).get("title") or n, f"[{t.get('kind')}] {t.get('name')}. Truth: {t.get('truth')} Seeded ch{t.get('seeded_chapter')}. "
                                                      f"Clues: {clues}. Misdirection: {t.get('misdirection')} {rev} Effect: {t.get('payoff_effect')}"))
    for r in rows:
        if len(picks) >= top_k:
            break
        picks.append((r.get("novel_title") or r.get("novel_id"), r.get("text") or ""))
    if not picks:
        return ""
    _log(project_id, f"AUTHOR BRAIN (conspiracy): {len(picks)} comparable thread(s): " + "; ".join(t for t, _ in picks[:4]), "success")
    craft = []
    for n in list(dict.fromkeys(preferred(project) + [r.get("novel_id") for r in rows if r.get("novel_id")]))[:3]:
        b = brain(n) or {}
        if b.get("conspiracy_craft"):
            craft.append(f"  [{b.get('title') or n}] " + " | ".join(_cut(x, 200) for x in b["conspiracy_craft"][:5]))
    lines = ["HOW THE AUTHORS OF COMPARABLE PUBLISHED NOVELS RAN THEIR LONG SECRETS - each thread from the author's side: the truth they "
             "knew, the chapter they first seeded it, the clues the reader actually saw and when, how they misdirected, and when and how it "
             "came out. Use the same timing and the same kinds of clue and misdirection; never reuse their names or plots:"]
    lines += [f"  [{t}]: {_cut(x, 850)}" for t, x in picks]
    if craft:
        lines += ["THOSE AUTHORS' CONSPIRACY CRAFT:"] + craft
    rl = _rhythm_line(corpus_rhythm())
    if rl:
        lines.append(rl)
    return "\n".join(lines)[:cap]


def timeline_material(project: dict, first: int, last: int, query: str, project_id: str = None, cap: int = 6000) -> str:
    """For the Timeline's suggestions: the on-page milestones comparable authors put over the same stretch, and the rhythm."""
    brains = all_brains()
    if not brains:
        return ""
    top = covered()
    staged = first <= top
    span = last - first + 1
    # which novels, and which of their chapters: the same chapters while the corpus covers them, else the best-matching arc's span
    sources = []
    for n in preferred(project):
        sources.append((n, first, min(last, top) if staged else None))
    for r in _search(query, "author_arc", 6, chapter_from=max(1, first - 30) if staged else None, chapter_to=last if staged else None):
        n = r.get("novel_id")
        if n in brains and all(s[0] != n for s in sources):
            if staged:
                sources.append((n, first, min(last, top)))
            else:
                a0 = r.get("chapter") or 1
                sources.append((n, a0, a0 + span - 1))
        if len(sources) >= 4:
            break
    lines, used = [], []
    for n, a, b in sources[:4]:
        if b is None:
            continue
        ms = [m for m in (brains[n].get("milestones") or []) if a <= (m.get("chapter") or 0) <= b]
        if not ms:
            continue
        used.append(brains[n].get("title") or n)
        lines.append(f"  [{brains[n].get('title') or n}, chapters {a}-{b}]:")
        lines += [f"    ch{m['chapter']} [{m['category']}] {_cut(m['title'], 90)}: {_cut(m.get('mc_sees'), 160)}" for m in ms[:16]]
    if not lines:
        return ""
    _log(project_id, f"AUTHOR BRAIN (timeline ch{first}-{last}): milestones from " + "; ".join(used), "success")
    out = ["WHAT COMPARABLE PUBLISHED NOVELS PUT ON THE PAGE OVER A STRETCH LIKE THIS (their milestones, as their heroes lived them). "
           "Learn the rhythm and the kinds of moment; never reuse their names or events:"] + lines
    rl = _rhythm_line(corpus_rhythm())
    if rl:
        out.append(rl)
    return "\n".join(out)[:cap]
