"""Corpus Wiki — minimal, scoped to exactly what's been asked for so far:
save one link's pasted content to disk as wiki/{novel_id}/temp/{link_name}.txt,
stripping any HTML markup down to plain text first (the author sometimes
pastes raw page source rather than the visible text). Nothing else lives
here yet — no scraping, no categorization, no standards. Deliberately
small; add to it only when asked."""
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import CORPUS_PATH

router = APIRouter()

WIKI_DIR = CORPUS_PATH / "wiki"


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")
    return slug or "page"


def _looks_like_html(s: str) -> bool:
    """Cheap check so plain pasted text (the common case) skips the parser
    entirely rather than paying for it and risking BeautifulSoup mangling
    text that only coincidentally contains a '<' or '&'."""
    return bool(re.search(r"<(!doctype|html|head|body|div|span|p|a|table|script|style)\b", s, re.I))


def _strip_html(s: str) -> str:
    """Reduce raw HTML down to its visible text, collapsing whitespace the
    way a browser's copy-paste would, so a save always ends up as clean
    prose regardless of whether the author pasted rendered text or view-source."""
    if not _looks_like_html(s):
        return s
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(s, "html.parser")
    for junk in soup(["script", "style", "noscript"]):
        junk.decompose()
    text = soup.get_text("\n")
    # Collapse runs of blank lines and trailing spaces left by tag boundaries,
    # without destroying real paragraph breaks (a single blank line is kept).
    lines = [line.strip() for line in text.splitlines()]
    cleaned, blank_run = [], False
    for line in lines:
        if line:
            cleaned.append(line)
            blank_run = False
        elif not blank_run:
            cleaned.append("")
            blank_run = True
    return "\n".join(cleaned).strip()


# Ignore list, not position-based skipping — confirmed live (two real
# pastes, Federation + Holy Land on a reference novel's Fandom wiki) that
# trying to detect "where the chrome block ends" by line shape/position is
# unreliable: the article's own numbered TOC and the wiki's full sidebar
# (which lists every OTHER page's title) look structurally identical once
# flattened to plain text, so a shape-based skip either stops too early or
# eats real content. An exact-match ignore list sidesteps that entirely —
# each line below is generic FANDOM PLATFORM chrome, the same on every
# Fandom wiki regardless of subject, never a name/term specific to any one
# story — so this never risks dropping real universe content (character
# names, faction names, in-story terms all pass through untouched).
_FANDOM_CHROME_LINES = {
    "home", "saved", "progress", "history", "utilities", "browse wikis",
    "community central", "switch to light theme", "switch to dark theme",
    "featured", "interactive maps", "discuss", "comment", "wiki menu",
    "contents", "explore", "main page", "all pages", "community",
    "recent blog posts", "sign in", "sign in to save", "don't have account? register now",
    "categories", "media kit", "contact", "advertise", "advertisement",
    "support", "help", "accessibility statement", "local sitemap",
    "global sitemap", "manage preferences", "terms of use", "privacy policy",
    "digital services act", "careers", "press", "guidelines", "admins",
    "about", "fandom", "fandom apps", "explore properties", "essentials",
    "most visited pages", "recently changed pages", "what is fandom?",
    "take your favorite fandoms with you and never miss a beat.",
    "view full site", "follow us", "more information",
    "join the conversation",
    "sign in to read what others are saying and share your thoughts.",
    "sign in to share your thoughts and get the conversation going.",
    "start a conversation", "fanatical", "gamespot", "metacritic",
    "tv guide", "honest entertainment", "overview",
}
# These headings always start a TRAILING recommendation widget — everything
# after them is a list of unrelated OTHER pages Fandom's algorithm picked,
# never this article's own content, but the titles themselves vary per page
# view so they can't go in the fixed-phrase list above. Confirmed live: once
# "Just for You" appears, nothing real follows it in either test paste.
_FANDOM_TRAILING_WIDGET_MARKERS = ("just for you", "popular pages", "recommended for you")
# Line-shape rules for chrome that ISN'T a fixed phrase: pure TOC outline
# numbers ("1.", "2.1.") and the boilerplate CC-BY-SA / "is a Fandom ...
# Community." footer lines, which repeat verbatim in structure but not
# necessarily exact text across different wikis.
_OUTLINE_NUM_RE = re.compile(r"^\d+(\.\d+)*\.?$")
_FANDOM_FOOTER_LINE_RE = re.compile(
    r"^(community content is available under|.+ is a fandom .+ community\.?$|comments? \(\d+\)$)", re.I)
# A line that's ONLY a bare URL or a leftover href fragment — a copy-paste
# from some browsers/extensions can drop the raw link target as its own
# line alongside the visible link text. Only matches a line that's nothing
# BUT a URL/href, never touches a real sentence that happens to mention one.
_BARE_URL_RE = re.compile(r"^(href=[\"']?)?(https?://|www\.)\S+[\"']?$", re.I)


def _cut_to_article_start(s: str, link_name: str) -> str:
    """Use the page's OWN title (the clicked link's display text, already
    known server-side) as a structural anchor rather than guessing at
    layout. Confirmed live on two real pastes: the article's title appears
    as a standalone line exactly 3 times in a full-page copy — once as the
    page's own <title>-derived header, once as its own entry inside the
    sidebar's affiliation list, and a third time immediately before the
    infobox/article body actually starts. Cutting to that third occurrence
    reliably drops the entire header+sidebar block in one step, which the
    chrome-ignore-list alone can't do (sidebar entries are story-specific
    names, not generic platform text, so they're deliberately not on that
    list). If the title doesn't appear at least 3 times (a shorter/different
    page layout), this is a no-op — better to keep extra chrome than risk
    cutting into real content on a shape this hasn't been confirmed against."""
    name = link_name.strip()
    if not name:
        return s
    lines = s.splitlines()
    matches = [i for i, ln in enumerate(lines) if ln.strip().lower() == name.lower()]
    if len(matches) < 3:
        return s
    return "\n".join(lines[matches[2]:])


def _strip_fandom_chrome(s: str) -> str:
    """Drop lines that are known generic Fandom platform chrome, wherever
    they occur in the paste — header nav, TOC scaffolding, footer — leaving
    every other line (including short lines that happen to be real story
    content, like a sidebar entry's own title) untouched. A paste with none
    of this chrome (already just article text, or a non-Fandom wiki) passes
    through completely unchanged."""
    lines = s.splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        lowered = stripped.lower()
        if lowered in _FANDOM_TRAILING_WIDGET_MARKERS:
            break  # everything from here to the end is a recommendation widget, not article content
        if lowered in _FANDOM_CHROME_LINES:
            continue
        if _OUTLINE_NUM_RE.match(stripped):
            continue
        if _FANDOM_FOOTER_LINE_RE.match(stripped):
            continue
        if _BARE_URL_RE.match(stripped):
            continue
        kept.append(line)

    # Collapse blank-line runs left behind by the removals, same rule
    # _strip_html already uses (a single blank line is kept as a paragraph
    # break, longer runs collapse to one).
    collapsed, blank_run = [], False
    for line in kept:
        if line.strip():
            collapsed.append(line)
            blank_run = False
        elif not blank_run:
            collapsed.append("")
            blank_run = True

    result = "\n".join(collapsed).strip()
    return result if result else s  # never return empty — fall back to the untrimmed input


# Same field keys the project's own Systems tab uses (ProjectView.jsx
# SystemsTab) plus 'characters' — an untagged/unrecognized value falls back
# to 'temp', matching the pre-tag behavior rather than erroring, since the
# tag dropdown is optional.
VALID_TAGS = {
    "characters", "power_levels", "techniques", "weapons", "alchemy",
    "arrays", "artifact_forging", "sacred_grounds", "races", "factions", "wars",
}


class SaveLinkContentRequest(BaseModel):
    novel_id: str
    link_name: str
    content: str
    tag: str = ""
    source_url: str = ""


# Written at the top of every saved .txt as a small, greppable header — not
# just metadata for humans, but what /wiki/saved-urls reads back to answer
# "has THIS url already been saved" without opening every file's content in
# full. Kept as plain "Key: value" lines rather than a JSON blob so the file
# stays readable as plain text, matching every other save in wiki/.
def _format_header(source_url: str, tag: str) -> str:
    lines = []
    if source_url.strip():
        lines.append(f"Source: {source_url.strip()}")
    lines.append(f"Tag: {tag}")
    return "\n".join(lines) + "\n\n"


_SOURCE_HEADER_RE = re.compile(r"^Source:\s*(\S+)\s*$", re.M)


@router.post("/save-link-content")
def save_link_content(req: SaveLinkContentRequest):
    """Writes pasted content to wiki/{novel_id}/{tag}/{link_name}.txt (or
    .../temp/... when untagged) — link_name is the clicked link's display
    text, slugified so it's a safe filename. Overwrites if the same link is
    saved again under the SAME tag (re-pasting after editing is the
    expected flow, not an error case); saving again under a DIFFERENT tag
    creates a new file rather than moving the old one, so re-tagging never
    silently loses a prior save. The source URL and tag are written as a
    small header at the top of the file, so a saved page always carries
    where it came from and how it was classified — not just the cleaned text."""
    if not req.novel_id.strip():
        raise HTTPException(400, "novel_id is required.")
    if not req.link_name.strip():
        raise HTTPException(400, "link_name is required.")
    if not req.content.strip():
        raise HTTPException(400, "content is empty — nothing to save.")

    cleaned = _strip_html(req.content)
    cleaned = _cut_to_article_start(cleaned, req.link_name)
    cleaned = _strip_fandom_chrome(cleaned)
    if not cleaned.strip():
        raise HTTPException(400, "Content was all markup, no visible text left after stripping HTML.")

    tag_slug = req.tag.strip().lower()
    folder = tag_slug if tag_slug in VALID_TAGS else "temp"

    novel_slug = _slugify(req.novel_id)
    file_slug = _slugify(req.link_name)
    out_dir = WIKI_DIR / novel_slug / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{file_slug}.txt"
    out_path.write_text(_format_header(req.source_url, folder) + cleaned, encoding="utf-8")

    return {"ok": True, "path": str(out_path.relative_to(CORPUS_PATH)), "tag": folder}


@router.get("/saved-urls")
def saved_urls(novel_id: str):
    """Every source URL already saved for a novel, across all tag folders —
    read from each file's own 'Source:' header line rather than trusting
    filenames (a link's display text can change on the wiki side; the URL
    is the stable identity). The frontend uses this on page load so a link
    already saved in a PRIOR session still shows red immediately, instead
    of only turning red after being clicked again this session."""
    novel_slug = _slugify(novel_id)
    novel_dir = WIKI_DIR / novel_slug
    urls = set()
    if novel_dir.exists():
        for txt_path in novel_dir.glob("*/*.txt"):
            try:
                head = txt_path.read_text(encoding="utf-8", errors="replace")[:2000]
            except OSError:
                continue
            m = _SOURCE_HEADER_RE.search(head)
            if m:
                urls.add(m.group(1))
    return {"urls": sorted(urls)}
