"""
chapter_lookup.py — which chapter a corpus record came from, read from the
per-chapter extractions (deltas_v3/chN.json: the file IS the chapter).

The merged whole-novel files the index builders read (prose/samples.json,
entities/*.json voice samples, humor/instances.json, reveals/log.json) lose the
chapter on a large share of records — e.g. a reference novel: every prose and
dialogue chunk, 278 of 796 humor beats and 185 of 503 reveals were indexed with no
chapter. Every one of those records still sits in the delta file of the chapter it
came from, so the builders look the chapter up here by the record's text whenever
the merged record has none.
"""
import json
import re
from pathlib import Path

_CH_FILE = re.compile(r"^ch(\d+)\.json$")
_CACHE: dict = {}


def norm(text) -> str:
    """Comparable form of a record's text: lowercase, curly quotes and punctuation
    at the ends dropped, whitespace collapsed, first 160 characters."""
    t = str(text or "").lower()
    t = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    t = " ".join(t.split()).strip(" \"'.,!?…-—")
    return t[:160]


def _humor_parts(h: dict):
    # Same schemas as build_humor_index.beat_parts.
    setup = str(h.get("setup") or h.get("context") or h.get("description") or "").strip()
    payoff = str(h.get("payoff") or h.get("excerpt") or h.get("example_text") or "").strip()
    return setup, payoff


def build(novel_dir: Path) -> dict:
    """{"prose"|"dialogue"|"humor"|"reveal": {norm(text): chapter}} for one novel.
    A text seen in several chapters keeps its earliest chapter."""
    novel_dir = Path(novel_dir)
    key = str(novel_dir.resolve())
    if key in _CACHE:
        return _CACHE[key]
    out = {"prose": {}, "dialogue": {}, "humor": {}, "reveal": {}}

    def put(cat, text, ch):
        k = norm(text)
        if len(k) >= 8 and (k not in out[cat] or ch < out[cat][k]):
            out[cat][k] = ch

    deltas = novel_dir / "deltas_v3"
    for f in (deltas.iterdir() if deltas.is_dir() else []):
        m = _CH_FILE.match(f.name)
        if not m:
            continue                    # chN.haiku45-original.json etc. are test/backup copies
        ch = int(m.group(1))
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for s in d.get("prose_samples") or []:
            if isinstance(s, dict):
                put("prose", s.get("excerpt"), ch)
        for c in d.get("character_voice_samples") or []:
            if isinstance(c, dict):
                for s in c.get("dialogue_samples") or []:
                    if isinstance(s, dict):
                        put("dialogue", s.get("line"), ch)
        for h in d.get("humor_instances") or []:
            if isinstance(h, dict):
                setup, payoff = _humor_parts(h)
                put("humor", payoff or setup, ch)
                if setup and payoff:
                    put("humor", setup + " → " + payoff, ch)
        for r in d.get("reveals") or []:
            if isinstance(r, dict):
                put("reveal", r.get("content"), ch)
    _CACHE[key] = out
    return out


_WORD = re.compile(r"[a-z][a-z'-]{3,}")
_WORDS_CACHE: dict = {}


def _chapter_words(novel_dir: Path):
    """({chapter: set of words in its whole delta file}, {word: idf}) for the fuzzy fallback."""
    key = str(Path(novel_dir).resolve())
    if key in _WORDS_CACHE:
        return _WORDS_CACHE[key]
    import math
    words = {}
    deltas = Path(novel_dir) / "deltas_v3"
    for f in (deltas.iterdir() if deltas.is_dir() else []):
        m = _CH_FILE.match(f.name)
        if m:
            try:
                words[int(m.group(1))] = set(_WORD.findall(f.read_text(encoding="utf-8").lower()))
            except Exception:
                pass
    df = {}
    for ws in words.values():
        for w in ws:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(words))
    idf = {w: math.log(n / c) for w, c in df.items()}
    _WORDS_CACHE[key] = (words, idf)
    return words, idf


def find_fuzzy(novel_dir: Path, text, min_score: float = 0.6, margin: float = 1.25):
    """The chapter whose delta file shares most of `text`'s distinctive words — for records the
    merged files reworded (a reveal rewritten at merge time no longer matches its delta text).
    Only a clear winner counts: at least min_score of the text's word weight, and margin times
    the runner-up. Otherwise None, so a doubtful record keeps no chapter rather than a wrong one."""
    words, idf = _chapter_words(novel_dir)
    mine = {w for w in _WORD.findall(str(text or "").lower()) if idf.get(w, 0) > 0.5}
    total = sum(idf[w] for w in mine)
    if len(mine) < 4 or total <= 0:
        return None
    scored = sorted(((sum(idf[w] for w in mine & ws) / total, ch) for ch, ws in words.items()), reverse=True)
    if not scored or scored[0][0] < min_score:
        return None
    if len(scored) > 1 and scored[0][0] < margin * scored[1][0]:
        return None
    return scored[0][1]


def find(novel_dir: Path, category: str, *texts):
    """The chapter of the first of `texts` found under `category`; failing an exact match,
    the fuzzy match of the first non-empty text; else None."""
    table = build(novel_dir).get(category) or {}
    for t in texts:
        k = norm(t)
        if k and k in table:
            return table[k]
    first = next((t for t in texts if str(t or "").strip()), "")
    return find_fuzzy(novel_dir, first) if first else None
