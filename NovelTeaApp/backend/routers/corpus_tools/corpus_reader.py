"""Corpus Reader: read the corpus novels' raw chapters (read-only). Served over the app's own address, so it loads over https
when the app is opened through the Tailscale https address (relative URLs, no hard-coded host)."""
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import CORPUS_PATH

router = APIRouter()
RAW_DIR = CORPUS_PATH / "raw"
NOVELS_DIR = CORPUS_PATH / "novels"
_CH = re.compile(r"^ch0*(\d+)\.txt$", re.I)
_TITLE = re.compile(r"^chapter\s*\d+\s*[-\u2013:]\s*(.+)$", re.I)


def _chapters(novel_id: str) -> dict:
    d = RAW_DIR / novel_id
    out = {}
    if d.is_dir():
        for f in d.glob("ch*.txt"):
            m = _CH.match(f.name)
            if m:
                out[int(m.group(1))] = f
    return out


def _novel_title(novel_id: str) -> str:
    try:
        title = json.loads((NOVELS_DIR / novel_id / "novel_metadata.json").read_text(encoding="utf-8")).get("title") or ""
    except Exception:
        title = ""
    if not title or title == novel_id:                       # no real title saved: "my_novel" -> "My Pua System"
        title = novel_id.replace("_", " ").title()
    return title


def _real_title(t: str) -> str:
    """A chapter title worth showing. Raws repeat things: "Chapter 4", or "a reference novel - Chapter 12 - Wu Xin Xiang Tian"."""
    t = (t or "").strip()
    for _ in range(3):
        m = re.match(r"^.*?chapter\s*\d+\s*[-–—:]\s*(.+)$", t, re.I)
        if not m:
            break
        t = m.group(1).strip()
    return "" if re.match(r"^(.*\s-\s)?chapter\s*\d+$", t, re.I) else t


def _read(f: Path) -> str:
    return f.read_text(encoding="utf-8", errors="replace")


def _split(text: str):
    """(title, paragraphs): the title line(s) ("Chapter N - Title", often twice) are dropped from the body."""
    lines = [l.strip() for l in re.split(r"\n+", text or "") if l.strip()]
    title = ""
    while lines and re.match(r"^chapter\s*\d+", lines[0], re.I) and len(lines[0].split()) <= 20:
        m = _TITLE.match(lines[0])
        if m and not title:
            title = m.group(1).strip()
        lines.pop(0)
    return title, [l.replace("\ufffd", "'") for l in lines]


@router.get("/novels")
def novels():
    out = []
    for d in sorted(p for p in RAW_DIR.iterdir() if p.is_dir()) if RAW_DIR.exists() else []:
        chs = _chapters(d.name)
        if not chs:
            continue
        ext = {int(m.group(1)) for f in (NOVELS_DIR / d.name / "deltas_v3").glob("ch*.json")
               if (m := re.match(r"^ch(\d+)\.json$", f.name))} if (NOVELS_DIR / d.name / "deltas_v3").exists() else set()
        out.append({"id": d.name, "title": _novel_title(d.name), "chapters": len(chs), "first": min(chs), "last": max(chs),
                    "extracted": len(ext)})
    return {"novels": out}


@router.get("/novel/{novel_id}/chapters")
def chapter_list(novel_id: str):
    chs = _chapters(novel_id)
    if not chs:
        raise HTTPException(404, "No chapters for that novel")
    out = []
    for n in sorted(chs):
        try:
            with open(chs[n], encoding="utf-8", errors="replace") as fh:
                head = [next(fh, "") for _ in range(2)]
        except Exception:
            head = []
        title = ""
        for h in head:
            m = _TITLE.match(h.strip())
            if m:
                title = _real_title(m.group(1))
                break
        out.append({"n": n, "title": title})
    return {"novel": novel_id, "title": _novel_title(novel_id), "chapters": out}


@router.get("/novel/{novel_id}/rolling-summary")
def rolling_summary(novel_id: str):
    """The novel's rolling summary (the story so far, as the extraction folds it up) for the reader's summary pop-up."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", novel_id):
        raise HTTPException(404, "No such novel")
    try:
        d = json.loads((NOVELS_DIR / novel_id / "rolling_summary.json").read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(404, "No rolling summary for that novel yet")
    text = str(d.get("summary") or "").strip()
    if not text:
        raise HTTPException(404, "No rolling summary for that novel yet")
    return {"novel": novel_id, "title": _novel_title(novel_id), "summary": text,
            "through": d.get("last_chapter_folded"), "updated_at": d.get("updated_at")}


@router.get("/novel/{novel_id}/chapter/{n}")
def chapter(novel_id: str, n: int):
    chs = _chapters(novel_id)
    if n not in chs:
        raise HTTPException(404, "Chapter not found")
    title, paras = _split(_read(chs[n]))
    nums = sorted(chs)
    i = nums.index(n)
    summary = ""
    try:
        summary = json.loads((NOVELS_DIR / novel_id / "deltas_v3" / f"ch{n}.json").read_text(encoding="utf-8")).get("summary") or ""
    except Exception:
        pass
    return {"novel": novel_id, "novel_title": _novel_title(novel_id), "n": n, "title": _real_title(title), "paragraphs": paras,
            "words": sum(len(p.split()) for p in paras), "summary": summary,
            "prev": nums[i - 1] if i > 0 else None, "next": nums[i + 1] if i + 1 < len(nums) else None}
