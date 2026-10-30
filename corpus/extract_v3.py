"""
extract_v3.py - Schema v3.0 Full Extraction

Unified single-pass extraction combining v2.0 narrative/plot intelligence
with v2.1 style/generation DNA. Both layers are requested from the LLM in
one call.

Output: novels/<novel>/deltas_v3/chNNN.json

Usage:
    python extract_v3.py --novel my_novel --chapter 1
    python extract_v3.py --novel my_novel --start 1 --end 10
    python extract_v3.py --novel my_novel --chapter 1
"""

import json
import re
import sys
import argparse
import time
from pathlib import Path
from collections import Counter
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# LLM calls go through llm_client (API key OR Claude subscription CLI).
# The old module-level `client` is no longer used but kept as None for safety.
client = None


def load_chapter_text(novel_id: str, chapter_num: int) -> str:
    raw_path = Path(f"raw/{novel_id}/ch{chapter_num}.txt")
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw chapter not found: {raw_path}")
    with open(raw_path, 'r', encoding='utf-8') as f:
        return f.read()


def analyze_style_dna(text: str) -> dict:
    """Programmatic pass — quantitative measurements the LLM doesn't need to count."""
    lines = text.strip().split('\n')
    if lines and re.match(r'^Chapter \d+', lines[0]):
        text = '\n'.join(lines[1:])

    sentences = re.split(r'[.!?]+\s+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    sentence_lengths = [len(s.split()) for s in sentences]
    total_sentences = max(len(sentence_lengths), 1)

    short  = sum(1 for l in sentence_lengths if 1 <= l <= 10)
    medium = sum(1 for l in sentence_lengths if 11 <= l <= 25)
    long   = sum(1 for l in sentence_lengths if l >= 26)

    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 20]
    total_paras = max(len(paragraphs), 1)

    para_sentence_counts = []
    for para in paragraphs:
        ps = re.split(r'[.!?]+\s+', para)
        para_sentence_counts.append(len([s for s in ps if len(s.strip()) > 10]))

    single      = sum(1 for c in para_sentence_counts if c == 1)
    two_to_four = sum(1 for c in para_sentence_counts if 2 <= c <= 4)
    five_plus   = sum(1 for c in para_sentence_counts if c >= 5)

    # Characters inside double quotes — straight or curly, mixed allowed, since the
    # corpus has all of "...", “...” and “...". A quote left unclosed runs to the end
    # of its line (some translators open every dialogue line with “ and rarely close
    # it — a reference novel from ~ch51 on); spans never cross a line break, so
    # narration can't be swallowed. Was len(findall(...)) / total_chars, i.e. quoted
    # SPANS per CHARACTER, which rounded to ~0.0 for every chapter.
    dialogue_chars = sum(len(m) for m in re.findall(r'[“"][^“”"\n]{2,}(?:[”"]|$)', text, re.M))
    total_chars = max(len(text), 1)
    words = text.split()
    total_words = max(len(words), 1)

    exclamations = text.count('!')
    questions    = text.count('?')

    profanity_words = ['fuck', 'damn', 'shit', 'bastard', 'bitch', 'hell']
    profanity_count = sum(text.lower().count(p) for p in profanity_words)

    common_prof = []
    for p in profanity_words:
        pattern = re.compile(r'\b' + p + r'\w*\b', re.IGNORECASE)
        matches = pattern.findall(text)
        if matches:
            common_prof.append(Counter(matches).most_common(1)[0][0])

    transition_patterns = [
        r'right at this moment', r'at the same time', r'after that',
        r'suddenly', r'immediately', r'in an instant', r'at this point',
        r'just as', r'meanwhile', r'however', r'therefore'
    ]
    found_transitions = []
    for pattern in transition_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            found_transitions.append(m.group())
    found_transitions = list(set(found_transitions))[:4]

    # ── Voice-fingerprint signals ────────────────────────────────────────
    # Added for the AI-detection/voice-deviation feature: the author's own
    # spec (see the feature request this was built from) explicitly wants
    # PATTERNS scored together, not any single symbol counted alone — "em
    # dash frequency is 2.8x baseline + repeated contrast construction +
    # uniform sentence lengths" is the target shape, not "— appears 47
    # times = AI". Everything here stays a plain regex/counter pass, same
    # zero-LLM-cost discipline as the rest of this function; a doc note
    # elsewhere (corpus/GENERATION_GROUNDING_REFERENCE.md-adjacent) lists
    # the harder LLM-only signals (metaphor density, emotion-explanation,
    # cliché density) this deliberately does NOT attempt yet.
    import statistics as _stats

    def _variance(xs):
        return round(_stats.pvariance(xs), 2) if len(xs) >= 2 else 0.0

    # Sentence-length variance — HIGH per the spec: "suspiciously consistent
    # sentence lengths" is one of the strongest single AI-tell signals, and
    # the existing short/medium/long BUCKETS above can't distinguish a
    # genuinely varied author (short short short LONG short) from a
    # metronomic one (12, 13, 12, 14, 13 words) that happens to land in the
    # same "medium" bucket every time — variance captures what the buckets
    # can't.
    sentence_length_variance = _variance(sentence_lengths)

    # Paragraph-length variance (in sentence-count terms) — same reasoning,
    # for paragraphs instead of sentences.
    paragraph_length_variance = _variance(para_sentence_counts)

    # Opening-word repetition — "He... He... He..." pattern: the fraction of
    # sentences whose first word repeats the immediately preceding
    # sentence's first word. HIGH signal per the spec.
    opening_words = [s.split()[0].lower() if s.split() else "" for s in sentences]
    repeated_openings = sum(1 for i in range(1, len(opening_words))
                            if opening_words[i] and opening_words[i] == opening_words[i - 1])
    opening_repetition_rate = round(repeated_openings / total_sentences, 3)

    # Contrast constructions — "not X, but Y" / "it wasn't X — it was Y" —
    # HIGH signal per the spec, a genuinely distinctive rhetorical tic when
    # overused.
    contrast_pattern = re.compile(
        r'\bnot\s+[a-z][\w\s,]{0,40}?\bbut\b|it\s+wasn.?t\b[\w\s,]{0,40}?[—-]\s*it\s+was\b',
        re.IGNORECASE)
    contrast_construction_count = len(contrast_pattern.findall(text))
    contrast_construction_rate = round(contrast_construction_count / total_sentences, 3)

    # Three-part lists — "X, Y, and Z" — MEDIUM signal.
    three_part_list_count = len(re.findall(r'\b\w+,\s+\w+,?\s+and\s+\w+\b', text))
    three_part_list_rate = round(three_part_list_count / total_sentences, 3)

    # Punctuation rates beyond the existing em-dash count — semicolons
    # (MEDIUM), colons (LOW), ellipses (LOW-MEDIUM per the spec).
    semicolon_rate = round(text.count(';') / total_sentences, 3)
    colon_rate     = round(text.count(':') / total_sentences, 3)
    ellipsis_rate  = round((text.count('…') + len(re.findall(r'\.\s?\.\s?\.', text))) / total_sentences, 3)

    # Vocabulary repetition — words appearing disproportionately often,
    # excluding a small stopword set — HIGH signal per the spec ("same
    # unusual words appearing disproportionately"). Only counts words of
    # 5+ letters (short common words dominate any text and aren't a useful
    # tell) appearing 4+ times, reported as a rate per 1000 words so it's
    # comparable across chapters of different lengths.
    _STOPWORDS = {"there", "their", "would", "could", "should", "which", "these",
                 "those", "about", "after", "before", "still", "again", "where",
                 "toward", "though", "through", "though", "being", "while"}
    word_tokens = re.findall(r"[a-zA-Z']{5,}", text.lower())
    word_counts = Counter(w for w in word_tokens if w not in _STOPWORDS)
    overused = [(w, c) for w, c in word_counts.most_common(10) if c >= 4]
    vocabulary_repetition_rate = round(sum(c for _, c in overused) / max(total_words, 1) * 1000, 2)
    top_overused_words = [w for w, _ in overused[:6]]

    # Redundant/perfect-grammar signals are deliberately NOT attempted here
    # (LOW-MEDIUM/LOW strength per the spec, and genuinely need an LLM read
    # to judge accurately — a regex can't tell "explained because it needed
    # explaining" from "explained the emotion right after showing it").

    return {
        "sentence_length_distribution": {
            "short_1_10_words":   round(short  / total_sentences, 2),
            "medium_11_25_words": round(medium / total_sentences, 2),
            "long_26_plus_words": round(long   / total_sentences, 2)
        },
        "paragraph_length_distribution": {
            "single_sentence":       round(single      / total_paras, 2),
            "two_to_four_sentences": round(two_to_four / total_paras, 2),
            "five_plus_sentences":   round(five_plus   / total_paras, 2)
        },
        "content_ratios": {
            "dialogue_percentage":          round(dialogue_chars / total_chars, 2),
            "action_percentage":            0.0,
            "description_percentage":       0.0,
            "internal_monologue_percentage": 0.0
        },
        "pacing_markers": {
            "average_words_between_dialogue":    0,
            "average_words_between_paragraphs":  round(total_words / total_paras, 1),
            "action_sequence_avg_length_words":  0,
            "exposition_block_avg_length_words": 0
        },
        "stylistic_devices": {
            "repetition_for_emphasis":    0.0,
            "rhetorical_questions":       round(questions    / total_sentences, 2),
            "exclamations":               round(exclamations / total_sentences, 2),
            "em_dashes_parentheticals":   round(text.count('—') / total_sentences, 2),
            "sensory_details_per_scene":  0.0,
            "metaphor_simile_frequency":  0.0
        },
        "vocabulary_markers": {
            "favorite_intensifiers":      [],
            "favorite_transitions":       found_transitions,
            "favorite_descriptors_power": [],
            "favorite_descriptors_emotion": [],
            "profanity_frequency": round(profanity_count / total_words, 4),
            "common_profanity":    common_prof
        },
        "character_catchphrases":   {},
        "distinctive_style_markers": [],
        # New, additive top-level key — every existing caller reads the keys
        # above unchanged; nothing here removes or renames anything. Rates
        # are per-sentence unless noted, so they're comparable across
        # chapters/novels of different lengths the same way the distributions
        # above already are.
        "voice_fingerprint": {
            "punctuation": {
                "semicolon_rate": semicolon_rate,
                "colon_rate": colon_rate,
                "ellipsis_rate": ellipsis_rate,
                "em_dash_rate": round(text.count('—') / total_sentences, 3),   # mirrors stylistic_devices' value at finer precision
            },
            "sentence": {
                "average_length": round(sum(sentence_lengths) / total_sentences, 1) if sentence_lengths else 0,
                "length_variance": sentence_length_variance,
                "opening_repetition_rate": opening_repetition_rate,
            },
            "paragraph": {
                "length_variance": paragraph_length_variance,
            },
            "style": {
                "contrast_construction_rate": contrast_construction_rate,
                "three_part_list_rate": three_part_list_rate,
            },
            "vocabulary": {
                "repetition_rate_per_1000_words": vocabulary_repetition_rate,
                "top_overused_words": top_overused_words,
            },
        },
    }


SYSTEM_PROMPT = """You are extracting structured narrative intelligence from a web novel chapter.
Produce a single JSON object containing every key defined below. No markdown fences.

─── LAYER 1: PLOT / NARRATIVE INTELLIGENCE ───────────────────────────────────

chapter_title     — string, title of chapter (empty string if none)
title_function    — "foreshadow" | "payoff_callback" | "thematic_statement" | "introduction" | "none"
chapter_function  — "setup" | "escalation" | "payoff" | "climax" | "resolution" | "transition" | "hook" | "cooldown" | "arc_finale" | "reveal" | "training_interlude" | "worldbuilding" | "twist"
summary           — 2-5 sentences covering all major events
arc_label_suggestion — string, e.g. "Arc 1: City of Origin"
arc_boundary_signal  — true | false (true = this chapter opens or closes an arc)
arc_notes            — string, pacing/arc commentary (or "")

new_characters — array of:
  { name, aliases[], type:"character", role:"protagonist|antagonist|supporting|minor_antagonist|minor_supporting",
    comedic_role:"straight_man|gag_character|deadpan_snarker|comic_relief|running_gag_target|none",
    description, notes }

new_locations — array of { name, type:"location", description, notes }
new_factions  — array of { name, type:"faction", description, notes }

new_glossary_terms — array of:
  { term, definition, category:"cultivation_realm|cultivation_concept|skill|stat|item|location|class|power_system|world_event|system_mechanic|other", chapter_introduced }

facts — array of:
  { subject, predicate, object, object_type:"entity|literal", source_chapter, status:"active|superseded", notes, spoiler_note }
  Valid predicates: has_alias, family_of, member_of, leads, ally_of, enemy_of, romantic_with,
    has_appearance_trait, has_personality_trait, has_ability, has_power_rank, has_reputation, wants,
    located_in, born_in, controls, owns, has_attribute, occurred_at_location, occurred_to_character

timeline_events — array of { event, order, source_chapter, stakes, spoiler_note }

humor_instances — array of:
  { type:"deadpan_reaction|situational_irony|character_dynamic|running_gag|subverted_trope|escalation_gag|fish_out_of_water",
    participants[], setup, payoff, tone_tags[], source_chapter, recurrence:"one-off|running_gag|callback",
    callback_to, example_text }

scheme_instances — array of:
  { schemer, target, goal, mechanism, setup_chapter, execution_chapter, payoff_chapter,
    status:"ongoing|succeeded|failed|discovered", victim_aware, stakes, tags[] }

knowledge_state — array of:
  { fact, known_to[], hidden_from[], hidden_from_notes, established_chapter, resolved_chapter, resolution }

antagonist_template_instances — array of:
  { template_id, pattern, instance_entity, instance_chapters[], variation_notes }

power_curve_notes — object (or null if no power progression this chapter):
  { chapter_range[start,end], pattern, implies_for_future }

reveals — array of:
  { reveal_type:"power_reveal|identity_reveal|relationship_reveal|conspiracy_reveal|world_reveal|betrayal_reveal|secret_goal_reveal|ability_reveal",
    content, setup_chapters[], payoff_chapter, revealed_to[], hidden_from_until_now[], impact }

reader_psychology — object:
  { reader_emotions: {awe,satisfaction,anticipation,curiosity,fear,tension,comedy,sadness,disgust},
    payoff_categories: {power_fantasy,justice,revenge,mystery,comedy,wish_fulfillment,strategic_victory,catharsis,tension,character_growth,political_intrigue,emotional_connection},
    tension_curve: {start,peak,end} }
  SCALES (strict): reader_emotions and payoff_categories are 0-10 INTEGERS.
  tension_curve start/peak/end are 0-100. Never score an emotion above 10 —
  a value like 95 is wrong; the correct value on that scale is 9 or 10.
  Omit zero-value keys.

author_intent — object:
  { author_goal, reader_effect, theme_reinforced, strategy_notes }

─── LAYER 2: STYLE / GENERATION DNA ─────────────────────────────────────────

prose_samples — array of 10-20 verbatim excerpts:
  { type:"combat_technique|combat_reaction|dialogue_threat|dialogue_banter|dialogue_exposition|internal_monologue_planning|internal_monologue_reaction|scene_transition|power_reveal|comedy_setup|comedy_payoff|description_environment|description_character|emotional_beat|cultivation_description",
    excerpt, source_chapter, source_character_pov, narrative_distance:"close_third|distant_third|omniscient|first_person",
    style_notes, tags[] }

style_dna_refinements — object (used to patch programmatic base):
  { content_ratios: {dialogue_percentage,action_percentage,description_percentage,internal_monologue_percentage},
    pacing_markers: {average_words_between_dialogue,action_sequence_avg_length_words,exposition_block_avg_length_words},
    stylistic_devices: {repetition_for_emphasis,sensory_details_per_scene,metaphor_simile_frequency},
    vocabulary_markers: {favorite_intensifiers[],favorite_descriptors_power[],favorite_descriptors_emotion[]},
    character_catchphrases: {CharacterName: ["phrase"]},
    distinctive_style_markers: ["string"] }

character_voice_samples — array of:
  { character_name, dialogue_samples:[{line,context,voice_notes}],
    speech_dna: {formality_level:"street|casual|neutral|formal|archaic",
                 verbosity:"terse|normal|verbose",
                 emotional_expression:"stoic|controlled|expressive|volatile",
                 signature_phrases[], sentence_structure_preference:"simple|compound|complex|fragmented",
                 uses_profanity, uses_humor:"never|rarely|often|constantly",
                 humor_style:"deadpan|sarcastic|absurd|self_deprecating|boastful|none"} }

scene_structure_patterns — object:
  { scenes: [{scene_number, estimated_word_count,
              scene_type:"combat|dialogue|exposition|travel_transition|cultivation|planning|revelation|comedy_sequence|emotional_confrontation|power_discovery",
              pov_character, narrative_distance, tension_level, pacing:"slow_burn|steady|rapid|explosive", structure_notes}],
    chapter_rhythm: {opening_hook:"action|dialogue|mystery|continuation|description",
                     middle_build:"steady_escalation|plateau|multiple_peaks|calm_before_storm",
                     ending_type:"cliffhanger|resolution|transition|emotional_beat|comedy_button",
                     scene_count, average_scene_length_words, longest_scene_words, shortest_scene_words} }

narrative_voice_analysis — object:
  { dominant_pov, pov_shifts:[{from_character,to_character,at_scene_number,transition_style}],
    narrative_intrusions:[{excerpt,type,tone}],
    thought_presentation: {internal_monologue_style:"italicized|tagged_with_thought|untagged_free_indirect|stream_of_consciousness|first_person_direct",
                           frequency:"rare|occasional|frequent|constant",
                           depth:"surface_reactions|strategic_planning|philosophical_reflection|memory_flashback"},
    structural_notes,
    genre_contract_signals: ["string"] }

─── WHEN A CHAPTER GENUINELY CONTAINS NOTHING FOR A FIELD ───────────────────

Some chapters truly contain no scheming, no new faction, no antagonist pattern,
no humour. Do NOT invent content to fill such a field, and do NOT silently omit
the key. Instead return the exact string "none" as that key's value:

  "scheme_instances": "none",
  "antagonist_template_instances": "none"

"none" means "I read the chapter and this genuinely does not occur here" — it is
a real, useful answer and is recorded as such. Omitting a key or returning [] is
read as "not extracted" and will cause the chapter to be re-processed.

Only these keys accept "none": new_characters, new_locations, new_factions,
new_glossary_terms, facts, timeline_events, humor_instances, scheme_instances,
knowledge_state, antagonist_template_instances, power_curve_notes, reveals,
prose_samples, character_voice_samples. Every other key must always have a real
value — summary, chapter_function, reader_psychology and author_intent are never
"none".

Return ONLY the JSON object with every key defined above. No markdown. No explanation."""


# The full schema, split into three coherent passes for engines that cannot
# reliably emit 7-15k tokens of JSON in one response (measured: a full delta is
# 24-60 KB). The input is small either way (~6k tokens) — it is the OUTPUT size
# that breaks non-Claude models, so the split is by output group, not by text.
# Group membership is derived from the MEASURED output weight of 78 existing
# deltas, not from intuition. prose_samples alone averages 8.8 KB — 25% of a
# whole delta — so it gets a call to itself; pairing it with anything pushes
# that response back over the size that breaks weaker models.
#
# Balance by bytes: prose 25.0% / voice 25.9% / plot 29.6% / world 19.5%,
# roughly 1.7k-2.6k output tokens each instead of one ~8.8k response.
# Every schema field appears in exactly one group.
#
# Splitting further than 4 buys nothing: prose_samples is the floor, so a 5-way
# split leaves the largest call unchanged while adding another round trip.
SPLIT_GROUPS = [
    ("prose", [
        "prose_samples",
    ]),
    ("voice", [
        "character_voice_samples", "narrative_voice_analysis",
        "scene_structure_patterns", "reader_psychology", "author_intent",
        "style_dna_refinements",
    ]),
    ("plot", [
        "title_function", "chapter_function", "summary",
        "arc_label_suggestion", "arc_boundary_signal", "arc_notes",
        "facts", "timeline_events", "knowledge_state", "reveals",
    ]),
    ("world", [
        "new_characters", "new_locations", "new_factions", "new_glossary_terms",
        "humor_instances", "scheme_instances", "antagonist_template_instances",
        "power_curve_notes",
    ]),
]

# Same schema as SPLIT_GROUPS, split finer — for engines whose calls time out
# or degrade even on the 4-way plan's SMALLEST call (measured live: an
# Ollama-bridged local model timed out on "prose", the 1-field group, not just
# the denser plot/world groups). prose/voice/plot are halved (proven live to
# fully succeed on qwen3.6:latest at this granularity — see
# chapter_extraction_comparison.md). world is quartered into world_a-d (2 keys
# each) instead of just halved: measured live that world_a/world_b (4 keys
# each) STILL hit the 300s timeout on Ollama even after the first halving,
# consistently and reproducibly (retested with failover disabled — same
# timeout, not a fluke) — so the "world" group specifically needed a second
# split pass that prose/voice/plot didn't.
#
# prose_samples is a single list field, so it can't be split by key the way
# voice/plot/world are — instead its group is split by REQUESTED COUNT (two
# calls, ~5-10 excerpts each), and the merge step below concatenates rather
# than overwrites when a key repeats across groups in the active plan.
SPLIT_GROUPS_10 = [
    ("prose_a", ["prose_samples"]),
    ("prose_b", ["prose_samples"]),
    ("voice_a", ["character_voice_samples", "narrative_voice_analysis"]),
    ("voice_b", ["scene_structure_patterns", "reader_psychology", "author_intent", "style_dna_refinements"]),
    ("plot_a", ["title_function", "chapter_function", "summary",
                "arc_label_suggestion", "arc_boundary_signal", "arc_notes"]),
    ("plot_b", ["facts", "timeline_events", "knowledge_state", "reveals"]),
    ("world_a", ["new_characters", "new_locations"]),
    ("world_b", ["new_factions", "new_glossary_terms"]),
    ("world_c", ["humor_instances", "scheme_instances"]),
    ("world_d", ["antagonist_template_instances", "power_curve_notes"]),
]


def _active_split_groups() -> list:
    """The 4-way plan for most engines; a 10-way plan (prose/voice/plot halved,
    world quartered) for Ollama specifically — see SPLIT_GROUPS_10's comment
    for why world needed a finer cut than the rest."""
    try:
        from llm_client import _agent_engine
        if _agent_engine() == "ollama":
            return SPLIT_GROUPS_10
        if _v4_enabled():
            return _split_groups_v4()
    except Exception:
        pass
    return SPLIT_GROUPS


def _split_enabled() -> bool:
    """Whether to split extraction across several smaller LLM calls.

    Reads generation.split_extraction from the app config (Settings checkbox),
    defaulting to ON — it measurably improves output on every engine tested.
    Turn it off to trade richness for ~4x fewer API calls per chapter.
    """
    env = os.environ.get("NM_SPLIT_EXTRACTION")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "no", "off")
    try:
        cfg_path = Path.home() / ".noveltea-engine" / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            val = (cfg.get("generation") or {}).get("split_extraction")
            if val is not None:
                return bool(val)
    except Exception:
        pass
    return True


def _v4_enabled() -> bool:
    """V4 = the V3 extraction plus the Chapter Mechanics fields (mx_*), carried by the same four split calls.
    On when generation.extraction_schema is "v4" (Settings / Corpus Builder), or NM_EXTRACTION_SCHEMA=v4 for a one-off run;
    needs split extraction, and not the 10-way Ollama plan (those chapters get mechanics from the Pipeline job instead)."""
    env = os.environ.get("NM_EXTRACTION_SCHEMA")
    try:
        if env is not None:
            want = env.strip().lower() == "v4"
        else:
            cfg_path = Path.home() / ".noveltea-engine" / "config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig")) if cfg_path.exists() else {}
            want = (cfg.get("generation") or {}).get("extraction_schema") == "v4"
        if not want or not _split_enabled():
            return False
        from llm_client import _agent_engine
        return _agent_engine() != "ollama"
    except Exception:
        return False


def _split_groups_v4() -> list:
    """SPLIT_GROUPS with each group's share of the mechanics keys appended (sizes balanced: see mechanics_core.MX_GROUP)."""
    import mechanics_core as mc
    return [(label, list(keys) + list(mc.MX_GROUP.get(label, []))) for label, keys in SPLIT_GROUPS]


_V4_CTX: dict = {}      # {"novel": id} for the chapter being extracted (extract_with_llm has no novel argument)


def _split_checkpoint_path(chapter_num: int) -> Path:
    """Where a partially-completed split extraction is parked between calls."""
    novel = _V4_CTX.get("novel", "x")
    d = Path(__file__).parent / "_split_parts" / novel      # next to the corpus (was the temp folder: lost on cleanup, and
    d.mkdir(parents=True, exist_ok=True)                    # shared by chapter NUMBER across novels)
    if _v4_enabled():           # a V3 checkpoint holds no mechanics keys: never resume one into a V4 run
        return d / f"ch{chapter_num}_v4_split.json"
    return d / f"ch{chapter_num}_split.json"


def _save_split_checkpoint(path: Path, chapter_num: int, merged: dict, done_labels: list) -> None:
    """Persist partial results atomically so an abort mid-run loses nothing.

    done_labels (group labels, not keys) is what resume/skip logic checks —
    required once two groups can target the SAME key (the 10-way Ollama plan's
    prose_a/prose_b both write prose_samples), since "is this key present"
    then no longer tells you whether both contributing calls have run."""
    try:
        payload = {
            "chapter_number": chapter_num,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fields": merged,
            "done_labels": done_labels,
        }
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:  # checkpointing must never break the extraction
        print(f"  [checkpoint] could not save: {str(e)[:80]}")


def _load_split_checkpoint(path: Path, chapter_num: int) -> tuple:
    """Restore a partial split run. Ignores a checkpoint for another chapter.
    Returns (fields, done_labels) — done_labels is [] for an old-format
    checkpoint saved before this field existed, which just means a resumed
    run re-does every group once rather than guessing at completed ones."""
    try:
        if not path.exists():
            return {}, []
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("chapter_number") != chapter_num:
            return {}, []
        fields = payload.get("fields")
        done_labels = payload.get("done_labels")
        return (dict(fields) if isinstance(fields, dict) else {},
                list(done_labels) if isinstance(done_labels, list) else [])
    except Exception:
        return {}, []


def _parse_json_response(response_text: str, label: str = "") -> dict:
    """Pull a JSON object out of an LLM response, tolerating markdown fences."""
    m = re.search(r'```json\s*\n(.*?)\n```', response_text, re.DOTALL)
    json_str = m.group(1) if m else response_text.strip()
    # Some models prepend prose despite the contract; fall back to the outermost
    # {...} span rather than discarding an otherwise good answer.
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        i, j = json_str.find("{"), json_str.rfind("}")
        if i != -1 and j > i:
            try:
                return json.loads(json_str[i:j + 1])
            except json.JSONDecodeError:
                pass
        fixed = None
        if i != -1 and j > i:
            try:
                import json_repair
                fixed = json_repair.repair(json_str[i:j + 1])      # single-quoted / unquoted values, bad keys, stray quotes, open brackets
            except Exception:
                fixed = None
            if fixed is None:
                fixed = _repair_unescaped_quotes(json_str[i:j + 1])
        if fixed is not None:
            print(f"  [json] repaired the answer's quoting/brackets{' (' + label + ')' if label else ''} - no re-ask needed")
            return fixed
    print(f"ERROR: LLM response parse failed{' (' + label + ')' if label else ''}")
    print(f"First 500 chars: {response_text[:500]}")
    _keep_bad_answer(json_str, label)
    return {}


def _keep_bad_answer(text: str, label: str):
    """Save the whole unparseable answer (and exactly where json.loads gives up) to corpus/_split_parts/_bad_answers/, so a
    failed parse can be looked at afterwards instead of guessed at from the first 500 characters."""
    try:
        try:
            json.loads(text, strict=False)
            why = "parsed on a second try"
        except json.JSONDecodeError as e:
            lo = max(0, e.pos - 120)
            why = f"{e.msg} at char {e.pos} of {len(text)}: ...{text[lo:e.pos]}<<HERE>>{text[e.pos:e.pos + 120]}..."
        d = Path(__file__).parent / "_split_parts" / "_bad_answers"
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{_V4_CTX.get('novel', 'x')}_{label or 'answer'}")[:80]
        (d / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.txt").write_text(f"WHY: {why}\n\n{text}", encoding="utf-8")
        print(f"      why it failed: {why[:260]}")
    except Exception:
        pass


def _repair_unescaped_quotes(s: str):
    """The answer parsed as JSON except for double quotes INSIDE a string value that the model forgot to escape (a quoted line
    of dialogue). A quote only closes a string when what follows it is JSON structure (, } ] :) - and a comma only counts if
    the next token could start a JSON value; any other quote inside a string is escaped. Returns the parsed object, or None
    when the result still does not parse (then the caller salvages key by key / re-asks as before). Text is never changed,
    only escaped."""
    out, in_str, i, n = [], False, 0, len(s)
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                out.append(s[i:i + 2])
                i += 2
                continue
            if c == '"':
                j = i + 1
                while j < n and s[j] in " \t\r\n":
                    j += 1
                closes = j >= n or s[j] in "}]:"
                if not closes and s[j] == ",":
                    k = j + 1
                    while k < n and s[k] in " \t\r\n":
                        k += 1
                    closes = k < n and (s[k] in '"{[-0123456789' or s.startswith(("true", "false", "null"), k))
                if closes:
                    in_str = False
                    out.append(c)
                else:
                    out.append('\\"')
            else:
                out.append(c)
        else:
            if c == '"':
                in_str = True
            out.append(c)
        i += 1
    try:
        obj = json.loads("".join(out), strict=False)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _salvage_partial(response_text: str, keys: list) -> dict:
    """Every requested top-level key whose value still parses, from an answer that does not parse as a whole (a truncated
    tail, one unescaped quote inside a quoted line). Each key is decoded on its own, so one bad value costs only itself."""
    dec, out = json.JSONDecoder(), {}
    for k in keys:
        for m in re.finditer(r'"' + re.escape(k) + r'"\s*:\s*', response_text or ""):
            try:
                out[k], _ = dec.raw_decode(response_text, m.end())
                break
            except json.JSONDecodeError:
                continue
    return out


def split_system_for(idx: int, n_groups: int, label: str, keys: list, v4: bool) -> str:
    key_list = "\n".join(f"  - {k}" for k in keys)
    # prose_a/prose_b (10-way Ollama plan only) both request prose_samples —
    # without a split hint the model tends to return near-duplicate excerpts
    # for both calls since it's the same field/instructions asked twice.
    half_hint = ""
    if label == "prose_a":
        half_hint = ("\nFor THIS call, draw your excerpts ONLY from the FIRST HALF of the "
                    "chapter text below (5-10 excerpts).")
    elif label == "prose_b":
        half_hint = ("\nFor THIS call, draw your excerpts ONLY from the SECOND HALF of the "
                    "chapter text below (5-10 excerpts) — do not repeat any moment or line "
                    "you would already have picked from the first half.")
    import mechanics_core as mc
    return (
        SYSTEM_PROMPT
        + (mc.v4_spec() if v4 else "")
        + f"\n\n─── THIS CALL ({idx}/{n_groups}: {label}) ───\n"
          f"The full schema is above for context, but for THIS response you must "
          f"return ONLY these keys:\n{key_list}\n"
          f"Return a single JSON object containing exactly (and only) those keys, "
          f"following their definitions above. Omit every other key."
          + half_hint
    )


def split_user_for(label: str, chapter_num: int, text: str, user_message: str, v4: bool, novel) -> str:
    """What one call reads. V4: the voice and plot calls get the chapter paragraph-numbered (the beat and scene ranges
    need it) and every call but prose gets the Python-measured context; the prose call keeps plain text so its
    quotes stay exact. V3 and non-V4 runs: the plain message, as always. (plot_a / plot_b of the part queue count as plot.)"""
    if not v4 or not novel:
        return user_message
    import mechanics_core as mc
    base = label.split("_")[0]
    body = user_message
    if base in mc.NUMBERED_GROUPS:
        body = f"Chapter {chapter_num} (paragraph-numbered):\n\n{mc.numbered_text(text)}"
    if base in mc.CONTEXT_GROUPS:
        try:
            body += "\n\nCONTEXT (measured by Python from the corpus; exact):\n" + mc.context_v4(novel, chapter_num, text)
        except Exception as e:
            print(f"  [mechanics] no context for the {label} call: {str(e)[:100]}")
    return body


def split_max_tokens(label: str, v4: bool) -> int:
    return 12000 if (v4 and label.split("_")[0] == "plot") else 8000


def extract_with_llm(text: str, chapter_num: int) -> dict:
    chapter_text = f"{text[:14000]}{'[... truncated ...]' if len(text) > 14000 else ''}"
    user_message = f"Chapter {chapter_num}:\n\n{chapter_text}"

    # Uses Anthropic API when a key is set, else the Claude subscription CLI.
    # required_keys lets the CLI path detect + retry thin/wrong-schema responses.
    from llm_client import call_llm

    all_keys = list(LLM_FIELDS)
    v4 = _v4_enabled()
    if v4:
        import mechanics_core as mc
        all_keys += list(mc.MX_KEYS)
        print("  - V4: Chapter Mechanics ride in the same 4 calls")

    # Split extraction is a Settings toggle (generation.split_extraction),
    # default ON. Measured same-novel: Claude single-call ch61 = 29.7 KB /
    # 3 prose_samples vs Claude 4-way ch64 = 53.9 KB / 10 prose_samples, so the
    # split is better on Claude too — but it costs 4 API calls per chapter
    # instead of 1, which is why it stays switchable.
    if not _split_enabled():
        print("  - single-call extraction (split disabled in Settings)...")
        response_text = call_llm(
            system=SYSTEM_PROMPT,
            user=user_message,
            max_tokens=16000,
            temperature=0.3,
            required_keys=all_keys,
        )
        return _parse_json_response(response_text)

    # Resume from a partial run: each group is checkpointed as soon as it lands,
    # so an abort (or a provider 503 on call 3 of 3) doesn't discard the calls
    # that already succeeded.
    active_groups = _active_split_groups()
    group_labels = [lbl for lbl, _ in active_groups]
    # Keys that more than one group in the ACTIVE plan is responsible for (only
    # happens on the 10-way Ollama plan: prose_a + prose_b both write
    # prose_samples) — these must be concatenated across contributing calls,
    # never overwritten, or the second call's results silently replace the first's.
    key_owner_count: dict = {}
    for _, ks in active_groups:
        for k in ks:
            key_owner_count[k] = key_owner_count.get(k, 0) + 1
    shared_keys = {k for k, n in key_owner_count.items() if n > 1}

    ckpt_path = _split_checkpoint_path(chapter_num)
    merged, done_labels = _load_split_checkpoint(ckpt_path, chapter_num)
    if "plot_a" in done_labels and "plot_b" in done_labels and "plot" not in done_labels:
        done_labels = done_labels + ["plot"]                      # both halves of the part queue's plot are in: plot is done
    if "voice_a" in done_labels and "voice_b" in done_labels and "voice" not in done_labels:
        done_labels = done_labels + ["voice"]                     # both halves of the part queue's voice are in: voice is done
    done_labels = [l for l in done_labels if l in group_labels]   # drop stale labels from a different plan
    stats: list = []   # (label, filled, requested, seconds, bytes) per call
    if done_labels:
        print(f"  - resuming from checkpoint: {', '.join(done_labels)} already extracted")

    def _split_system_for(idx, label, keys):
        return split_system_for(idx, len(active_groups), label, keys, v4)

    def _user_for(label):
        return split_user_for(label, chapter_num, text, user_message, v4, _V4_CTX.get("novel"))

    def _max_tokens_for(label):
        return split_max_tokens(label, v4)

    # Nvidia only: with several pooled keys, the groups still to do run AT THE SAME TIME, each pinned to its own key
    # (llm_client.pin_nemotron_slot), then flow through the same ordered merge / checkpoint loop below. Any other
    # engine, or a one-key pool, keeps the original one-after-another behaviour. A failed group is re-raised at its own
    # turn in the loop, after the groups before it have been merged and checkpointed.
    prefetched: dict = {}
    pending = [(i, l, k) for i, (l, k) in enumerate(active_groups, 1) if l not in done_labels]
    try:
        from llm_client import nemotron_parallel_slots, pin_nemotron_slot, unpin_nemotron_slot
        workers = nemotron_parallel_slots(len(pending))
    except Exception:
        workers = 1
    if workers > 1 and len(pending) > 1:
        from concurrent.futures import ThreadPoolExecutor

        def _prefetch(slot, idx, label, keys):
            pin_nemotron_slot(slot)
            t1 = time.time()
            try:
                print(f"  [{idx}/{len(active_groups)}] {label}: requesting {len(keys)} fields on key slot {slot + 1}")
                return call_llm(system=_split_system_for(idx, label, keys), user=_user_for(label),
                                max_tokens=_max_tokens_for(label), temperature=0.3, required_keys=keys), time.time() - t1
            except Exception as e:
                return e, time.time() - t1
            finally:
                unpin_nemotron_slot()
        print(f"  - {len(pending)} split calls in parallel on {workers} Nvidia key(s)...")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {l: pool.submit(_prefetch, n, i, l, k) for n, (i, l, k) in enumerate(pending)}
            for l, f in futs.items():
                prefetched[l] = f.result()

    first_failure = None
    for idx, (label, keys) in enumerate(active_groups, 1):
        if label in done_labels:
            print(f"  - split extraction {idx}/{len(active_groups)} ({label}): cached, skipping")
            continue

        split_system = _split_system_for(idx, label, keys)
        t0 = time.time()
        if label in prefetched:
            response_text, took = prefetched[label]
            t0 = time.time() - took                      # report the call's own duration
            if isinstance(response_text, Exception):
                # parallel mode: the other groups' answers are already paid for, so keep merging + checkpointing them
                # and raise this failure after the loop (a re-run resumes from the checkpoint)
                print(f"  [{idx}/{len(active_groups)}] {label}: FAILED after {took:.0f}s "
                      f"— {str(response_text)[:120]}")
                first_failure = first_failure or response_text
                continue
        else:
            print(f"  [{idx}/{len(active_groups)}] {label}: requesting {len(keys)} fields "
                  f"({', '.join(keys[:4])}{'…' if len(keys) > 4 else ''})")
            try:
                response_text = call_llm(
                    system=split_system,
                    user=_user_for(label),
                    max_tokens=_max_tokens_for(label),
                    temperature=0.3,
                    required_keys=keys,
                )
            except Exception as e:
                # Keep what we have so a retry resumes instead of restarting.
                _save_split_checkpoint(ckpt_path, chapter_num, merged, done_labels)
                done_n = sum(1 for k in all_keys if k in merged)
                print(f"  [{idx}/{len(active_groups)}] {label}: FAILED after {time.time()-t0:.0f}s "
                      f"— {str(e)[:120]}")
                print(f"      checkpoint saved ({done_n}/{len(all_keys)} fields kept) — "
                      f"re-run this chapter to resume from here")
                raise

        elapsed = time.time() - t0
        part = _parse_json_response(response_text, label)
        if v4:
            if not part:                                   # the answer as a whole did not parse: keep every key that did
                part = _salvage_partial(response_text, keys)
                if part:
                    print(f"      salvaged {len(part)}/{len(keys)} keys from an unparseable {label} answer")
            lost = [k for k in keys if k not in part]
            if lost:                                       # one targeted retry for just the lost keys
                print(f"      {label}: re-asking for {len(lost)} lost key(s): {', '.join(lost)}")
                try:
                    again = call_llm(
                        system=split_system.replace("return ONLY these keys:", "return ONLY these keys (an earlier answer was "
                                                    "not valid JSON: escape every double quote inside a string as backslash-quote):", 1),
                        user=_user_for(label) + "\n\nReturn ONLY these keys, as one valid JSON object: " + ", ".join(lost),
                        max_tokens=_max_tokens_for(label), temperature=0.2, required_keys=lost)
                    got = _parse_json_response(again, label + " retry") or _salvage_partial(again, lost)
                    part.update({k: v for k, v in got.items() if k in lost})
                except Exception as e:
                    print(f"      {label}: retry failed — {str(e)[:100]}")
        # Keep only the keys this pass was responsible for, so a model that
        # re-emits earlier fields (often thinner) can't overwrite good data.
        # A key owned by more than one group in the active plan is CONCATENATED
        # (list) or MERGED (dict) across contributing calls instead of overwritten.
        for k in keys:
            if k not in part:
                continue
            if k in shared_keys and k in merged:
                existing = merged[k]
                if isinstance(existing, list) and isinstance(part[k], list):
                    merged[k] = existing + part[k]
                elif isinstance(existing, dict) and isinstance(part[k], dict):
                    merged[k] = {**existing, **part[k]}
                else:
                    merged[k] = part[k]   # incompatible types — last call wins, same as before
            else:
                merged[k] = part[k]
        done_labels.append(label)
        _save_split_checkpoint(ckpt_path, chapter_num, merged, done_labels)

        # Per-call report: which fields actually came back, and how big.
        filled = [k for k in keys if merged.get(k) not in (None, "", [], {})]
        blank = [k for k in keys if k not in filled]
        size = len(json.dumps({k: merged.get(k) for k in filled}, ensure_ascii=False))
        counts = ", ".join(
            f"{k}={len(merged[k])}" for k in filled
            if isinstance(merged.get(k), (list, dict))
        )
        print(f"  [{idx}/{len(active_groups)}] {label}: {len(filled)}/{len(keys)} filled "
              f"in {elapsed:.0f}s, {size:,} bytes"
              + (f" ({counts})" if counts else ""))
        if blank:
            print(f"      empty: {', '.join(blank)}")
        stats.append((label, len(filled), len(keys), elapsed, size))

    if first_failure is not None:
        _save_split_checkpoint(ckpt_path, chapter_num, merged, done_labels)
        done_n = sum(1 for k in all_keys if k in merged)
        print(f"      checkpoint saved ({done_n}/{len(all_keys)} fields kept) — re-run this chapter to resume from here")
        raise first_failure

    got = sum(1 for k in all_keys if merged.get(k) not in (None, "", [], {}))
    total_bytes = len(json.dumps(merged, ensure_ascii=False))
    total_time = sum(s[3] for s in stats)
    # ASCII only: this streams to a Windows console that defaults to cp1252,
    # where box-drawing characters raise UnicodeEncodeError and kill the run.
    print(f"  == split summary: {got}/{len(all_keys)} fields, {total_bytes:,} bytes, "
          f"{len(stats)} call(s) in {total_time:.0f}s ==")
    for label, f, t, el, sz in stats:
        share = (sz / total_bytes * 100) if total_bytes else 0
        print(f"      {label:<7} {f}/{t} fields  {el:5.0f}s  {sz:>7,} B  {share:4.1f}%")
    still_empty = [k for k in all_keys if merged.get(k) in (None, "", [], {})]
    if still_empty:
        print(f"      still empty: {', '.join(still_empty)}")
    # Full delta is about to be saved by the caller; the checkpoint is spent.
    try:
        if ckpt_path.exists():
            ckpt_path.unlink()
    except OSError:
        pass
    return merged


def merge_style_dna(base: dict, refinements: dict) -> dict:
    result = base.copy()

    cr = refinements.get("content_ratios", {})
    if cr:
        result["content_ratios"].update(cr)

    pm = refinements.get("pacing_markers", {})
    if pm:
        result["pacing_markers"].update(pm)

    sd = refinements.get("stylistic_devices", {})
    if sd:
        result["stylistic_devices"].update(sd)

    vm = refinements.get("vocabulary_markers", {})
    if vm:
        for key in ["favorite_intensifiers", "favorite_descriptors_power", "favorite_descriptors_emotion"]:
            if key in vm:
                result["vocabulary_markers"][key] = vm[key]

    if "character_catchphrases" in refinements:
        result["character_catchphrases"] = refinements["character_catchphrases"]

    if "distinctive_style_markers" in refinements:
        result["distinctive_style_markers"] = refinements["distinctive_style_markers"]

    return result


def extract_chapter_v3(novel_id: str, chapter_num: int) -> dict:
    print(f"[v3] Extracting chapter {chapter_num} for {novel_id}...")

    text = load_chapter_text(novel_id, chapter_num)

    print("  - Programmatic style analysis...")
    style_dna_base = analyze_style_dna(text)

    print("  - LLM full extraction (plot + style)...")
    _V4_CTX["novel"] = novel_id
    llm = extract_with_llm(text, chapter_num)
    return delta_from_llm(novel_id, chapter_num, text, llm, style_dna_base)


def delta_from_llm(novel_id: str, chapter_num: int, text: str, llm: dict, style_dna_base: dict) -> dict:
    """Everything after the model calls: the merged answers -> one validated delta. Shared by the one-chapter path above and
    the parallel part queue (extract_queue.py), which assembles a chapter the moment its last part lands."""
    if "mx_scene_joins" in llm:        # V4: how each scene joins the one before, folded into the one scene list
        import mechanics_core as mc
        joined = mc.merge_scene_joins(llm)
        print(f"  - scene joins: {joined} of {len((llm.get('scene_structure_patterns') or {}).get('scenes') or [])} scenes")
        try:                      # exact word counts from each scene's paragraph range (the model only estimated them)
            paras = mc.paragraphs(text)
            for sc in (llm.get("scene_structure_patterns") or {}).get("scenes") or []:
                pr = sc.get("paras")
                if isinstance(pr, list) and len(pr) == 2 and all(isinstance(x, int) for x in pr) and 1 <= pr[0] <= pr[1] <= len(paras):
                    sc["estimated_word_count"] = sum(len(p.split()) for p in paras[pr[0] - 1:pr[1]])
        except Exception as e:
            print(f"  [scenes] word counts left as estimated: {str(e)[:80]}")

    # "none" answers -> real empty values + a record of what was confirmed absent,
    # so the validation round doesn't repair fields the model already ruled on.
    confirmed_empty = normalize_none_sentinels(llm)
    if confirmed_empty:
        print(f"  - confirmed absent: {', '.join(sorted(confirmed_empty))}")

    style_dna = merge_style_dna(style_dna_base, llm.get("style_dna_refinements", {}))

    # Extract chapter title from text if LLM didn't provide one
    # The title is the chapter's own first line - Python reads it exactly; the model's guess is only a fallback.
    chapter_title = ""
    m = re.search(r'Chapter \d+\s*[–\-:]\s*(.+)', text.split('\n')[0])
    if m:
        chapter_title = m.group(1).strip()
    if not chapter_title:
        chapter_title = llm.get("chapter_title", "")

    delta = {
        "schema_version": "3.0",
        "chapter_number": chapter_num,
        "chapter_title":  chapter_title,
        "title_function":       llm.get("title_function", "none"),
        "chapter_function":     llm.get("chapter_function", "setup"),
        "summary":              llm.get("summary", ""),
        "arc_label_suggestion": llm.get("arc_label_suggestion", ""),
        "arc_boundary_signal":  llm.get("arc_boundary_signal", False),
        "arc_notes":            llm.get("arc_notes", ""),
        "merge_notes":          {},

        "new_characters":     llm.get("new_characters", []),
        "new_locations":      llm.get("new_locations", []),
        "new_factions":       llm.get("new_factions", []),
        "new_glossary_terms": llm.get("new_glossary_terms", []),

        "facts":            llm.get("facts", []),
        "timeline_events":  llm.get("timeline_events", []),
        "humor_instances":  llm.get("humor_instances", []),
        "scheme_instances": llm.get("scheme_instances", []),
        "knowledge_state":  llm.get("knowledge_state", []),
        "antagonist_template_instances": llm.get("antagonist_template_instances", []),
        "power_curve_notes": llm.get("power_curve_notes", None),
        "reveals":           llm.get("reveals", []),

        "reader_psychology": llm.get("reader_psychology", {}),
        "author_intent":     llm.get("author_intent", {}),

        "prose_samples":            llm.get("prose_samples", []),
        "style_dna":                style_dna,
        "character_voice_samples":  llm.get("character_voice_samples", []),
        "scene_structure_patterns": llm.get("scene_structure_patterns", {}),
        "narrative_voice_analysis": llm.get("narrative_voice_analysis", {}),

        "novel_metadata_hints": {
            "alt_titles": [],
            "translator_notes": [],
            "genre_signals": []
        },

        # Fields the model inspected and confirmed genuinely absent from this
        # chapter. Distinguishes "nothing to extract" from "never extracted",
        # so validation doesn't repair-loop on them. Ignored by merge.py.
        "confirmed_empty": sorted(confirmed_empty),
    }

    # V4: the mechanics answers (mx_*) of the four calls -> one validated record inside the delta
    if any(k in llm for k in ("mx_beats", "mx_cast", "mx_run", "mx_chapter_type")):
        try:
            import mechanics_core as mc
            import delta_audit
            pv = delta_audit.current_engine_model()
            rec = mc.assemble_v4(llm, text, novel_id, chapter_num, pv.get("engine"), pv.get("model"))
        except Exception as e:
            rec = None
            print(f"  [mechanics] skipped: {str(e)[:120]}")
        if rec and rec.get("beats"):
            # a snapshot of the scenes WITH their joins travels inside mechanics: Delta Upgrade re-asks scene_structure_patterns
            # (without joins) and must not be able to take the joins with it
            rec["scenes"] = mc.scenes_of(delta)
            delta["mechanics"] = dict(rec)
            delta["schema_version"] = "4.0"
            print(f"  - mechanics: {len(rec['beats'])} beats, {len(rec.get('cast') or [])} cast, {len(rec.get('fights') or [])} fight(s)")
        else:
            print("  - mechanics: the model returned none (the Pipeline job can fill this chapter later)")

    return delta


def normalize_scales(delta: dict) -> list:
    """Force reader_psychology scores onto their documented scales.

    The prompt has always said "0-10", but the model does not always obey: one
    novel in the corpus (my_novel) scored emotions 0-100, producing values
    like comedy=100. Averaging those against every other novel's 0-10 scores
    yielded nonsense ("comedy 99/10") in anything that aggregates this field.

    A prompt instruction alone was not enough, so this clamps at the single
    choke point every extraction passes through. Returns a list of the
    corrections made so the caller can report them.
    """
    fixes = []
    rp = delta.get("reader_psychology")
    if not isinstance(rp, dict):
        return fixes

    # reader_emotions / payoff_categories are 0-10.
    for section in ("reader_emotions", "payoff_categories"):
        block = rp.get(section)
        if not isinstance(block, dict):
            continue
        for k, v in list(block.items()):
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                continue
            if v > 10:
                # A 0-100 score divides cleanly; anything else is clamped.
                new = round(v / 10) if v <= 100 else 10
                block[k] = max(0, min(10, new))
                fixes.append(f"{section}.{k}: {v} -> {block[k]}")
            elif v < 0:
                block[k] = 0
                fixes.append(f"{section}.{k}: {v} -> 0")

    # tension_curve is 0-100.
    tc = rp.get("tension_curve")
    if isinstance(tc, dict):
        for k in ("start", "peak", "end"):
            v = tc.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if v > 100 or v < 0:
                    tc[k] = max(0, min(100, round(v)))
                    fixes.append(f"tension_curve.{k}: {v} -> {tc[k]}")
    return fixes


def save_delta(delta: dict, novel_id: str):
    chapter_num = delta["chapter_number"]
    # Normalise before writing so no out-of-scale value ever reaches disk.
    fixes = normalize_scales(delta)
    if fixes:
        print(f"  [scale] normalised {len(fixes)} out-of-range score(s): {'; '.join(fixes[:4])}")
    output_path = Path("novels") / novel_id / "deltas_v3" / f"ch{chapter_num}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if "mechanics" not in delta and output_path.exists():
        # a rewrite that did not re-ask for the mechanics (Delta Upgrade, a repair, a V3 re-extraction) must not drop them
        try:
            prev = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(prev, dict) and prev.get("mechanics"):
                delta = {"schema_version": "4.0", **{k: v for k, v in delta.items() if k != "schema_version"},
                         "mechanics": prev["mechanics"]}
        except Exception:
            pass
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(delta, f, indent=2, ensure_ascii=False)
    print(f"  [OK] {output_path}")
    # Leave a mark in delta_quality.json: this chapter's richness score, flags, and which engine/model
    # produced it — so later "which chapters could be upgraded?" needs no re-reading. Must never be able
    # to break an extraction, hence the blanket except.
    try:
        import delta_audit
        delta_audit.mark_chapter(novel_id, chapter_num, delta)
    except Exception:
        pass


# Fields that come from the LLM (vs. the programmatic style pass). Only these can
# be "empty and need repair"; style_dna / schema_version / etc. are never repaired.
LLM_FIELDS = [
    "title_function", "chapter_function", "summary",
    "arc_label_suggestion", "arc_boundary_signal", "arc_notes",
    "new_characters", "new_locations", "new_factions", "new_glossary_terms",
    "facts", "timeline_events", "humor_instances", "scheme_instances",
    "knowledge_state", "antagonist_template_instances", "power_curve_notes",
    "reveals", "reader_psychology", "author_intent", "prose_samples",
    "character_voice_samples", "scene_structure_patterns", "narrative_voice_analysis",
    "style_dna_refinements",
]

# Fields that are legitimately allowed to be empty on many chapters (don't flag them)
# No-gaps policy: nothing is excused from repair. Previously this excused
# character_voice_samples / power_curve_notes / antagonist_template_instances
# and others, so they were never re-requested no matter how many chapters
# came back empty.
#
# A chapter genuinely may not contain e.g. humour or a new faction. The repair
# pass asks for those fields once; if the model returns empty again, the delta
# is accepted rather than looping forever (see repair_chapter_fields).
OPTIONAL_FIELDS = set()


def _empty(v):
    return v in (None, "", [], {})


# ── Confirmed-absent sentinel ────────────────────────────────────────────────
# A chapter genuinely may contain no scheming, no new faction, no antagonist
# template. Previously that was indistinguishable from "the model never filled
# this in", so the no-gaps policy re-requested such fields forever: targeted
# repair x2 then a full re-extract, all to re-derive the same empty list.
#
# The model may now answer "none" (or {"none": true}) for any collection field
# it inspected and found genuinely absent. We normalise that back to the real
# empty value — merge.py still sees [] / {} / null and needs no changes — and
# record the key in delta["confirmed_empty"], which the quality checks treat as
# satisfied. Absence becomes an assertion instead of a silence.
CONFIRMABLE_EMPTY_FIELDS = {
    "new_characters", "new_locations", "new_factions", "new_glossary_terms",
    "facts", "timeline_events", "humor_instances", "scheme_instances",
    "knowledge_state", "antagonist_template_instances", "power_curve_notes",
    "reveals", "prose_samples", "character_voice_samples",
}

_NONE_TOKENS = {"none", "n/a", "na", "null", "nothing", "no", "[]"}


def _is_none_sentinel(v) -> bool:
    """True if the model explicitly asserted 'nothing of this kind here'."""
    if isinstance(v, str):
        return v.strip().strip('."').lower() in _NONE_TOKENS
    if isinstance(v, dict):
        return v.get("none") is True
    # ["none"] — a model wrapping the sentinel in the array shape it was given
    if isinstance(v, list) and len(v) == 1:
        return _is_none_sentinel(v[0])
    return False


def _empty_value_for(key: str):
    """The real empty value a confirmed-absent field collapses to."""
    if key == "power_curve_notes":
        return None
    return []


def normalize_none_sentinels(data: dict) -> list:
    """Replace 'none' sentinels with real empty values, in place.

    Returns the list of keys the model confirmed as genuinely absent.
    """
    confirmed = []
    for k in CONFIRMABLE_EMPTY_FIELDS:
        if k in data and _is_none_sentinel(data[k]):
            data[k] = _empty_value_for(k)
            confirmed.append(k)
    return confirmed


def _poor_quality(key: str, value, chapter_text: str = "") -> bool:
    """Heuristics for a field that is present but a POOR extraction — worth repairing.
    Conservative: only flags clear signs of a weak/degenerate extraction."""
    if _empty(value):
        return False  # emptiness handled separately
    # A summary that's too short for a full chapter is almost always a bad extraction.
    if key == "summary":
        return len(str(value).strip()) < 60
    # reader_psychology / author_intent should be structured objects with real content.
    if key in ("reader_psychology", "author_intent"):
        if isinstance(value, dict):
            filled = sum(1 for v in value.values() if not _empty(v))
            return filled < 2
        return len(str(value).strip()) < 40
    # narrative_voice_analysis / scene_structure_patterns: dicts that shouldn't be near-empty
    if key in ("narrative_voice_analysis", "scene_structure_patterns"):
        if isinstance(value, dict):
            return sum(1 for v in value.values() if not _empty(v)) < 1
    # List fields: for an event-dense chapter, having exactly 0-1 items is suspicious
    # for the core narrative lists (but only when the chapter clearly has content).
    if key in ("facts", "reveals", "timeline_events") and isinstance(value, list):
        if chapter_text and len(chapter_text) > 3000 and len(value) == 0:
            return True
    return False


def missing_llm_fields(delta: dict, chapter_text: str = "") -> list:
    """Return LLM fields that are EMPTY (required) OR present-but-poor-quality.

    Fields the model explicitly confirmed as absent (see normalize_none_sentinels)
    are NOT reported missing — re-asking would just re-derive the same empty."""
    confirmed = set(delta.get("confirmed_empty") or [])
    out = []
    for k in LLM_FIELDS:
        v = delta.get(k)
        if _empty(v):
            if k not in OPTIONAL_FIELDS and k not in confirmed:
                out.append(k)
        elif _poor_quality(k, v, chapter_text):
            out.append(k)
    return out


def repair_chapter_fields(novel_id: str, chapter_num: int, fields: list) -> dict:
    """TARGETED repair: re-request ONLY the given empty fields from the LLM and
    merge them into the existing delta. Does NOT redo style analysis or the whole
    schema — much cheaper/faster than a full re-extraction."""
    delta_path = Path("novels") / novel_id / "deltas_v3" / f"ch{chapter_num}.json"
    if not delta_path.exists():
        raise FileNotFoundError(f"No delta to repair: {delta_path}")
    with open(delta_path, encoding="utf-8") as f:
        delta = json.load(f)

    text = load_chapter_text(novel_id, chapter_num)

    if not fields:
        fields = missing_llm_fields(delta, text)   # empty OR poor-quality
    if not fields:
        print(f"  [repair] ch{chapter_num}: nothing to repair")
        return delta
    print(f"  [repair] ch{chapter_num}: requesting {len(fields)} field(s): {', '.join(fields)}")

    # A focused prompt asking ONLY for the missing fields, reusing the full schema
    # description so the model knows each field's shape.
    field_spec = "\n".join(f"- {k}" for k in fields)
    repair_system = (
        "You are repairing specific missing fields in a web-novel chapter extraction. "
        "The full field definitions are below; produce values ONLY for the requested keys, "
        "following those definitions exactly.\n\n" + SYSTEM_PROMPT
    )
    repair_user = (
        f"Chapter {chapter_num}:\n\n{text[:14000]}"
        f"{'[... truncated ...]' if len(text) > 14000 else ''}\n\n"
        f"Extract ONLY these keys from the chapter above and return a JSON object "
        f"containing exactly (and only) these keys:\n{field_spec}"
    )

    from llm_client import call_llm
    # No explicit model: an id hardcoded here would override the CLI Model
    # picked in Settings, and would be flat wrong on a non-Claude engine.
    raw = call_llm(system=repair_system, user=repair_user,
                   max_tokens=8000, temperature=0.3,
                   required_keys=fields)

    # Parse and merge only the requested fields
    m = re.search(r'```json\s*\n(.*?)\n```', raw, re.DOTALL)
    js = m.group(1) if m else raw.strip()
    try:
        patch = json.loads(js)
    except json.JSONDecodeError:
        print(f"  [repair] ch{chapter_num}: repair response unparseable, leaving delta unchanged")
        return delta

    # A "none" answer is a real result: the model looked and found nothing.
    # Record it so this field is never re-requested for this chapter again.
    newly_confirmed = normalize_none_sentinels(patch)

    repaired = []
    for k in fields:
        if k in patch and not _empty(patch[k]):
            # style_dna_refinements isn't a top-level delta key — it's a patch
            # ONTO delta["style_dna"] (see merge_style_dna), same as the main
            # extraction path does. Writing it to delta["style_dna_refinements"]
            # directly would leave the actual content_ratios/pacing_markers/etc.
            # still zeroed and add a dead, never-read key alongside them.
            if k == "style_dna_refinements":
                delta["style_dna"] = merge_style_dna(delta.get("style_dna") or {}, patch[k])
            else:
                delta[k] = patch[k]
            repaired.append(k)

    # Fields the repair was asked for that came back empty with no explicit
    # sentinel are ALSO treated as confirmed absent: the model was pointed
    # straight at them and still produced nothing, which is an answer. Without
    # this, a model that just omits the key loops until the full re-extract.
    for k in fields:
        if k in CONFIRMABLE_EMPTY_FIELDS and k not in repaired:
            if k not in newly_confirmed:
                newly_confirmed.append(k)
            delta.setdefault(k, _empty_value_for(k))

    if newly_confirmed:
        prev = set(delta.get("confirmed_empty") or [])
        delta["confirmed_empty"] = sorted(prev | set(newly_confirmed))

    print(f"  [repair] ch{chapter_num}: filled {len(repaired)}/{len(fields)} — {', '.join(repaired) or 'none'}"
          + (f"; confirmed absent: {', '.join(sorted(newly_confirmed))}" if newly_confirmed else ""))
    save_delta(delta, novel_id)
    return delta


def main():
    parser = argparse.ArgumentParser(description="NovelTea Engine v3 schema extraction")
    parser.add_argument("--novel",   required=True, help="Novel ID")
    parser.add_argument("--chapter", type=int, help="Single chapter")
    parser.add_argument("--start",   type=int, help="Batch start chapter")
    parser.add_argument("--end",     type=int, help="Batch end chapter")
    parser.add_argument("--repair",  action="store_true",
                        help="Targeted repair: re-request only empty LLM fields and merge them, "
                             "instead of re-extracting the whole chapter.")
    parser.add_argument("--fields",  help="Comma-separated field names to repair (with --repair). "
                                          "Default: auto-detect empty required fields.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Batch mode: skip chapters that already have a non-trivial delta "
                             "(lets an interrupted range re-run without re-extracting done work; "
                             "the validation round still repairs poor-quality deltas).")
    args = parser.parse_args()

    # ── Targeted repair mode ──
    if args.repair:
        want = [f.strip() for f in args.fields.split(",")] if args.fields else None
        chapters = ([args.chapter] if args.chapter
                    else list(range(args.start, args.end + 1)) if args.start and args.end
                    else [])
        if not chapters:
            print("Error: --repair needs --chapter N or --start N --end N")
            sys.exit(1)
        for ch in chapters:
            try:
                repair_chapter_fields(args.novel, ch, want)
            except FileNotFoundError as e:
                print(f"[SKIP] {e}")
            except Exception as e:
                print(f"[REPAIR ERROR] Ch{ch}: {str(e)[:120]}")
        return

    if args.chapter:
        delta = extract_chapter_v3(args.novel, args.chapter)
        save_delta(delta, args.novel)
    elif args.start and args.end:
        # Nvidia with several pooled keys: the whole range is one shared queue of (chapter, part) tasks, so a free agent
        # never waits for another chapter's slowest part (see extract_queue.py). Anything else keeps the loop below.
        try:
            import extract_queue
            use_queue = extract_queue.eligible()
        except Exception as e:
            print(f"[queue] not available ({str(e)[:80]}) - extracting one chapter at a time")
            use_queue = False
        if use_queue:
            res = extract_queue.run_range(args.novel, list(range(args.start, args.end + 1)), skip_existing=args.skip_existing)
            print(f"[queue] done: {len(res['ok'])} saved, {len(res['failed'])} failed {res['failed'] or ''}, {len(res['skipped'])} skipped")
            return
        for ch in range(args.start, args.end + 1):
            if args.skip_existing:
                dp = Path("novels") / args.novel / "deltas_v3" / f"ch{ch}.json"
                try:
                    if dp.exists() and dp.stat().st_size > 500:
                        print(f"[SKIP] Ch{ch}: delta already exists ({dp.stat().st_size} bytes)")
                        continue
                except OSError:
                    pass
            try:
                delta = extract_chapter_v3(args.novel, ch)
                save_delta(delta, args.novel)
                time.sleep(0.5)
            except FileNotFoundError as e:
                print(f"[SKIP] {e}")
            except Exception as e:
                print(f"[ERROR] Ch{ch}: {str(e)[:120]}")
                if "rate_limit" in str(e).lower():
                    print("[RATE LIMIT] Waiting 60s...")
                    time.sleep(60)
    else:
        print("Error: specify --chapter N or --start N --end N")
        sys.exit(1)


if __name__ == "__main__":
    main()
