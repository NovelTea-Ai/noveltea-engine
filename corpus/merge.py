import os
#!/usr/bin/env python3
"""
Wiki Brain Merge Script
========================

Purpose:
  Takes per-chapter extraction "delta" JSON files (one per chapter, produced
  by the extraction step) and merges them into a persistent, growing wiki
  brain: one JSON file per entity (character/location/faction/concept), plus
  aggregated timeline, glossary, and humor-pattern files.

What it does:
  1. Entity resolution  - decides whether an extracted name is a NEW entity
     or refers to an EXISTING one (handles aliasing, e.g. "Jiang Hai" ->
     "Jiang Zhen Hai"), while protecting against false merges of near-
     identical-but-distinct names (e.g. "Jiang Chen" vs "Jiang Cheng").
  2. Alias accumulation - keeps a running set of all names/titles an entity
     has been called.
  3. Fact accumulation + versioning - appends new facts to an entity's fact
     list; if a new fact for the same (subject, predicate) pair conflicts
     with an existing "active" fact, the old one is marked "superseded"
     (unless the new entry explicitly marks itself superseded/historical).
  4. Conflict flagging - contradictions that aren't simple supersessions
     (e.g. "alive" vs "dead" for the same subject) get written to a
     conflicts log for manual review rather than silently resolved.
  5. Timeline / glossary / humor aggregation - appends chapter-tagged
     records to running global lists.
  6. Running-gag linking - resolves `callback_to` text references into
     `callback_to_id` links pointing at earlier humor_instance records,
     where a confident match is found; otherwise leaves them as
     unresolved text notes for manual linking.

Usage:
  python merge.py deltas/ch001.json deltas/ch002.json deltas/ch003.json
  (or just: python merge.py deltas/*.json  -- processed in filename order)

Output:
  entities/<slug>.json     - one file per entity, accumulated across chapters
  timeline/events.json     - global chapter-ordered timeline
  glossary/terms.json      - global glossary
  humor/instances.json     - global humor instance log
  conflicts.json           - flagged contradictions needing review
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


def _coerce_chapter_int(v):
    """Extraction sometimes returns chapter numbers as strings like 'Chapter 52'
    or '59' instead of a bare int. Coerce to int where possible; return None for
    genuinely non-numeric references (e.g. 'earlier') rather than guessing."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.search(r'\d+', v)
        if m:
            return int(m.group())
        return None
    return None

BRAIN_DIR = Path(__file__).parent
NOVELS_DIR = BRAIN_DIR / "novels"
REGISTRY_FILE = NOVELS_DIR / "registry.json"


def novel_paths(novel_id):
    """Return a dict of all per-novel file/dir paths, scoped under
    novels/<novel_id>/.
    """
    root = NOVELS_DIR / novel_id
    return {
        "root": root,
        "entities": root / "entities",
        "timeline": root / "timeline" / "events.json",
        "glossary": root / "glossary" / "terms.json",
        "humor": root / "humor" / "instances.json",
        "conflicts": root / "conflicts.json",
        "arcs": root / "timeline" / "arcs.json",
        "novel_meta": root / "novel_metadata.json",
        "schemes": root / "schemes" / "instances.json",
        "knowledge": root / "knowledge" / "state.json",
        "prose": root / "prose" / "samples.json",
        "onomatopoeia": root / "onomatopoeia" / "instances.json",
        "antagonist_templates": root / "templates" / "antagonists.json",
        "power_curve": root / "power_curve" / "notes.json",
        "reader_psychology": root / "reader_psychology" / "chapters.json",
        "author_intent": root / "author_intent" / "chapters.json",
        "reveals": root / "reveals" / "log.json",
        # v2.1 ENHANCED AGGREGATIONS
        "style_dna_evolution": root / "prose" / "style_dna_evolution.json",
        "prose_by_type": root / "prose" / "samples_by_type.json",
        "scene_patterns": root / "structure" / "scene_patterns.json",
        "narrative_tracking": root / "narrative" / "pov_tracking.json",
        "character_voices": root / "entities",  # voice_dna per character
    }


def ensure_novel_dirs(paths):
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["entities"].mkdir(parents=True, exist_ok=True)
    for key in ("timeline", "glossary", "humor", "arcs", "schemes",
                "knowledge", "prose", "onomatopoeia", "antagonist_templates", "power_curve",
                "reader_psychology", "author_intent", "reveals",
                "style_dna_evolution", "prose_by_type", "scene_patterns", "narrative_tracking"):
        if key in paths:
            paths[key].parent.mkdir(parents=True, exist_ok=True)


def update_registry(novel_id, title, chapters_extracted, highest_chapter=None):
    registry = load_json(REGISTRY_FILE, {"novels": []})
    entry = next((n for n in registry["novels"] if n["id"] == novel_id), None)
    if entry is None:
        entry = {
            "id": novel_id,
            "title": title or novel_id,
            "alt_titles": [],
            "directory": f"novels/{novel_id}",
            "chapters_extracted": 0,
            "status": "active",
        }
        registry["novels"].append(entry)
    if title:
        entry["title"] = title
    entry["chapters_extracted"] = chapters_extracted          # how many chapters are extracted (a count, not a chapter number)
    if highest_chapter is not None:
        entry["highest_chapter_extracted"] = max(entry.get("highest_chapter_extracted") or 0, highest_chapter)
    save_json(REGISTRY_FILE, registry)

# Predicates where a new value for the same (subject, predicate) should
# supersede the old one (only one "active" value makes sense at a time).
SINGLE_VALUED_PREDICATES = {
    "has_power_rank",
    "has_reputation",
}

# Predicate pairs that are mutually exclusive for a given (subject, object)
# pair -- e.g. you can't be both an active ally_of and enemy_of the same
# faction at once. When a new fact of one predicate appears, any existing
# active fact of the opposing predicate (for the same subject+object) is
# superseded.
OPPOSING_PREDICATE_PAIRS = {
    "ally_of": "enemy_of",
    "enemy_of": "ally_of",
    "romantic_with": "enemy_of",
}

# Symmetric relational predicates: when subject->object is recorded, the
# same predicate also holds object->subject. These get mirrored onto the
# object entity's own fact list so relationship status stays in sync
# regardless of which entity is queried.
SYMMETRIC_PREDICATES = {
    "ally_of", "enemy_of", "romantic_with",
}

# Predicates that, if they appear with contradictory literal values for the
# same subject, should be flagged as a conflict rather than auto-superseded
# (these represent state that shouldn't normally flip silently).
CONFLICT_SENSITIVE_PREDICATES = {
    "occurred_to_character",  # e.g. "killed" vs later "alive and well"
}

# For occurred_to_character facts specifically, only flag a conflict if both
# the existing and new literal objects contain genuinely OPPOSING state
# words (e.g. "killed"/"dead" vs "alive"). Distinct sequential events about
# the same character (e.g. "overheard X" then later "learned the truth Y")
# are normal narrative progression, not contradictions, and should NOT be
# flagged.
_CONTRADICTION_WORD_PAIRS = [
    ({"killed", "dead", "deceased", "died"}, {"alive", "survives", "recovers", "unharmed"}),
]


def _is_genuine_contradiction(existing_obj, new_obj):
    existing_l = existing_obj.lower()
    new_l = new_obj.lower()
    for group_a, group_b in _CONTRADICTION_WORD_PAIRS:
        a_in_existing = any(w in existing_l for w in group_a)
        b_in_existing = any(w in existing_l for w in group_b)
        a_in_new = any(w in new_l for w in group_a)
        b_in_new = any(w in new_l for w in group_b)
        if (a_in_existing and b_in_new) or (b_in_existing and a_in_new):
            return True
    return False


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def load_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------

def load_all_entities(entities_dir):
    """Load every existing entity file into memory, keyed by slug."""
    entities = {}
    if entities_dir.exists():
        for f in entities_dir.glob("*.json"):
            data = load_json(f, None)
            if data:
                entities[f.stem] = data
    return entities


def build_alias_index(entities):
    """Map every known name/alias (lowercased) -> entity slug.

    Only EXACT (case-insensitive) matches are used for auto-resolution.
    This deliberately avoids fuzzy matching, because near-identical names
    in these novels (e.g. 'Jiang Chen' vs 'Jiang Cheng') are often
    DIFFERENT characters. Anything that doesn't exactly match an existing
    alias is treated as a new entity, or flagged if it's suspiciously
    close to an existing one.
    """
    index = {}
    for slug, ent in entities.items():
        names = [ent.get("canonical_name", "")] + ent.get("aliases", [])
        for n in names:
            if n:
                index[n.lower().strip()] = slug
    return index


def find_near_miss_warnings(name, alias_index, entities):
    """Detect near-identical-but-not-exact name matches against existing
    entities, to surface in conflicts.json for manual review (e.g.
    'Jiang Cheng' appearing when 'Jiang Chen' already exists).
    Uses a simple edit-distance-1 check on short names only.
    """
    warnings = []
    target = name.lower().strip()
    for known_name, slug in alias_index.items():
        if known_name == target:
            continue
        if abs(len(known_name) - len(target)) > 1:
            continue
        if _edit_distance_le_1(known_name, target):
            ent = entities.get(slug, {})
            warnings.append({
                "new_name": name,
                "similar_to_entity": slug,
                "similar_to_name": known_name,
                "similar_entity_canonical": ent.get("canonical_name"),
            })
    return warnings


def _edit_distance_le_1(a, b):
    if a == b:
        return False  # exact match handled elsewhere
    if abs(len(a) - len(b)) > 1:
        return False
    # simple DP edit distance, early-exit if > 1
    if len(a) < len(b):
        a, b = b, a
    if len(a) == len(b):
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs == 1
    # len(a) == len(b)+1 -> check single deletion
    for i in range(len(a)):
        if a[:i] + a[i+1:] == b:
            return True
    return False


def resolve_entity(name, entity_type, alias_index, entities, conflicts):
    """Return the slug an extracted entity name should map to.

    Exact alias match -> existing slug.
    Otherwise -> new slug from this name, after recording any near-miss
    warnings for manual review.
    """
    key = name.lower().strip()
    if key in alias_index:
        return alias_index[key]

    warnings = find_near_miss_warnings(name, alias_index, entities)
    if warnings:
        conflicts.setdefault("near_miss_name_warnings", []).extend(warnings)

    return slugify(name)


# ---------------------------------------------------------------------------
# Entity record construction / update
# ---------------------------------------------------------------------------

def new_entity_record(name, entity_type, chapter_num):
    return {
        "canonical_name": name,
        "type": entity_type,
        "aliases": [],
        "facts": [],
        "appearances": [],
        "created_chapter": chapter_num,
    }


def merge_entity_meta(record, char_entry, chapter_num):
    """Merge metadata (role, comedic_role, notes, aliases) from a
    new_characters / new_locations / new_factions entry into the record.
    """
    for key in ("role", "comedic_role", "notes"):
        if key in char_entry and char_entry[key]:
            # last-write-wins for simple scalar metadata, but keep history
            history = record.setdefault("_meta_history", {})
            old = record.get(key)
            if old is not None and old != char_entry[key]:
                history.setdefault(key, []).append({
                    "value": old,
                    "superseded_at_chapter": chapter_num,
                })
            record[key] = char_entry[key]

    for alias in char_entry.get("aliases", []):
        if alias and alias not in record["aliases"] and alias != record["canonical_name"]:
            record["aliases"].append(alias)

    if chapter_num not in record["appearances"]:
        record["appearances"].append(chapter_num)

    return record


def add_fact(record, fact, conflicts, entity_slug):
    """Add a fact to an entity's fact list, handling supersession and
    conflict detection.
    """
    predicate = fact.get("predicate")
    new_status = fact.get("status", "active")

    if predicate in SINGLE_VALUED_PREDICATES and new_status == "active":
        # Supersede any prior active fact with the same predicate.
        for existing in record["facts"]:
            if existing.get("predicate") == predicate and existing.get("status", "active") == "active":
                existing["status"] = "superseded"
                existing["superseded_at_chapter"] = fact.get("source_chapter")

    if predicate in OPPOSING_PREDICATE_PAIRS and new_status == "active":
        opposing = OPPOSING_PREDICATE_PAIRS[predicate]
        for existing in record["facts"]:
            if (existing.get("predicate") == opposing
                    and existing.get("status", "active") == "active"
                    and existing.get("object") == fact.get("object")):
                existing["status"] = "superseded"
                existing["superseded_at_chapter"] = fact.get("source_chapter")
                existing.setdefault("superseded_reason", f"superseded by opposing predicate '{predicate}'")
        # Also collapse any earlier active facts of the SAME predicate+object
        # (e.g. repeated ally_of confirmations) -- keep only the latest as
        # active, mark earlier ones as historical confirmations.
        for existing in record["facts"]:
            if (existing.get("predicate") == predicate
                    and existing.get("status", "active") == "active"
                    and existing.get("object") == fact.get("object")
                    and existing.get("source_chapter") != fact.get("source_chapter")):
                existing["status"] = "superseded"
                existing["superseded_at_chapter"] = fact.get("source_chapter")
                existing.setdefault("superseded_reason", "superseded by later confirmation of same relation")

    if predicate in CONFLICT_SENSITIVE_PREDICATES:
        for existing in record["facts"]:
            if (existing.get("predicate") == predicate
                    and existing.get("status", "active") == "active"
                    and existing.get("object") != fact.get("object")
                    and _is_genuine_contradiction(existing.get("object", ""), fact.get("object", ""))):
                conflicts.setdefault("fact_conflicts", []).append({
                    "entity": entity_slug,
                    "predicate": predicate,
                    "existing": existing,
                    "new": fact,
                })

    record["facts"].append(fact)


# ---------------------------------------------------------------------------
# Humor / running-gag linking
# ---------------------------------------------------------------------------

def link_humor_instances(new_instances, humor_log, conflicts, chapter_num=None):
    """Append new humor instances to the global log. If an instance has a
    callback_to text reference, try to resolve it to the id of an earlier
    instance via simple keyword overlap; otherwise leave as an unresolved
    note for manual linking.

    source_chapter is stamped from the delta's own chapter_number (trusted)
    rather than the LLM's per-instance value, which is sometimes a string
    like 'Chapter 52'. Deduped by (source_chapter, setup, payoff) so a
    re-merged/re-repaired chapter can't double its humor instances.
    """
    seen = {(h.get("source_chapter"), (h.get("setup") or "")[:120], (h.get("payoff") or "")[:120])
            for h in humor_log}
    for inst in new_instances:
        inst = dict(inst)
        if chapter_num is not None:
            inst["source_chapter"] = chapter_num
        else:
            inst["source_chapter"] = _coerce_chapter_int(inst.get("source_chapter"))

        key = (inst.get("source_chapter"), (inst.get("setup") or "")[:120], (inst.get("payoff") or "")[:120])
        if key in seen:
            continue
        seen.add(key)

        inst_id = f"humor_{len(humor_log) + 1:04d}"
        inst["id"] = inst_id

        callback_text = inst.get("callback_to")
        # The extractor sometimes returns a bare int (a chapter number) or a
        # list/dict instead of a text reference — coerce to a string so the
        # keyword matcher never crashes on .lower().
        if callback_text is not None and not isinstance(callback_text, str):
            if isinstance(callback_text, (list, tuple)):
                callback_text = " ".join(str(x) for x in callback_text)
            else:
                callback_text = str(callback_text)
        if callback_text:
            resolved = _resolve_callback(callback_text, humor_log, inst.get("participants"))
            if resolved:
                inst["callback_to_id"] = resolved
            else:
                conflicts.setdefault("unresolved_callbacks", []).append({
                    "instance_id": inst_id,
                    "callback_to_text": callback_text,
                })

        humor_log.append(inst)


def _resolve_callback(callback_text, humor_log, new_participants=None):
    """Resolve a callback_to text reference to an earlier humor_instance id.

    Primary signal: participant overlap (the callback almost always involves
    at least one of the same characters as the earlier setup). Secondary
    signal: keyword overlap between the callback description and the
    candidate's setup/payoff text. A match is only returned if it clears a
    minimum combined-confidence threshold; otherwise the reference is left
    unresolved for manual review rather than guessing.
    """
    callback_words = set(re.findall(r"[a-z]{4,}", str(callback_text).lower()))
    # participants entries can be non-strings; coerce defensively
    new_participants = set(str(p) for p in (new_participants or []))

    best_id, best_score = None, 0
    for inst in humor_log:
        text = (str(inst.get("setup", "")) + " " + str(inst.get("payoff", ""))).lower()
        words = set(re.findall(r"[a-z]{4,}", text))
        keyword_score = len(callback_words & words)

        participant_score = 0
        if new_participants:
            existing_participants = set(str(p) for p in (inst.get("participants") or []))
            participant_score = len(new_participants & existing_participants) * 3

        score = keyword_score + participant_score
        if score > best_score:
            best_score, best_id = score, inst.get("id")

    # Require both: at least one shared participant AND some keyword overlap,
    # OR a very strong keyword-only match. This avoids weak coincidental
    # matches like "guards"/"shock" appearing in unrelated instances.
    return best_id if best_score >= 5 else None


# ---------------------------------------------------------------------------
# Resolution hints (from extractor's "notes" / "merge_notes" fields)
# ---------------------------------------------------------------------------

# Pattern: notes saying "Resolves <Name> (ch.N) -> full name <Name2>"
RESOLVE_PATTERN = re.compile(
    r"resolves\s+(.+?)\s*\(ch\.?\s*\d+\)\s*[\u2192\->]+\s*full name\s+(.+?)\.?$",
    re.IGNORECASE,
)


def apply_entity_aliasing(old_name, new_canonical_slug_or_name, entities, alias_index, conflicts):
    """Merge an existing entity (referenced by old_name) into the entity
    identified by new_canonical_slug_or_name, if both exist as separate
    entity records. The new_canonical entity keeps its facts/appearances
    plus gains old_name's facts/appearances/aliases; old_name's record is
    removed and its slug is redirected in alias_index.
    """
    old_key = old_name.lower().strip()
    new_key = new_canonical_slug_or_name.lower().strip()

    old_slug = alias_index.get(old_key)
    new_slug = alias_index.get(new_key)

    if not old_slug or not new_slug or old_slug == new_slug:
        return  # nothing to merge, or already merged

    if old_slug not in entities or new_slug not in entities:
        return

    old_rec = entities[old_slug]
    new_rec = entities[new_slug]

    if old_rec["canonical_name"] not in new_rec["aliases"] and old_rec["canonical_name"] != new_rec["canonical_name"]:
        new_rec["aliases"].append(old_rec["canonical_name"])
    for a in old_rec.get("aliases", []):
        if a not in new_rec["aliases"] and a != new_rec["canonical_name"]:
            new_rec["aliases"].append(a)

    for fact in old_rec.get("facts", []):
        fact["subject"] = new_rec["canonical_name"]
        new_rec["facts"].append(fact)

    for ch in old_rec.get("appearances", []):
        if ch not in new_rec["appearances"]:
            new_rec["appearances"].append(ch)
    new_rec["appearances"].sort()

    new_rec["created_chapter"] = min(new_rec.get("created_chapter", 9999), old_rec.get("created_chapter", 9999))

    for n in [old_rec["canonical_name"]] + old_rec.get("aliases", []):
        alias_index[n.lower().strip()] = new_slug
    alias_index[old_key] = new_slug

    del entities[old_slug]

    conflicts.setdefault("auto_merged_entities", []).append({
        "merged_from": old_rec["canonical_name"],
        "merged_into": new_rec["canonical_name"],
    })


def process_resolution_hints(delta, entities, alias_index, conflicts):
    """Scan new_characters[].notes and merge_notes[] for explicit
    resolution hints like:
        "Resolves Jiang Hai (ch.1) -> full name Jiang Zhen Hai."
    and apply entity merges accordingly.
    """
    candidates = []
    for entry in delta.get("new_characters", []):
        note = entry.get("notes", "")
        if note:
            candidates.append(note)
    for note in delta.get("merge_notes", {}).values():
        if isinstance(note, str):
            candidates.append(note)

    for note in candidates:
        m = RESOLVE_PATTERN.search(note)
        if m:
            old_name, new_name = m.group(1).strip(), m.group(2).strip()
            apply_entity_aliasing(old_name, new_name, entities, alias_index, conflicts)


def _assign_chapter_to_arc(arcs, arc_label, chapter_num, is_start=False):
    """Add chapter_num to the named arc's chapter range, creating the arc
    if it doesn't exist yet.
    """
    arc = next((a for a in arcs if a["label"] == arc_label), None)
    if arc is None:
        arc = {"label": arc_label, "chapters": []}
        arcs.append(arc)
    if chapter_num not in arc["chapters"]:
        arc["chapters"].append(chapter_num)
    arc["chapters"].sort()


def merge_scheme_instances(new_schemes, scheme_log, conflicts):
    """Merge scheme_instances into the running scheme log. Schemes are
    matched by (schemer, target, goal) -- a re-emitted scheme with the same
    key updates the existing record (execution_chapter, payoff_chapter,
    status, stakes) rather than creating a duplicate.

    Chapter-reference fields are coerced from the LLM's occasional string
    form ('Chapter 52') to int -- these can legitimately reference an
    earlier/later chapter than the current delta, so they're normalized
    rather than force-stamped.
    """
    for new in new_schemes:
        new = dict(new)
        for field in ("setup_chapter", "execution_chapter", "payoff_chapter"):
            if field in new:
                new[field] = _coerce_chapter_int(new[field])
        key = (new.get("schemer"), new.get("target"), new.get("goal"))
        existing = next((s for s in scheme_log
                          if (s.get("schemer"), s.get("target"), s.get("goal")) == key), None)
        if existing:
            # update mutable fields, keep original setup_chapter
            for field in ("execution_chapter", "payoff_chapter", "status",
                           "stakes", "victim_aware", "mechanism", "linked_humor_id"):
                if new.get(field) is not None:
                    existing[field] = new[field]
            existing.setdefault("history", []).append({
                "updated_at_chapter": new.get("payoff_chapter") or new.get("execution_chapter"),
                "status": new.get("status"),
            })
        else:
            new = dict(new)
            new["id"] = f"scheme_{len(scheme_log) + 1:04d}"
            new["history"] = []
            scheme_log.append(new)


def _coerce_fact_dict(item, key="fact"):
    """Some extractions (esp. CLI-mode) emit list items as bare strings instead of
    objects. Coerce a string into a minimal dict so the merge logic still works."""
    if isinstance(item, str):
        return {key: item}
    if isinstance(item, dict):
        return item
    return None


def _normalize_knowledge_state(new_states):
    """Accept the several shapes extractions produce and yield a flat list of
    {fact, who_knows} dicts:
      - list of dicts  (canonical)            -> passed through
      - list of strings                       -> {fact: str}
      - dict of {who_knows: [facts...]}       -> flattened with who_knows tag
    """
    out = []
    if isinstance(new_states, dict):
        for who, facts in new_states.items():
            if isinstance(facts, list):
                for f in facts:
                    if isinstance(f, str) and f.strip():
                        out.append({"fact": f.strip(), "who_knows": who})
                    elif isinstance(f, dict):
                        d = dict(f)
                        d.setdefault("who_knows", who)
                        out.append(d)
            elif isinstance(facts, str) and facts.strip():
                out.append({"fact": facts.strip(), "who_knows": who})
    elif isinstance(new_states, list):
        for item in new_states:
            d = _coerce_fact_dict(item, "fact")
            if d is not None:
                out.append(d)
    return out


def _next_knowledge_id(knowledge_log) -> str:
    """Max-based, not length-based: `len(knowledge_log)+1` collides when two
    id-less legacy entries get backfilled in the same merge_chapter call (the
    array doesn't grow on a backfill, so both would compute the same length)."""
    nums = []
    for k in knowledge_log:
        kid = isinstance(k, dict) and k.get("id")
        if isinstance(kid, str) and kid.startswith("knowledge_") and kid.split("_")[-1].isdigit():
            nums.append(int(kid.split("_")[-1]))
    return f"knowledge_{(max(nums) + 1) if nums else 1:04d}"


def merge_knowledge_state(new_states, knowledge_log, conflicts):
    """Merge knowledge_state entries. Matched by `fact` text (exact match);
    a re-emitted entry with a filled-in resolved_chapter updates the
    existing record. Tolerant of dict / list / string input shapes.

    Backfills `id` onto an existing record that predates id assignment being
    added here — without this, a legacy id-less record matched by fact text
    stays id-less forever, since the only place `id` was ever set was the
    "brand new record" branch below.
    """
    for new in _normalize_knowledge_state(new_states):
        existing = next((k for k in knowledge_log if isinstance(k, dict) and k.get("fact") == new.get("fact")), None)
        if existing:
            if not existing.get("id"):
                existing["id"] = _next_knowledge_id(knowledge_log)
            if new.get("resolved_chapter") is not None:
                existing["resolved_chapter"] = new["resolved_chapter"]
                existing["resolution"] = new.get("resolution", existing.get("resolution"))
        else:
            new = dict(new)
            new["id"] = _next_knowledge_id(knowledge_log)
            knowledge_log.append(new)


def merge_prose_samples(new_samples, prose_log, chapter_num=None):
    """Append prose samples, deduped by (chapter, excerpt) so re-merging a
    chapter's delta (verify pass, catch-up run) can't double the samples.

    source_chapter is always stamped from the delta's own chapter_number
    (the trusted top-level field) rather than trusted from the LLM's
    per-sample value, which is sometimes a string like 'Chapter 52'."""
    seen = {(s.get("source_chapter"), (s.get("excerpt") or "")[:120]) for s in prose_log}
    for sample in new_samples:
        sample = dict(sample)
        # The schema asks for "excerpt", but the LLM drifts to "text" or "quote"
        # on some chapters. Those used to merge with an empty excerpt — present
        # in the store but carrying no prose (37 of 65 lost across ch51-61).
        # Normalise the synonyms so the sample text always survives.
        if not (sample.get("excerpt") or "").strip():
            for alt in ("text", "quote", "sample", "line"):
                if (sample.get(alt) or "").strip():
                    sample["excerpt"] = sample.pop(alt)
                    break
        # Likewise the annotation key: "style_notes" is the schema name, but
        # "context"/"note"/"function" show up in practice.
        if not (sample.get("style_notes") or "").strip():
            for alt in ("context", "note", "notes"):
                if (sample.get(alt) or "").strip():
                    sample["style_notes"] = sample[alt]
                    break
        if not (sample.get("excerpt") or "").strip():
            continue  # nothing usable in this sample — don't store an empty row

        if chapter_num is not None:
            sample["source_chapter"] = chapter_num
        else:
            sample["source_chapter"] = _coerce_chapter_int(sample.get("source_chapter"))
        key = (sample.get("source_chapter"), (sample.get("excerpt") or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        sample["id"] = f"prose_{len(prose_log) + 1:04d}"
        prose_log.append(sample)


def merge_onomatopoeia_instances(new_instances, onomatopoeia_log, chapter_num=None):
    """Append onomatopoeia instances, deduped by (chapter, word, excerpt) so
    re-merging a chapter's delta can't double them up. Mirrors
    merge_prose_samples exactly — source_chapter is stamped from the delta's
    own trusted chapter_number rather than the LLM's own per-instance value."""
    seen = {(o.get("source_chapter"), (o.get("word") or "").lower(), (o.get("excerpt") or "")[:120])
            for o in onomatopoeia_log}
    for inst in new_instances:
        if not isinstance(inst, dict) or not inst.get("word"):
            continue
        inst = dict(inst)
        if chapter_num is not None:
            inst["source_chapter"] = chapter_num
        else:
            inst["source_chapter"] = _coerce_chapter_int(inst.get("source_chapter"))
        key = (inst.get("source_chapter"), (inst.get("word") or "").lower(), (inst.get("excerpt") or "")[:120])
        if key in seen:
            continue
        seen.add(key)
        inst["id"] = f"onomatopoeia_{len(onomatopoeia_log) + 1:04d}"
        onomatopoeia_log.append(inst)


def merge_antagonist_templates(new_instances, template_log):
    """Merge antagonist_template_instances. Instances sharing a template_id
    are grouped under one template record with an `instances[]` list.

    Entries missing a template_id or an instance_entity are dropped rather
    than merged — without a template_id every such entry would otherwise
    collapse into one shared `template_id: None` junk bucket (this is what
    produced the ~70-null-instance stub template found in production data).
    Re-running merge over the same chapter (e.g. after a --repair pass) is
    also guarded against re-appending an identical instance.
    """
    for inst in new_instances:
        tid = inst.get("template_id")
        entity = inst.get("instance_entity")
        if not tid or not entity:
            continue

        template = next((t for t in template_log if t.get("template_id") == tid), None)
        if template is None:
            template = {
                "template_id": tid,
                "pattern": inst.get("pattern"),
                "instances": [],
            }
            template_log.append(template)
        else:
            # pattern text may be refined in later instances; keep latest
            if inst.get("pattern"):
                template["pattern"] = inst["pattern"]

        new_record = {
            "entity": entity,
            "chapters": inst.get("instance_chapters"),
            "variation_notes": inst.get("variation_notes"),
        }
        if new_record not in template["instances"]:
            template["instances"].append(new_record)


def merge_power_curve_notes(note, power_curve_log):
    if note:
        power_curve_log.append(note)


def _as_chapter_dict(data):
    """Coerce per-chapter data into a dict. Extractions sometimes emit a list
    (of [key,value] pairs, of dicts, or of strings) instead of an object."""
    if isinstance(data, dict):
        return dict(data)
    if isinstance(data, list):
        merged = {}
        for i, item in enumerate(data):
            if isinstance(item, dict):
                merged.update(item)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                merged[str(item[0])] = item[1]
            else:
                merged[f"item_{i}"] = item
        return merged
    # scalar / string
    return {"value": data}


def merge_reader_psychology(chapter_num, data, psychology_log):
    """Store reader psychology data keyed by chapter number."""
    if not data:
        return
    entry = _as_chapter_dict(data)
    entry["chapter"] = chapter_num
    for i, existing in enumerate(psychology_log):
        if isinstance(existing, dict) and existing.get("chapter") == chapter_num:
            psychology_log[i] = entry
            return
    psychology_log.append(entry)


def merge_author_intent(chapter_num, data, intent_log):
    """Store author intent data keyed by chapter number."""
    if not data:
        return
    entry = _as_chapter_dict(data)
    entry["chapter"] = chapter_num
    for i, existing in enumerate(intent_log):
        if isinstance(existing, dict) and existing.get("chapter") == chapter_num:
            intent_log[i] = entry
            return
    intent_log.append(entry)


def _normalize_reveal(rev):
    """Normalize reveal entries from older extractor formats to the v3 schema.

    Old format A (PBS): {"reveal": str, "significance": str, "foreshadowing_payoff": str, "prior_setup_chapter": int}
    Old format B (CMA/KI): {"reveal_type": str, "content": str, "chapter": int, "foreshadowed_in": ..., "significance": str}
    V3 format:  {"reveal_type": str, "content": str, "setup_chapters": [...], "payoff_chapter": int, ...}
    """
    rev = dict(rev)
    # Format A: has "reveal" key but no "reveal_type"
    if "reveal" in rev and "reveal_type" not in rev:
        rev["reveal_type"] = "plot_reveal"
        rev["content"] = rev.pop("reveal")
        if "prior_setup_chapter" in rev:
            rev.setdefault("setup_chapters", [rev.pop("prior_setup_chapter")])
    # Format B: has "chapter" but no "payoff_chapter"
    if "chapter" in rev and "payoff_chapter" not in rev:
        rev["payoff_chapter"] = rev.pop("chapter")
    # Chapter-reference fields are coerced from the LLM's occasional string
    # form ('Chapter 52') to int; setup_chapters can legitimately reference
    # earlier chapters than payoff_chapter, so both are normalized rather
    # than force-stamped to the current delta's chapter.
    if "payoff_chapter" in rev:
        rev["payoff_chapter"] = _coerce_chapter_int(rev["payoff_chapter"])
    if "revealed_to_reader_chapter" in rev:
        rev["revealed_to_reader_chapter"] = _coerce_chapter_int(rev["revealed_to_reader_chapter"])
    if isinstance(rev.get("setup_chapters"), list):
        rev["setup_chapters"] = [c for c in (_coerce_chapter_int(x) for x in rev["setup_chapters"]) if c is not None]
    return rev


def merge_reveals(new_reveals, reveals_log):
    """Append reveal entries, deduped by (reveal_type, content, payoff_chapter)."""
    for rev in new_reveals:
        rev = _normalize_reveal(rev)
        key = (rev.get("reveal_type"), rev.get("content"), rev.get("payoff_chapter"))
        existing = next((r for r in reveals_log
                         if (r.get("reveal_type"), r.get("content"), r.get("payoff_chapter")) == key), None)
        if existing:
            existing.update({k: v for k, v in rev.items() if v is not None})
        else:
            rev["id"] = f"reveal_{len(reveals_log) + 1:04d}"
            reveals_log.append(rev)


# ---------------------------------------------------------------------------
# Main merge for a single chapter delta
# ---------------------------------------------------------------------------

# Delta fields that MUST be lists of dict objects for the merge logic. Some
# extractions (especially CLI-mode fallback) emit bare strings or nested lists;
# we coerce/drop those so a single bad field never crashes the whole merge.
_LIST_OF_DICT_FIELDS = {
    "new_characters": "name", "new_locations": "name", "new_factions": "name",
    "new_glossary_terms": "term", "facts": "fact", "timeline_events": "event",
    "humor_instances": "text", "scheme_instances": "goal",
    "knowledge_state": "fact", "antagonist_template_instances": "template_id",
    "reveals": "content", "prose_samples": "text", "character_voice_samples": "text",
}


def _sanitize_delta(delta):
    """Coerce list-of-dict fields into a safe shape: strings become {key: str},
    non-dict/non-str items are dropped. Prevents AttributeError deep in merge."""
    if not isinstance(delta, dict):
        return delta
    for field, key in _LIST_OF_DICT_FIELDS.items():
        val = delta.get(field)
        if not isinstance(val, list):
            continue
        cleaned = []
        for item in val:
            if isinstance(item, dict):
                cleaned.append(item)
            elif isinstance(item, str) and item.strip():
                cleaned.append({key: item.strip()})
            # anything else (numbers, nested lists, None) is dropped
        delta[field] = cleaned
    return delta


def merge_chapter(delta, entities, alias_index, conflicts, timeline, glossary, humor_log, novel_meta, arcs,
                  scheme_log, knowledge_log, prose_log, antagonist_templates, power_curve_log,
                  psychology_log, intent_log, reveals_log):
    delta = _sanitize_delta(delta)
    chapter_num = delta.get("chapter_number")

    # --- Register/update entities from new_characters / new_locations / new_factions ---
    for bucket_key, default_type in [
        ("new_characters", "character"),
        ("new_locations", "location"),
        ("new_factions", "faction"),
    ]:
        for entry in delta.get(bucket_key, []):
            name = entry.get("name") if isinstance(entry, dict) else None
            if not name:
                continue  # skip malformed entity entries
            entity_type = entry.get("type", default_type)
            slug = resolve_entity(name, entity_type, alias_index, entities, conflicts)

            if slug not in entities:
                entities[slug] = new_entity_record(name, entity_type, chapter_num)
                # index canonical name immediately
                alias_index[name.lower().strip()] = slug

            merge_entity_meta(entities[slug], entry, chapter_num)

            # index any new aliases for future chapters
            for alias in entities[slug]["aliases"]:
                alias_index[alias.lower().strip()] = slug
            alias_index[entities[slug]["canonical_name"].lower().strip()] = slug

    # --- Apply explicit resolution hints (e.g. "Resolves Jiang Hai (ch.1) -> full name Jiang Zhen Hai") ---
    process_resolution_hints(delta, entities, alias_index, conflicts)

    # --- Apply merge_notes hints (manual disambiguation already done by extractor) ---
    # merge_notes are informational; they've already been reflected in how the
    # extractor wrote new_characters (e.g. using "Jiang Zhen Hai" not "Jiang Hai").
    # We still record them for provenance.
    if "merge_notes" in delta:
        conflicts.setdefault("merge_notes_log", []).append({
            "chapter": chapter_num,
            "notes": delta["merge_notes"],
        })

    # --- Facts ---
    for fact in delta.get("facts", []):
        # Support both old schema (subject/predicate/object) and new schema (fact/category)
        if "subject" in fact:
            # Old schema: RDF-style facts
            subject_name = fact["subject"]
            slug = resolve_entity(subject_name, "character", alias_index, entities, conflicts)
            if slug not in entities:
                # fact references an entity not declared in new_characters/etc;
                # create a minimal stub record
                entities[slug] = new_entity_record(subject_name, "unknown", chapter_num)
                alias_index[subject_name.lower().strip()] = slug

            add_fact(entities[slug], fact, conflicts, slug)

            if chapter_num not in entities[slug]["appearances"]:
                entities[slug]["appearances"].append(chapter_num)

            # Mirror symmetric relational facts onto the object entity so
            # relationship status (ally_of/enemy_of/etc.) stays consistent
            # regardless of which entity is queried.
            predicate = fact.get("predicate")
            obj = fact.get("object")
            obj_type = fact.get("object_type", "entity")
            if predicate in SYMMETRIC_PREDICATES and obj_type != "literal" and isinstance(obj, str):
                obj_key = obj.lower().strip()
                if obj_key in alias_index:
                    obj_slug = alias_index[obj_key]
                    if obj_slug != slug and obj_slug in entities:
                        mirrored = dict(fact)
                        mirrored["subject"] = entities[obj_slug]["canonical_name"]
                        mirrored["object"] = entities[slug]["canonical_name"]
                        mirrored["_mirrored_from"] = slug
                        add_fact(entities[obj_slug], mirrored, conflicts, obj_slug)
                        if chapter_num not in entities[obj_slug]["appearances"]:
                            entities[obj_slug]["appearances"].append(chapter_num)
        elif "fact" in fact:
            # New schema: simple narrative facts
            # Store in knowledge_log instead of entity-specific facts
            knowledge_log.append({
                "chapter": chapter_num,
                "fact": fact["fact"],
                "category": fact.get("category", "general"),
            })

    # --- Glossary ---
    for term in delta.get("new_glossary_terms", []):
        # Skip malformed glossary terms
        if not isinstance(term, dict) or "term" not in term:
            continue

        term_key = term["term"].lower().strip()
        # Support both 'definition' (old schema) and 'description' (new schema)
        term_def = term.get("definition") or term.get("description", "")
        existing = next((g for g in glossary if g["term"].lower().strip() == term_key), None)
        if existing:
            if existing["definition"] != term_def:
                existing.setdefault("definition_history", []).append({
                    "definition": existing["definition"],
                    "chapter": chapter_num,
                })
                existing["definition"] = term_def
        else:
            glossary.append({
                "term": term["term"],
                "definition": term_def,
                "first_seen_chapter": chapter_num,
            })

    # --- Timeline ---
    for event in delta.get("timeline_events", []):
        # Support both old schema (event) and new schema (description)
        event_text = event.get("event") or event.get("description", "")
        timeline.append({
            "chapter": chapter_num,
            "order": event.get("order") or event.get("sequence"),
            "event": event_text,
            "spoiler_note": event.get("spoiler_note"),
            "stakes": event.get("stakes"),
        })

    # --- Humor instances ---
    link_humor_instances(delta.get("humor_instances", []), humor_log, conflicts, chapter_num)

    # --- Scheme instances ---
    merge_scheme_instances(delta.get("scheme_instances", []), scheme_log, conflicts)

    # --- Knowledge state ---
    merge_knowledge_state(delta.get("knowledge_state", []), knowledge_log, conflicts)

    # --- Prose samples ---
    merge_prose_samples(delta.get("prose_samples", []), prose_log, chapter_num)

    # --- Antagonist templates ---
    merge_antagonist_templates(delta.get("antagonist_template_instances", []), antagonist_templates)

    # --- Power curve notes ---
    merge_power_curve_notes(delta.get("power_curve_notes"), power_curve_log)

    # --- Reader psychology ---
    merge_reader_psychology(chapter_num, delta.get("reader_psychology"), psychology_log)

    # --- Author intent ---
    merge_author_intent(chapter_num, delta.get("author_intent"), intent_log)

    # --- Reveals ---
    merge_reveals(delta.get("reveals", []), reveals_log)

    # --- Novel metadata hints (alt titles, translator notes, genre signals) ---
    hints = delta.get("novel_metadata_hints", {})
    for title in hints.get("alt_titles", []):
        if title not in novel_meta["alt_titles"]:
            novel_meta["alt_titles"].append(title)

    for note in hints.get("translator_notes", []):
        novel_meta["translator_notes"].append(note)

    for signal in hints.get("genre_signals", []):
        novel_meta["genre_signals"][signal] = novel_meta["genre_signals"].get(signal, [])
        if chapter_num not in novel_meta["genre_signals"][signal]:
            novel_meta["genre_signals"][signal].append(chapter_num)

    # --- Arc label aggregation ---
    arc_label = delta.get("arc_label_suggestion")
    if arc_label:
        # An arc_label_suggestion may describe a transition, e.g.
        # "Arc 1: X (closes) / Arc 2: Y (opens)". Split on " / " and
        # assign the first part to this chapter, opening the second
        # part as a new arc starting at this chapter.
        parts = [p.strip() for p in arc_label.split("/")]
        primary = parts[0].replace("(closes)", "").strip()
        _assign_chapter_to_arc(arcs, primary, chapter_num)
        if len(parts) > 1:
            new_arc = parts[1].replace("(opens)", "").strip()
            _assign_chapter_to_arc(arcs, new_arc, chapter_num, is_start=True)

    # --- Chapter summary metadata stored on a pseudo "chapter" entity ---
    chapter_slug = f"chapter_{chapter_num:04d}"
    entities[chapter_slug] = {
        "canonical_name": f"Chapter {chapter_num}",
        "type": "chapter_meta",
        "summary": delta.get("summary"),
        "arc_boundary_signal": delta.get("arc_boundary_signal", False),
        "arc_notes": delta.get("arc_notes"),
    }


# ---------------------------------------------------------------------------
# v2.1 Enhanced Aggregation Functions
# ---------------------------------------------------------------------------

def aggregate_style_dna(delta, style_dna_evolution):
    """Aggregate style_dna from v2.1 deltas to track evolution over chapters."""
    if "style_dna" not in delta:
        return

    chapter_num = delta.get("chapter_number")
    style_dna_evolution.append({
        "chapter": chapter_num,
        "style_dna": delta["style_dna"]
    })


def aggregate_prose_by_type(delta, prose_by_type):
    """Index prose samples by type for easy lookup during generation."""
    if "prose_samples" not in delta:
        return

    chapter_num = delta.get("chapter_number")

    for sample in delta["prose_samples"]:
        sample_type = sample.get("type", "unknown")
        if sample_type not in prose_by_type:
            prose_by_type[sample_type] = []

        # Add chapter reference
        sample_with_chapter = sample.copy()
        sample_with_chapter["source_chapter"] = chapter_num
        prose_by_type[sample_type].append(sample_with_chapter)


def _normalize_voice_samples(raw):
    """
    Coerce character_voice_samples into a list of dicts with a `character_name`
    and a `dialogue_samples` list.

    The extractor is inconsistent about this field across chapters (all four of
    these shapes occur in my_novel ch91-95):
      * list of dicts keyed `character_name` + `dialogue_samples`  (canonical)
      * list of dicts keyed `character` + `sample`                 (singular)
      * list of bare strings                                       (no speaker)
      * dict of {character_slug: {dialogue_samples|internal_monologue_samples}}
    A dict used to crash the merge outright with
    'str' object has no attribute 'get'.
    """
    if not raw:
        return []

    # dict-of-characters -> list of per-character dicts
    if isinstance(raw, dict):
        items = []
        for key, val in raw.items():
            if isinstance(val, dict):
                entry = dict(val)
                entry.setdefault("character_name", key)
                items.append(entry)
            elif isinstance(val, list):
                items.append({"character_name": key, "dialogue_samples": val})
            elif isinstance(val, str):
                items.append({"character_name": key, "dialogue_samples": [val]})
        raw = items

    if not isinstance(raw, list):
        return []

    out = []
    for item in raw:
        # A bare string has no speaker attached — nothing to aggregate onto an
        # entity, so skip rather than guess who said it.
        if not isinstance(item, dict):
            continue

        entry = dict(item)
        name = (entry.get("character_name") or entry.get("character")
                or entry.get("name") or entry.get("speaker") or "")
        if not isinstance(name, str) or not name.strip():
            continue
        entry["character_name"] = name.strip()

        # Gather every spelling of "the lines this character said".
        samples = []
        for key in ("dialogue_samples", "internal_monologue_samples",
                    "samples", "sample", "quote", "line", "text"):
            val = entry.get(key)
            if isinstance(val, list):
                samples.extend(val)
            elif isinstance(val, str) and val.strip():
                samples.append(val)
        entry["dialogue_samples"] = samples
        out.append(entry)
    return out


def aggregate_character_voices(delta, entities, alias_index):
    """Merge character_voice_samples into entity voice_dna."""
    if "character_voice_samples" not in delta:
        return

    chapter_num = delta.get("chapter_number")

    for voice_sample in _normalize_voice_samples(delta["character_voice_samples"]):
        char_name = voice_sample.get("character_name")
        if not char_name:
            continue

        # Resolve to entity slug
        slug = alias_index.get(char_name.lower().strip())
        if not slug or slug not in entities:
            # Entity not found, skip
            continue

        entity = entities[slug]

        # Initialize voice_dna if not present
        if "voice_dna" not in entity:
            entity["voice_dna"] = {
                "dialogue_samples": [],
                "speech_dna_history": []
            }

        # Append dialogue samples
        for dialogue in voice_sample.get("dialogue_samples", []):
            # Handle both dict and string formats (LLM sometimes returns bare strings)
            if isinstance(dialogue, str):
                dialogue_with_chapter = {"text": dialogue}
            elif isinstance(dialogue, dict):
                dialogue_with_chapter = dialogue.copy()
            else:
                continue  # skip malformed entries
            dialogue_with_chapter["chapter"] = chapter_num
            entity["voice_dna"]["dialogue_samples"].append(dialogue_with_chapter)

        # Append speech_dna snapshot
        if "speech_dna" in voice_sample:
            speech_dna_snapshot = voice_sample["speech_dna"].copy()
            speech_dna_snapshot["chapter"] = chapter_num
            entity["voice_dna"]["speech_dna_history"].append(speech_dna_snapshot)


def aggregate_scene_patterns(delta, scene_patterns):
    """Catalog scene structures for pattern recognition."""
    if "scene_structure_patterns" not in delta:
        return

    chapter_num = delta.get("chapter_number")
    structure = delta["scene_structure_patterns"]

    # Add chapter-level pattern
    if "scenes" in structure:
        for scene in structure["scenes"]:
            scene_type = scene.get("scene_type", "unknown")

            if scene_type not in scene_patterns:
                scene_patterns[scene_type] = {
                    "examples": [],
                    "avg_tension": 0,
                    "common_pacing": {},
                    "common_structures": []
                }

            # Add example
            scene_with_chapter = scene.copy()
            scene_with_chapter["chapter"] = chapter_num
            scene_patterns[scene_type]["examples"].append(scene_with_chapter)

            # Update averages
            examples = scene_patterns[scene_type]["examples"]
            # tension_level is a number, but some deltas carry a word ("high"); only the numeric ones go into the average
            tensions = [s["tension_level"] for s in examples
                        if isinstance(s.get("tension_level"), (int, float)) and not isinstance(s.get("tension_level"), bool)]
            scene_patterns[scene_type]["avg_tension"] = sum(tensions) / len(tensions) if tensions else 0

            # Track pacing frequency
            pacing = scene.get("pacing", "unknown")
            scene_patterns[scene_type]["common_pacing"][pacing] = scene_patterns[scene_type]["common_pacing"].get(pacing, 0) + 1


def aggregate_narrative_tracking(delta, narrative_tracking):
    """Track POV usage and narrative voice patterns."""
    if "narrative_voice_analysis" not in delta:
        return

    chapter_num = delta.get("chapter_number")
    analysis = delta["narrative_voice_analysis"]

    narrative_tracking.append({
        "chapter": chapter_num,
        "dominant_pov": analysis.get("dominant_pov"),
        "pov_shifts": analysis.get("pov_shifts", []),
        "narrative_intrusions_count": len(analysis.get("narrative_intrusions", [])),
        "thought_presentation": analysis.get("thought_presentation", {})
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(delta_paths, novel_id):
    paths = novel_paths(novel_id)
    ensure_novel_dirs(paths)

    entities = load_all_entities(paths["entities"])
    alias_index = build_alias_index(entities)
    conflicts = load_json(paths["conflicts"], {})
    timeline = load_json(paths["timeline"], [])
    glossary = load_json(paths["glossary"], [])
    humor_log = load_json(paths["humor"], [])
    arcs = load_json(paths["arcs"], [])
    scheme_log = load_json(paths["schemes"], [])
    knowledge_log = load_json(paths["knowledge"], [])
    prose_log = load_json(paths["prose"], [])
    antagonist_templates = load_json(paths["antagonist_templates"], [])
    power_curve_log = load_json(paths["power_curve"], [])
    psychology_log = load_json(paths["reader_psychology"], [])
    intent_log = load_json(paths["author_intent"], [])
    reveals_log = load_json(paths["reveals"], [])
    novel_meta = load_json(paths["novel_meta"], {
        "title": novel_id,
        "novel_id": novel_id,
        "alt_titles": [],
        "translator_notes": [],
        "genre_signals": {},
    })

    # v2.1 ENHANCED AGGREGATIONS
    style_dna_evolution = load_json(paths["style_dna_evolution"], [])
    prose_by_type = load_json(paths["prose_by_type"], {})
    scene_patterns = load_json(paths["scene_patterns"], {})
    narrative_tracking = load_json(paths["narrative_tracking"], [])

    # A chapter already in the brain must not be merged again: the merge only ADDS records, so a second pass duplicates the chapter's
    # timeline events, entity facts, narrative tracking... (a chapter whose delta has no reader psychology was never recognised as merged,
    # and the Corpus Builder's pre-flight re-merged it on every run). NM_REMERGE=1 forces it.
    merged_seen = ({r.get("chapter") for r in psychology_log if isinstance(r, dict)}
                   | {e.get("chapter") for e in timeline if isinstance(e, dict)}
                   | {r.get("chapter") for r in narrative_tracking if isinstance(r, dict)})
    merged_seen.discard(None)
    max_chapter = 0
    for path in sorted(delta_paths):
        path = Path(path)
        delta = load_json(path, None)
        if delta is None:
            print(f"  [skip] could not read {path}")
            continue
        _chn = delta.get("chapter_number")
        if _chn in merged_seen and not os.environ.get("NM_REMERGE"):
            print(f"  [skip] {path.name}: chapter {_chn} is already in the brain (merging it again would duplicate it)")
            continue
        merged_seen.add(_chn)
        print(f"Merging {path.name} (chapter {delta.get('chapter_number')})...")
        merge_chapter(delta, entities, alias_index, conflicts, timeline, glossary, humor_log, novel_meta, arcs,
                       scheme_log, knowledge_log, prose_log, antagonist_templates, power_curve_log,
                       psychology_log, intent_log, reveals_log)

        # v2.1 ENHANCED AGGREGATIONS (gracefully handle both v2.0 and v2.1 deltas)
        aggregate_style_dna(delta, style_dna_evolution)
        aggregate_prose_by_type(delta, prose_by_type)
        aggregate_character_voices(delta, entities, alias_index)
        aggregate_scene_patterns(delta, scene_patterns)
        aggregate_narrative_tracking(delta, narrative_tracking)

        if delta.get("chapter_number"):
            max_chapter = max(max_chapter, delta["chapter_number"])

    # --- Write everything back out ---
    for slug, record in entities.items():
        save_json(paths["entities"] / f"{slug}.json", record)

    save_json(paths["timeline"], sorted(timeline, key=lambda e: (e["chapter"], e.get("order") or 0)))
    save_json(paths["glossary"], glossary)
    save_json(paths["humor"], humor_log)
    save_json(paths["arcs"], arcs)
    save_json(paths["novel_meta"], novel_meta)
    save_json(paths["schemes"], scheme_log)
    save_json(paths["knowledge"], knowledge_log)
    save_json(paths["prose"], prose_log)
    save_json(paths["antagonist_templates"], antagonist_templates)
    save_json(paths["power_curve"], power_curve_log)
    save_json(paths["reader_psychology"], sorted(psychology_log, key=lambda x: x.get("chapter", 0)))
    save_json(paths["author_intent"], sorted(intent_log, key=lambda x: x.get("chapter", 0)))
    save_json(paths["reveals"], reveals_log)

    # v2.1 ENHANCED AGGREGATIONS
    save_json(paths["style_dna_evolution"], sorted(style_dna_evolution, key=lambda x: x.get("chapter", 0)))
    save_json(paths["prose_by_type"], prose_by_type)
    save_json(paths["scene_patterns"], scene_patterns)
    save_json(paths["narrative_tracking"], sorted(narrative_tracking, key=lambda x: x.get("chapter", 0)))

    conflicts["_last_merge"] = datetime.now(timezone.utc).isoformat()
    save_json(paths["conflicts"], conflicts)

    # Keep the top-level novel registry in sync
    if max_chapter:
        # the registry's "chapters extracted" is a COUNT of the chapterN.json files; max_chapter (the highest chapter
        # number) goes in its own field. It used to store max_chapter as the count, so a novel extracted as chapters
        # 1-104 plus 224-301 read "301".
        _d3 = paths["root"] / "deltas_v3"
        _count = sum(1 for f in _d3.iterdir() if re.match(r"^ch\d+\.json$", f.name)) if _d3.is_dir() else 0
        update_registry(novel_id, novel_meta.get("title"), _count or max_chapter, highest_chapter=max_chapter)

    print(f"\nDone. {len(entities)} entity files written to {paths['entities']}/")
    print(f"Novel: {novel_meta.get('title', novel_id)} ({novel_id})")
    print(f"Arcs: {len(arcs)}, genre signals: {len(novel_meta.get('genre_signals', {}))}, translator notes: {len(novel_meta.get('translator_notes', []))}")
    print(f"Schemes: {len(scheme_log)}, knowledge states: {len(knowledge_log)}, prose samples: {len(prose_log)}, antagonist templates: {len(antagonist_templates)}, power curve notes: {len(power_curve_log)}")
    print(f"Reader psychology: {len(psychology_log)} chapters, author intent: {len(intent_log)} chapters, reveals: {len(reveals_log)}")

    # v2.1 stats
    total_prose_by_type = sum(len(samples) for samples in prose_by_type.values())
    entities_with_voice = sum(1 for e in entities.values() if "voice_dna" in e)
    if style_dna_evolution or total_prose_by_type or entities_with_voice:
        print(f"[v2.1] Style DNA snapshots: {len(style_dna_evolution)}, Prose samples by type: {total_prose_by_type} across {len(prose_by_type)} types, Scene patterns: {len(scene_patterns)} types, Narrative tracking: {len(narrative_tracking)} chapters")
        print(f"[v2.1] Entities with voice DNA: {entities_with_voice}")

    if any(k != "_last_merge" and k != "merge_notes_log" for k in conflicts):
        print(f"NOTE: conflicts/warnings recorded in {paths['conflicts']} -- review these.")


if __name__ == "__main__":
    args = sys.argv[1:]
    # --novel is REQUIRED: a silent default once merged one novel's deltas into
    # another's aggregates (cross-novel corruption). Fail loudly instead.
    novel_id = None
    delta_args = []
    i = 0
    while i < len(args):
        if args[i] == "--novel":
            novel_id = args[i + 1]
            i += 2
        else:
            delta_args.append(args[i])
            i += 1

    if not novel_id or not delta_args:
        print(f"Usage: python {sys.argv[0]} --novel <novel_id> <delta1.json> [delta2.json ...]")
        if not novel_id:
            print("ERROR: --novel is required (no default — prevents merging into the wrong novel).")
        sys.exit(1)
    main(delta_args, novel_id)
