"""Blueprint — reference-backed generation (was SYSTEM_STANDARDS_PLAN.md,
built under the now-parked Corpus Wiki page; the author asked for this to
be its own separate menu item instead; later renamed from "Standard" to
"Blueprint" app-wide — same feature/storage, clearer name: a reusable
template a project builds FROM, not a fixed requirement it must conform
TO). A small library of real, reviewed reference data (a novel's
cultivation ranks, its dimensional-zone catalog, ...) that project
generation can inherit from and adapt, instead of inventing from scratch
every time. Storage: corpus/blueprints/{system_type}/{blueprint_id}.json
— one file per blueprint, same "curated reference, not raw corpus
extraction" convention character_dna/ already established.

Author's own framing for this menu item: "a set standard for all systems so
it can either be used in project verbatim or interactively changed based on
the standard or completely new" — i.e. three usage modes downstream of what
this router builds/serves: (1) apply a saved blueprint as-is, (2) run it
through the interactive-interview mechanism to adapt it to a project
(generate.py's existing per-field interview config — see
SYSTEM_STANDARDS_PLAN.md's "Build order" for the not-yet-wired step), or
(3) ignore blueprints entirely and generate fresh. This router only covers
building/browsing the blueprint library itself — extract a wiki page (or
pasted reference text) into a schema-shaped item, review, save. It does not
touch generate.py's own generation branches; that wiring is a separate,
not-yet-done step per the plan doc.
"""
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import CORPUS_PATH

router = APIRouter()

# Same error log generate.py's endpoints already write to — extraction here
# used to fail silently into just a truncated HTTPException message with
# nothing kept for later ("it hung/failed, why?" had no real answer). Reuses
# the SAME file so both show up in one place.
_ERROR_LOG = Path.home() / ".noveltea-engine" / "errors.log"


def _log_error(context: str, detail: str):
    try:
        _ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {context}\n{detail}\n{'-'*70}\n")
    except Exception:
        pass  # logging must never itself break the request


def _corpus_import(name: str):
    """llm_client / extract_v3 live in corpus/ (the corpus script tree),
    not this backend's own package — same cross-boundary pattern already
    established in generate.py (sys.path.insert(0, str(CORPUS_PATH)) right
    before the import, done lazily per-call rather than at module load,
    since CORPUS_PATH's real value depends on config resolving the corpus
    location first)."""
    if str(CORPUS_PATH) not in sys.path:
        sys.path.insert(0, str(CORPUS_PATH))
    import importlib
    return importlib.import_module(name)


BLUEPRINTS_DIR = CORPUS_PATH / "blueprints"

# Per-system_type target schema — the exact per-item shape _build_prompt's
# power_levels/etc. branches already generate FROM scratch (generate.py).
# Extraction targets the SAME shape so a saved blueprint is a drop-in
# reference for that existing generation code, not a new format it has to
# learn. Extend this dict (a new system_type = a new dict entry) as more
# blueprint categories are needed.
_SCHEMAS = {
    "power_levels": {
        "item_key": "levels",
        "item_schema": '{"rank": 1, "name": "Realm/Stage name", "sublevels": 9, '
                       '"description": "What cultivators at this level can do", '
                       '"requirement": "How to reach this level", '
                       '"breakthrough": "The trial/insight/condition needed to advance further"}',
        "extra_fields": '"overview": "2-4 sentence summary of how the system works", '
                        '"rules": ["Core rule 1", "Core rule 2", "..."]',
    },
    # World Bible absorbed Sacred Grounds & Ruins, Factions & Powers, and
    # Races & Species (per author decision — those three no longer exist as
    # standalone systems). Unlike every other entry in this dict, "world" is
    # not a repeated-item schema — it's ONE consolidated object with THREE
    # sub-lists (factions/key_locations/races) plus meta fields, matching
    # project.world_bible's real shape exactly (ProjectView.jsx's WorldTab).
    # Each list item is just {name, description-or-importance, tags: [...]}
    # — the many discrete fields the old standalone systems had (type, tier,
    # danger_level, etc.) collapse into freeform `tags` here too, mirroring
    # the project-side editor's own simplification.
    "world": {
        "item_key": None,   # no single repeated-item list — see extract_blueprint()'s special-case handling
        "item_schema": '{"world_name": "Name of the world/setting", '
                       '"power_tiers": ["Tier1 (weakest)", "...", "TierN (peak)"], '
                       '"rules": ["Core world rule 1", "..."], '
                       '"factions": [{"name": "Faction name", "role": "ally|enemy|neutral", '
                       '"description": "What this faction is, its history, and its culture", '
                       '"tags": ["type e.g. Sect/Kingdom/Empire", "tier", "alignment", "leader name", "territory", "..."]}], '
                       '"key_locations": [{"name": "Location name", '
                       '"importance": "Why it matters — short 1-sentence summary", '
                       '"tags": ["type e.g. Ancient Tomb/Dungeon", "danger level", "status", "notable dangers/rewards", "..."]}], '
                       '"races": [{"name": "Race/species name", '
                       '"description": "What defines this race", '
                       '"tags": ["category e.g. Beast Clan/Demon Race", "power tier", "alignment", "homeland", "..."]}]}',
        "extra_fields": None,   # overview/rules live INSIDE item_schema for this type, not appended alongside it
    },
    # Remaining 9 mirror ProjectView.jsx's ENGINE_FIELDS field lists exactly
    # (same key order, same field names) so an extracted item slots straight
    # into that same editor with no remapping.
    "techniques": {
        "item_key": "techniques",
        "item_schema": '{"name": "Technique name", "type": "Combat|Movement|Dao Law|Forbidden Art|..." , '
                       '"tier": "Tier/grade of the technique", "element": "Elemental affinity, if any", '
                       '"dao_law": "The dao/law principle it embodies, if any", '
                       '"effect": "What it does in practice", "who_uses": "Who is known to use this"}',
        "extra_fields": '"overview": "2-4 sentence summary", "rules": ["Core rule 1", "..."]',
    },
    "weapons": {
        "item_key": "weapons",
        "item_schema": '{"name": "Weapon/artifact name", "type": "Sword|Spear|Armor|Artifact|...", '
                       '"grade": "Rank/grade of the item", "ability": "Its special ability or power", '
                       '"owner": "Who currently owns/wields it", "origin": "Where it came from"}',
        "extra_fields": '"overview": "2-4 sentence summary", "rules": ["Core rule 1", "..."]',
    },
    "alchemy": {
        "item_key": "pills",
        "item_schema": '{"name": "Pill/formula name", "grade": "Rank/grade", "type": "Healing|Enhancement|Breakthrough|...", '
                       '"effect": "What it does", "ingredients": ["ingredient 1", "..."], "rarity": "How rare it is"}',
        "extra_fields": '"overview": "2-4 sentence summary of how the alchemy system works", "rules": ["Core rule 1", "..."]',
    },
    "arrays": {
        "item_key": "formations",
        "item_schema": '{"name": "Array/formation name", "grade": "Rank/grade", "category": "Defensive|Offensive|Sealing|...", '
                       '"effect": "What it does", "materials": ["material 1", "..."]}',
        "extra_fields": '"overview": "2-4 sentence summary of how formations work", "rules": ["Core rule 1", "..."]',
    },
    "artifact_forging": {
        "item_key": "artifacts",
        "item_schema": '{"name": "Artifact/material name", "type": "Weapon|Armor|Tool|Material|...", "grade": "Rank/grade", '
                       '"ability": "What it does", "materials": ["material 1", "..."], "rank_required": "Forger rank needed to craft it"}',
        "extra_fields": '"overview": "2-4 sentence summary of forging ranks/system", "rules": ["Core rule 1", "..."]',
    },
    "treasures_materials": {
        "item_key": "treasures",
        "item_schema": '{"name": "Treasure/material name", "type": "Heaven-and-Earth Treasure|Spirit Stone|Rare Ore|Herb|Essence|Crystal|Other", '
                       '"grade": "Rank/grade of the item", "rarity": "How rare/hard to find it is", '
                       '"description": "What it is, its appearance, and its history", "effect": "What it does or grants when used/consumed/refined", '
                       '"origin": "Where it comes from or how it forms", "known_owners": "Who currently possesses it or has historically fought over it"}',
        "extra_fields": '"overview": "2-4 sentence summary of how treasures/materials work in this world", "rules": ["Core rule 1", "..."]',
    },
    "wars": {
        "item_key": "wars",
        "item_schema": '{"name": "War/conflict name", "type": "World War|Race War|Invasion|Beast Tide|...", '
                       '"scale": "Local|Regional|World|Cosmic", "status": "Ongoing|Resolved|Looming", '
                       '"description": "What this conflict is about", "factions_involved": "Who is fighting", '
                       '"cause": "What started it", "key_battles": "Notable battles", '
                       '"turning_point": "The moment that changed its course", "outcome": "How it ended (if it has)", '
                       '"impact": "Its lasting effect on the world"}',
        "extra_fields": '"overview": "2-4 sentence summary", "rules": ["Core rule 1", "..."]',
    },
    "relationships": {
        "item_key": "relationships",
        "item_schema": '{"name": "Short label, e.g. \'Jiang Chen & Yan Chenyu\'", '
                       '"participants": "Comma-separated names of everyone involved", '
                       '"type": "Romantic|Rival|Mentor|Nemesis|Sworn Sibling|Betrayal|Family|Ally|Master-Servant|...", '
                       '"status": "Current state of the bond, e.g. \'Married\', \'Estranged\', \'Active feud\', \'Deceased\'", '
                       '"description": "How it formed, the key beats that changed it, and where it stands now"}',
        "extra_fields": '"overview": "2-4 sentence summary of the relationship web in this world", "rules": ["Core rule 1", "..."]',
    },
    "encounters": {
        "item_key": "encounters",
        "item_schema": '{"name": "Encounter name", '
                       '"type": "Ambush|Dungeon Delve|Tournament|Negotiation|Heist|Rescue|Siege|Hunt|Trial|...", '
                       '"danger_level": "How dangerous this scenario is", '
                       '"participants": "Who is typically involved (comma-separated names or roles)", '
                       '"stakes": "What\'s being risked or fought for", '
                       '"complications": "What makes it harder than it looks", '
                       '"loot_reward": "What can be gained from it", '
                       '"outcome": "How it typically resolves, or its range of possible outcomes"}',
        "extra_fields": '"overview": "2-4 sentence summary of how encounters work in this world", "rules": ["Core rule 1", "..."]',
    },
    "currency_commerce": {
        "item_key": "entities",
        "item_schema": '{"name": "Entity name", '
                       '"type": "Chamber of Commerce|Auction House|Currency|Gambling Venue|Appraisal Service|Merchant Guild|Trade Route|Beast Core Exchange|Other", '
                       '"tier": "Scale/importance — local, regional, continental, etc.", '
                       '"description": "What it actually is and how it operates", '
                       '"trades_in": "What specifically changes hands here — items, materials, information, favors", '
                       '"who_controls": "The faction, family, or individual who actually runs or profits from it"}',
        "extra_fields": '"overview": "2-4 sentence summary of how money/trade works in this world", "rules": ["Core rule 1", "..."]',
    },
    "pets_mounts": {
        "item_key": "companions",
        "item_schema": '{"name": "Companion name", '
                       '"species": "What kind of creature it is", '
                       '"grade": "Common|Rare|Legendary|Mythic (or this world\'s own tier naming)", '
                       '"bond": "How the bond formed and what it requires to maintain", '
                       '"abilities": "What it can actually do — combat, utility, or travel", '
                       '"temperament": "Personality — loyal, feral, aloof, protective, etc.", '
                       '"owner": "Character name, or \'Unbonded/wild\' if not yet claimed"}',
        "extra_fields": '"overview": "2-4 sentence summary of how companions/mounts work in this world", "rules": ["Core rule 1", "..."]',
    },
    "bosses_monsters": {
        "item_key": "monsters",
        "item_schema": '{"name": "Monster/boss name", '
                       '"type": "Beast|Undead|Demon|Spirit|Aberration|Construct|Corrupted Cultivator|Other", '
                       '"threat_tier": "How dangerous it is, scaled against the power ranks", '
                       '"habitat": "Where it\'s typically found", '
                       '"abilities": "What makes it dangerous — specific combat/special abilities", '
                       '"weaknesses": "The exploitable flaw or condition that makes it beatable", '
                       '"loot_reward": "What defeating it yields — materials, techniques, reputation, plot progress"}',
        "extra_fields": '"overview": "2-4 sentence summary of what threats populate this world", "rules": ["Core rule 1", "..."]',
    },
    # Blueprint-library-only (no project Systems tab card, no AI-generate-from-
    # scratch button — see BLUEPRINT_ONLY_ENGINES in ProjectView.jsx). Still a
    # normal repeated-item schema like every other entry here; the ONLY thing
    # that makes it "Blueprint-only" is the frontend never listing it in
    # SYSTEM_ENGINES, not anything special in this router.
    "character_templates": {
        "item_key": "characters",
        "item_schema": '{"name": "Character name", '
                       '"role": "Male Lead|Female Lead|Sidekick|Mentor|Antagonist|Rival|Ally|Enemy|Other", '
                       '"archetype": "The narrative archetype/fantasy this character embodies", '
                       '"description": "Backstory, personality flavor, and what makes them distinct", '
                       '"powers_items": "Notable techniques, abilities, weapons, or items they possess"}',
        "extra_fields": '"overview": "2-4 sentence summary of this cast of characters", "rules": ["Core rule 1", "..."]',
    },
}


def _clean_reference_html(html: str) -> str:
    """Strip a wiki/reference page down to real content — infobox key/value
    pairs plus heading/paragraph/list text — dropping script/ad/nav noise.
    Returns plain text, section-labelled, suitable to hand an LLM directly."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "noscript"]):
        tag.decompose()

    lines = []

    title_tag = soup.find("title")
    if title_tag:
        lines.append(f"PAGE TITLE: {title_tag.get_text(strip=True)}")

    infobox = soup.find(class_=re.compile(r"portable-infobox"))
    if infobox:
        lines.append("\nINFOBOX:")
        for group in infobox.find_all(class_=re.compile(r"pi-item pi-data")):
            label = group.find(class_=re.compile(r"pi-data-label"))
            value = group.find(class_=re.compile(r"pi-data-value"))
            if label and value:
                lines.append(f"  {label.get_text(strip=True)}: {value.get_text(' ', strip=True)}")

    body = soup.find(class_="mw-parser-output")
    if body:
        lines.append("\nARTICLE BODY:")
        infobox_in_body = body.find(class_=re.compile(r"portable-infobox"))
        if infobox_in_body:
            infobox_in_body.decompose()
        for el in body.find_all(["h2", "h3", "h4", "p", "li"]):
            text = el.get_text(" ", strip=True)
            if not text:
                continue
            if el.name in ("h2", "h3", "h4"):
                lines.append(f"\n### {text}")
            elif el.name == "li":
                lines.append(f"  - {text}")
            else:
                lines.append(text)

    result = "\n".join(lines)
    return result[:40000]  # generous cap — real pages seen so far are well under this


class ExtractRequest(BaseModel):
    system_type: str
    html: Optional[str] = None       # pasted/uploaded HTML — preferred, works for any source
    text: Optional[str] = None       # plain pasted text (no HTML) — used as-is, no cleanup pass
    hint: Optional[str] = None       # optional author note, e.g. "this is one zone among several — extract just this one location"
    bulk: bool = False               # confirmed real gap: a paste naming SEVERAL distinct entries
                                      # (e.g. multiple named techniques/abilities in one block) only ever
                                      # produced ONE item — the prompt below asked for exactly one object
                                      # and _parse_json_response only ever unwrapped a single dict. bulk=True
                                      # switches to a JSON ARRAY prompt/parse so a paste with N distinct
                                      # entries comes back as N items/cards instead of being collapsed into one.
    abort_key: Optional[str] = None  # client-generated id (fresh per extraction) — POST /abort with the
                                      # same id from another request kills the in-flight LLM call for real
                                      # (Popen kill / socket close per engine, see llm_client.abort_call).


class AbortRequest(BaseModel):
    abort_key: str


@router.post("/abort")
def abort_extract(req: AbortRequest):
    """Kills whatever engine call is currently running under this abort_key —
    the console's Abort button target for a Blueprint extraction, since the
    extract call is a plain blocking request/response with no other handle
    the frontend can act on. Always 'succeeds' (ok:True) whether or not
    anything was actually still running — the caller only wants the request
    to stop, and 'nothing to kill because it already finished/hadn't started
    yet' isn't an error from that point of view."""
    llm_client = _corpus_import("llm_client")
    killed = llm_client.abort_call(req.abort_key)
    return {"ok": True, "killed": killed}


@router.post("/extract")
def extract_blueprint(req: ExtractRequest):
    """Stage 1: parse + LLM-structure a reference page/text into either ONE
    schema-shaped item (default) or an ARRAY of items (bulk=True, for a
    paste that names several distinct entries at once) — the frontend
    collects these (one extraction per page/paste, or several from one bulk
    paste) before assembling and saving a complete blueprint via /save.
    Returns the structured item(s) for review/editing, never writes anything."""
    if req.system_type not in _SCHEMAS:
        raise HTTPException(400, f"Unknown system_type '{req.system_type}' — must be one of {list(_SCHEMAS)}.")
    schema = _SCHEMAS[req.system_type]

    if req.html:
        try:
            cleaned = _clean_reference_html(req.html)
        except Exception as e:
            raise HTTPException(500, f"Could not parse the page HTML: {str(e)[:200]}")
        source_note = "pasted HTML"
    elif req.text:
        cleaned = req.text.strip()[:40000]
        source_note = "pasted text"
    else:
        raise HTTPException(400, "Provide either html or text.")

    if len(cleaned.strip()) < 50:
        raise HTTPException(400, "Found almost no extractable content — wrong page, or a format this parser doesn't recognize yet.")

    if req.bulk:
        system = f"""You are transcribing a reference source into structured JSON items for NovelTea Engine's \
blueprint library — a REAL reference an author's generation can inherit from and adapt, not a \
paraphrase or summary. The source below names MULTIPLE distinct entries (e.g. several named techniques, \
abilities, ranks, or locations) — extract EVERY separately-named entry you find as its OWN item, not just \
the first or most prominent one. Preserve every concrete detail (names, numbers, mechanics, conditions) \
faithfully; never invent something the source doesn't state. If a field genuinely isn't covered by the \
source for a given entry, leave it as an honest empty string or omit it — do not guess to fill it in. Do \
not merge distinct entries into one item, and do not split a single entry into several.

Output ONLY a JSON ARRAY, one element per distinct entry found, each matching the {req.system_type} schema exactly:
[{schema['item_schema']}, ...]
{f'Author note: {req.hint}' if req.hint else ''}"""
    else:
        system = f"""You are transcribing a reference source into a structured JSON item for NovelTea Engine's \
blueprint library — a REAL reference an author's generation can inherit from and adapt, not a \
paraphrase or summary. Preserve every concrete detail (names, numbers, mechanics, conditions) faithfully; \
never invent something the source doesn't state. If a field genuinely isn't covered by the source, leave it \
as an honest empty string or omit it — do not guess to fill it in.

Output ONLY this JSON (one item, matching the {req.system_type} schema exactly):
{schema['item_schema']}
{f'Author note: {req.hint}' if req.hint else ''}"""

    user = f"SOURCE ({source_note}):\n\n{cleaned}\n\nTranscribe this source into the JSON schema now."

    llm_client = _corpus_import("llm_client")
    # Resolve BEFORE the call, not after — the caller wants to know which
    # engine/model is about to run (and see it in the console) even if the
    # call itself then hangs or fails; current_model_label() is a pure
    # Settings lookup, it never actually calls anything.
    model_label = llm_client.current_model_label()

    try:
        raw = llm_client.call_llm(system=system, user=user, max_tokens=8000 if req.bulk else 4000,
                                   temperature=0.1, abort_key=req.abort_key)
    except llm_client.CallAborted:
        # Deliberate stop via POST /abort — not a real failure, so it gets its
        # own status/message rather than looking like the model errored out.
        raise HTTPException(499, f"[{model_label}] Extraction stopped — aborted from the console.")
    except Exception as e:
        detail = str(e)
        _log_error(
            f"blueprints.extract system_type={req.system_type} bulk={req.bulk} model={model_label}",
            detail,
        )
        # Full detail goes to the error log above; the HTTP response keeps a
        # longer slice than before (200 -> 500 chars) since this is the ONLY
        # thing the frontend console line has to show the author — the old
        # 200-char cutoff was chopping the actually-useful part off of e.g.
        # long CLI/HTTP error bodies.
        raise HTTPException(502, f"[{model_label}] Extraction LLM call failed: {detail[:500]}")

    extract_v3 = _corpus_import("extract_v3")
    parsed = extract_v3._parse_json_response(raw, label="blueprint_extract")

    if req.bulk:
        if isinstance(parsed, dict):
            # The model sometimes wraps the array in a single key (e.g.
            # {"items": [...]}) despite the instruction — unwrap it rather
            # than failing outright, since the array IS there, just nested.
            list_vals = [v for v in parsed.values() if isinstance(v, list)]
            parsed = list_vals[0] if len(list_vals) == 1 else [parsed]
        if not isinstance(parsed, list) or not parsed:
            _log_error(f"blueprints.extract system_type={req.system_type} bulk=True model={model_label}",
                       f"no usable list in response — raw (first 2000 chars):\n{str(raw)[:2000]}")
            raise HTTPException(502, f"[{model_label}] Bulk extraction did not return a usable list of items — try again, or split the paste into smaller chunks.")
        items = [it for it in parsed if isinstance(it, dict)]
        if not items:
            raise HTTPException(502, f"[{model_label}] Bulk extraction returned a list, but none of its entries were usable JSON objects.")
        return {"ok": True, "system_type": req.system_type, "source": source_note, "items": items, "model": model_label}

    if not isinstance(parsed, dict):
        _log_error(f"blueprints.extract system_type={req.system_type} bulk=False model={model_label}",
                   f"no usable JSON object in response — raw (first 2000 chars):\n{str(raw)[:2000]}")
        raise HTTPException(502, f"[{model_label}] Extraction did not return a usable JSON object — try again, or trim the source text.")
    return {"ok": True, "system_type": req.system_type, "source": source_note, "item": parsed, "model": model_label}


class SaveBlueprintRequest(BaseModel):
    system_type: str
    standard_id: str
    display_name: str
    source: str
    overview: str = ""
    rules: list[str] = []
    items: list[dict] = []   # the accumulated extracted items — 'levels' or 'locations' depending on system_type


@router.post("/save")
def save_blueprint(req: SaveBlueprintRequest):
    """Stage 2: assemble reviewed items into one blueprint file and write it —
    the only place this router touches disk. Overwrites if the blueprint id
    already exists for this system_type (re-saving after editing/adding more
    items is the expected iteration loop, not an error case)."""
    if req.system_type not in _SCHEMAS:
        raise HTTPException(400, f"Unknown system_type '{req.system_type}' — must be one of {list(_SCHEMAS)}.")
    if not req.standard_id.strip():
        raise HTTPException(400, "blueprint_id is required.")
    if not req.items:
        raise HTTPException(400, "At least one item is required — nothing to save.")

    schema = _SCHEMAS[req.system_type]
    slug = re.sub(r"[^a-z0-9_]+", "_", req.standard_id.strip().lower()).strip("_")
    out_dir = BLUEPRINTS_DIR / req.system_type
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.json"

    data = {
        "standard_id": slug,
        "system_type": req.system_type,
        "source": req.source,
        "display_name": req.display_name,
        "overview": req.overview,
        "rules": req.rules,
    }
    if schema["item_key"] is None:
        # World Bible: req.items is a ONE-element array wrapping the single
        # consolidated object (world_name/power_tiers/rules/factions/
        # key_locations/races) — spread its keys directly into the file
        # instead of nesting under a list key, matching project.world_bible's
        # own shape exactly (no schema["item_key"] exists to nest under).
        wb = req.items[0] if req.items else {}
        data["world_name"] = wb.get("world_name", "")
        data["power_tiers"] = wb.get("power_tiers", [])
        data["factions"] = wb.get("factions", [])
        data["key_locations"] = wb.get("key_locations", [])
        data["races"] = wb.get("races", [])
        # wb's own "rules" (if the LLM nested it there) loses to the
        # top-level req.rules already set above, which is what the save
        # form's Overview/Rules panel actually edits — avoid silently
        # overwriting the author's edited rules with the raw extraction.
    else:
        data[schema["item_key"]] = req.items
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "path": str(out_path.relative_to(CORPUS_PATH))}


@router.get("/list")
def list_blueprints(system_type: Optional[str] = None):
    """Browse existing blueprints — for the picker dropdown elsewhere AND this
    page's own 'already have' view."""
    out = []
    if not BLUEPRINTS_DIR.exists():
        return {"standards": out}
    types = [system_type] if system_type else [d.name for d in BLUEPRINTS_DIR.iterdir() if d.is_dir()]
    for st in types:
        type_dir = BLUEPRINTS_DIR / st
        if not type_dir.exists():
            continue
        for f in sorted(type_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            item_key = _SCHEMAS.get(st, {}).get("item_key")
            if item_key is None:
                # World Bible: no single item list — count across all three.
                item_count = (len(d.get("factions", []) or []) + len(d.get("key_locations", []) or [])
                              + len(d.get("races", []) or []))
            else:
                item_count = len(d.get(item_key, []) or [])
            out.append({
                "system_type": st, "standard_id": d.get("standard_id", f.stem),
                "display_name": d.get("display_name", f.stem), "overview": d.get("overview", ""),
                "item_count": item_count, "source": d.get("source", ""),
            })
    return {"standards": out}


@router.get("/system-types")
def system_types():
    """The set of system_type keys this router knows how to extract/save —
    drives the frontend's type selector without hardcoding the list twice."""
    return {"system_types": list(_SCHEMAS.keys())}


@router.get("/active-model")
def active_model():
    """Pure Settings lookup, no LLM call — lets the frontend announce which
    engine/model an Extract click is about to use in the console BEFORE the
    (possibly slow/hanging) call itself even starts, instead of only finding
    out after it succeeds or fails."""
    llm_client = _corpus_import("llm_client")
    return {"model": llm_client.current_model_label()}


@router.get("/{system_type}/{standard_id}")
def get_blueprint(system_type: str, standard_id: str):
    """Full detail for one blueprint — the picker's actual generation-time
    read, and this page's own edit view."""
    path = BLUEPRINTS_DIR / system_type / f"{standard_id}.json"
    if not path.exists():
        raise HTTPException(404, f"No blueprint '{standard_id}' for system_type '{system_type}'.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(500, f"Blueprint file is corrupt: {str(e)[:200]}")


@router.delete("/{system_type}/{standard_id}")
def delete_blueprint(system_type: str, standard_id: str):
    """Remove a blueprint file — the page's own delete action, not called by
    anything else."""
    path = BLUEPRINTS_DIR / system_type / f"{standard_id}.json"
    if not path.exists():
        raise HTTPException(404, f"No blueprint '{standard_id}' for system_type '{system_type}'.")
    path.unlink()
    return {"ok": True}
