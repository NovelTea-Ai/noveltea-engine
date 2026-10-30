# NovelTea Engine Delta Schema v3.0

**Supersedes**: SCHEMA.md (v2.0) and SCHEMA_V2.1_GENERATION.md (v2.1)  
**Purpose**: Unified schema combining v2.0 narrative/plot intelligence with v2.1 style/generation DNA. Every field from both versions is present. Nothing is dropped.

---

## Top-Level Structure

```json
{
  "schema_version": "3.0",

  "chapter_number": 0,
  "chapter_title": "string",
  "title_function": "foreshadow | payoff_callback | thematic_statement | introduction | none",
  "chapter_function": "setup | escalation | payoff | climax | resolution | transition | hook | cooldown | arc_finale | reveal | training_interlude | worldbuilding | twist",
  "summary": "string — 2-5 sentences covering all major events",
  "arc_label_suggestion": "string — e.g. 'Arc 3: Black Sect Power Struggle'",
  "arc_boundary_signal": false,
  "arc_notes": "string — optional commentary on arc rhythm, pacing role of this chapter",
  "merge_notes": {},

  "new_characters": [ ],
  "new_locations":  [ ],
  "new_factions":   [ ],
  "new_glossary_terms": [ ],

  "facts":              [ ],
  "timeline_events":    [ ],
  "humor_instances":    [ ],
  "scheme_instances":   [ ],
  "knowledge_state":    [ ],
  "antagonist_template_instances": [ ],
  "power_curve_notes":  { },
  "reveals":            [ ],

  "reader_psychology":  { },
  "author_intent":      { },

  "prose_samples":           [ ],
  "style_dna":               { },
  "character_voice_samples": [ ],
  "scene_structure_patterns": { },
  "narrative_voice_analysis": { },

  "novel_metadata_hints": { }
}
```

---

## Section 1 — Entity Declarations

### `new_characters`
```json
{
  "name": "string — canonical name",
  "aliases": ["string"],
  "type": "character",
  "role": "protagonist | antagonist | supporting | minor_antagonist | minor_supporting",
  "comedic_role": "straight_man | gag_character | deadpan_snarker | comic_relief | running_gag_target | none",
  "description": "string — appearance, personality, key traits on introduction",
  "notes": "string — resolution hints for merge.py, e.g. 'Resolves OldName (ch.N) -> full name NewName'"
}
```

### `new_locations`
```json
{
  "name": "string",
  "type": "location",
  "description": "string — what it is and its significance",
  "notes": "string — optional"
}
```

### `new_factions`
```json
{
  "name": "string",
  "type": "faction",
  "description": "string",
  "notes": "string — optional"
}
```

---

## Section 2 — Glossary

```json
{
  "term": "string",
  "definition": "string — in-world meaning AND mechanical implications if any",
  "category": "cultivation_realm | cultivation_concept | skill | stat | item | location | class | power_system | world_event | system_mechanic | other",
  "chapter_introduced": 0
}
```

---

## Section 3 — Facts

```json
{
  "subject": "entity canonical name",
  "predicate": "controlled vocabulary — see below",
  "object": "entity canonical name OR literal string",
  "object_type": "entity | literal",
  "source_chapter": 0,
  "status": "active | superseded",
  "notes": "string — optional",
  "spoiler_note": "string — optional, forward-looking implications"
}
```

**Predicate vocabulary:**
- Identity/relationships: `has_alias`, `family_of`, `member_of`, `leads`, `ally_of`, `enemy_of`, `romantic_with`
- Character: `has_appearance_trait`, `has_personality_trait`, `has_ability`, `has_power_rank`, `has_reputation`, `wants`
- Location/world: `located_in`, `born_in`, `controls`, `owns`, `has_attribute`
- Events: `occurred_at_location`, `occurred_to_character`

**Single-valued predicates** (`has_power_rank`, `has_reputation`): new active fact auto-supersedes prior active fact for same subject.  
**Symmetric predicates** (`ally_of`, `enemy_of`, `romantic_with`): mirrored onto object entity. `ally_of` and `enemy_of` are mutually exclusive per pair.

---

## Section 4 — Timeline Events

```json
{
  "event": "string — one concrete sentence",
  "order": 0,
  "source_chapter": 0,
  "stakes": "string — optional, what was at risk if this went differently",
  "spoiler_note": "string — optional, forward-looking implication"
}
```

---

## Section 5 — Humor Instances

```json
{
  "type": "deadpan_reaction | situational_irony | character_dynamic | running_gag | subverted_trope | escalation_gag | fish_out_of_water",
  "participants": ["entity canonical name"],
  "setup": "string",
  "payoff": "string",
  "tone_tags": ["deadpan", "dark_comedy", "dramatic_irony", "schadenfreude", "absurdist", "reversal", "wordplay", "running_gag", "callback"],
  "source_chapter": 0,
  "recurrence": "one-off | running_gag | callback",
  "callback_to": "string — optional, description of earlier instance this pays off",
  "example_text": "string — optional, verbatim quote <=2 sentences"
}
```

---

## Section 6 — Scheme Instances

```json
{
  "schemer": "entity canonical name",
  "target": "entity canonical name",
  "goal": "string",
  "mechanism": "string — how the scheme works",
  "setup_chapter": 0,
  "execution_chapter": 0,
  "payoff_chapter": 0,
  "status": "ongoing | succeeded | failed | discovered",
  "victim_aware": false,
  "stakes": "string — consequence if discovered or failed",
  "tags": ["manipulation", "public_trap", "staged_reveal", "third_party_witness", "long_con"],
  "linked_humor_id": "string — optional"
}
```

Re-emit with same `schemer`+`target`+`goal` key when updating status across chapters.

---

## Section 7 — Knowledge State (Dramatic Irony)

```json
{
  "fact": "string — the piece of information",
  "known_to": ["reader", "entity canonical name"],
  "hidden_from": ["entity canonical name"],
  "hidden_from_notes": "string — optional nuance",
  "established_chapter": 0,
  "resolved_chapter": null,
  "resolution": "string — optional, how the gap closes"
}
```

---

## Section 8 — Antagonist Template Instances

```json
{
  "template_id": "string — slug reused across instances, e.g. 'underestimating_challenger'",
  "pattern": "string — the generic arc shape",
  "instance_entity": "entity canonical name",
  "instance_chapters": [0, 0],
  "variation_notes": "string — how this instance differs from prior ones (escalation, twist)"
}
```

---

## Section 9 — Power Curve Notes

Only emit on chapters with a power-progression event.

```json
{
  "chapter_range": [0, 0],
  "pattern": "string — pacing/cost/justification shape of this progression",
  "implies_for_future": "string — what this suggests about future pacing to avoid repetition"
}
```

---

## Section 10 — Reveals

```json
{
  "reveal_type": "power_reveal | identity_reveal | relationship_reveal | conspiracy_reveal | world_reveal | betrayal_reveal | secret_goal_reveal | ability_reveal",
  "content": "string — what was revealed",
  "setup_chapters": [0],
  "payoff_chapter": 0,
  "revealed_to": ["reader", "entity canonical name"],
  "hidden_from_until_now": ["entity canonical name"],
  "impact": "string — how this changes story dynamics"
}
```

---

## Section 11 — Reader Psychology

```json
{
  "reader_emotions": {
    "awe": 0, "satisfaction": 0, "anticipation": 0, "curiosity": 0,
    "fear": 0, "tension": 0, "comedy": 0, "sadness": 0, "disgust": 0
  },
  "payoff_categories": {
    "power_fantasy": 0, "justice": 0, "revenge": 0, "mystery": 0,
    "comedy": 0, "wish_fulfillment": 0, "strategic_victory": 0,
    "catharsis": 0, "tension": 0, "character_growth": 0,
    "political_intrigue": 0, "emotional_connection": 0
  },
  "tension_curve": {
    "start": 0,
    "peak": 0,
    "end": 0
  }
}
```

All emotion/payoff scores: integers 0–10. Tension curve: integers 0–100. Omit zero values in deltas.

---

## Section 12 — Author Intent

The most important section for generation. Records WHY the author made these choices, not just what happened.

```json
{
  "author_goal": "string — what the author was trying to accomplish narratively",
  "reader_effect": "string — the intended reader experience/emotion/takeaway",
  "theme_reinforced": "string — which core theme this chapter advances",
  "strategy_notes": "string — the specific technique or mechanism used to achieve the above"
}
```

---

## Section 13 — Prose Samples (10–20 per chapter)

```json
{
  "type": "combat_technique | combat_reaction | dialogue_threat | dialogue_banter | dialogue_exposition | internal_monologue_planning | internal_monologue_reaction | scene_transition | power_reveal | comedy_setup | comedy_payoff | description_environment | description_character | emotional_beat | cultivation_description",
  "excerpt": "string — verbatim 2–8 sentences",
  "source_chapter": 0,
  "source_character_pov": "string — which character's perspective, or 'omniscient'",
  "narrative_distance": "close_third | distant_third | omniscient | first_person",
  "style_notes": "string — what makes this exemplary: rhythm, word choice, technique",
  "tags": ["absurdist", "repetition", "stream_of_consciousness", "technical", "poetic", "blunt"]
}
```

---

## Section 14 — Style DNA

Quantitative prose fingerprint. Programmatic fields are computed from the text; LLM fills the rest.

```json
{
  "sentence_length_distribution": {
    "short_1_10_words": 0.0,
    "medium_11_25_words": 0.0,
    "long_26_plus_words": 0.0
  },
  "paragraph_length_distribution": {
    "single_sentence": 0.0,
    "two_to_four_sentences": 0.0,
    "five_plus_sentences": 0.0
  },
  "content_ratios": {
    "dialogue_percentage": 0.0,
    "action_percentage": 0.0,
    "description_percentage": 0.0,
    "internal_monologue_percentage": 0.0
  },
  "pacing_markers": {
    "average_words_between_dialogue": 0,
    "average_words_between_paragraphs": 0,
    "action_sequence_avg_length_words": 0,
    "exposition_block_avg_length_words": 0
  },
  "stylistic_devices": {
    "repetition_for_emphasis": 0.0,
    "rhetorical_questions": 0.0,
    "exclamations": 0.0,
    "em_dashes_parentheticals": 0.0,
    "sensory_details_per_scene": 0.0,
    "metaphor_simile_frequency": 0.0
  },
  "vocabulary_markers": {
    "favorite_intensifiers": [],
    "favorite_transitions": [],
    "favorite_descriptors_power": [],
    "favorite_descriptors_emotion": [],
    "profanity_frequency": 0.0,
    "common_profanity": []
  },
  "character_catchphrases": {},
  "distinctive_style_markers": []
}
```

---

## Section 15 — Character Voice Samples

```json
{
  "character_name": "string — canonical name",
  "dialogue_samples": [
    {
      "line": "string — verbatim dialogue or thought",
      "context": "string — what triggered this line",
      "voice_notes": "string — what this reveals about how they speak/think"
    }
  ],
  "speech_dna": {
    "formality_level": "street | casual | neutral | formal | archaic",
    "verbosity": "terse | normal | verbose",
    "emotional_expression": "stoic | controlled | expressive | volatile",
    "signature_phrases": [],
    "sentence_structure_preference": "simple | compound | complex | fragmented",
    "uses_profanity": false,
    "uses_humor": "never | rarely | often | constantly",
    "humor_style": "deadpan | sarcastic | absurd | self_deprecating | boastful | none"
  }
}
```

---

## Section 16 — Scene Structure Patterns

```json
{
  "scenes": [
    {
      "scene_number": 0,
      "estimated_word_count": 0,
      "scene_type": "combat | dialogue | exposition | travel_transition | cultivation | planning | revelation | comedy_sequence | emotional_confrontation | power_discovery",
      "pov_character": "string or null",
      "narrative_distance": "close_third | distant_third | omniscient | first_person",
      "tension_level": 0.0,
      "pacing": "slow_burn | steady | rapid | explosive",
      "structure_notes": "string — how the scene is built, what makes it work"
    }
  ],
  "chapter_rhythm": {
    "opening_hook": "action | dialogue | mystery | continuation | description",
    "middle_build": "steady_escalation | plateau | multiple_peaks | calm_before_storm",
    "ending_type": "cliffhanger | resolution | transition | emotional_beat | comedy_button",
    "scene_count": 0,
    "average_scene_length_words": 0,
    "longest_scene_words": 0,
    "shortest_scene_words": 0
  }
}
```

---

## Section 17 — Narrative Voice Analysis

```json
{
  "dominant_pov": "string — character name or 'Omniscient' or 'Shifting'",
  "pov_shifts": [
    {
      "from_character": "string or null",
      "to_character": "string or null",
      "at_scene_number": 0,
      "transition_style": "hard_break | smooth_handoff | omniscient_bridge"
    }
  ],
  "narrative_intrusions": [
    {
      "excerpt": "string — narrator commenting directly",
      "type": "foreshadowing | dramatic_irony | aside_to_reader | genre_commentary | power_system_explanation",
      "tone": "humorous | ominous | matter_of_fact | sarcastic"
    }
  ],
  "thought_presentation": {
    "internal_monologue_style": "italicized | tagged_with_thought | untagged_free_indirect | stream_of_consciousness | first_person_direct",
    "frequency": "rare | occasional | frequent | constant",
    "depth": "surface_reactions | strategic_planning | philosophical_reflection | memory_flashback"
  },
  "structural_notes": "string — optional, anything notable about voice in this chapter",
  "genre_contract_signals": []
}
```

---

## Section 18 — Novel Metadata Hints

```json
{
  "alt_titles": [],
  "translator_notes": [
    {"text": "string", "chapter": 0, "context": "string"}
  ],
  "genre_signals": []
}
```

---

## Complete Field Reference

| Field | From | Required |
|-------|------|----------|
| `schema_version` | v2.1 | Always `"3.0"` |
| `chapter_number` | v2.0 | ✅ |
| `chapter_title` | v2.0 | ✅ |
| `title_function` | v2.0 | ✅ |
| `chapter_function` | v2.0 | ✅ |
| `summary` | v2.0 | ✅ |
| `arc_label_suggestion` | v2.0 | ✅ |
| `arc_boundary_signal` | v2.0 | ✅ |
| `arc_notes` | v2.0 | optional |
| `merge_notes` | v2.0 | optional |
| `new_characters` | v2.0 | ✅ |
| `new_locations` | v2.0 | ✅ |
| `new_factions` | v2.0 | ✅ |
| `new_glossary_terms` | v2.0 | ✅ |
| `facts` | v2.0 | ✅ |
| `timeline_events` | v2.0 | ✅ |
| `humor_instances` | v2.0 | ✅ |
| `scheme_instances` | v2.0 | ✅ |
| `knowledge_state` | v2.0 | ✅ |
| `antagonist_template_instances` | v2.0 | ✅ |
| `power_curve_notes` | v2.0 | when applicable |
| `reveals` | v2.0 | ✅ |
| `reader_psychology` | v2.0 | ✅ |
| `author_intent` | v2.0 | ✅ |
| `prose_samples` | v2.1 | ✅ 10–20 |
| `style_dna` | v2.1 | ✅ |
| `character_voice_samples` | v2.1 | ✅ |
| `scene_structure_patterns` | v2.1 | ✅ |
| `narrative_voice_analysis` | v2.1 | ✅ |
| `novel_metadata_hints` | v2.0 | optional |

---

## Migration Notes

- **v2.0 deltas**: Missing all v2.1 style fields. Can still be merged — merge.py treats missing fields as empty.
- **v2.1 deltas**: Missing `author_intent`, `knowledge_state`, `scheme_instances`, `antagonist_template_instances`, `power_curve_notes`, `new_factions`, `arc_notes`, `merge_notes`, `novel_metadata_hints`. These are the gaps to backfill.
- **v3.0 deltas**: Complete. Use `extract_enhanced.py` once updated to v3 prompt (see `extract_enhanced.py` header).

## LLM Extraction Prompt Coverage

The LLM extraction call must cover ALL of the following in a single pass:

**Plot/narrative layer** (was v2.0 only):
- `summary`, `chapter_function`, `title_function`, `arc_label_suggestion`, `arc_boundary_signal`
- `new_characters`, `new_locations`, `new_factions`, `new_glossary_terms`
- `facts`, `timeline_events`
- `humor_instances`, `scheme_instances`, `knowledge_state`
- `antagonist_template_instances`, `power_curve_notes`, `reveals`
- `reader_psychology`, `author_intent`

**Style/generation layer** (was v2.1 only):
- `prose_samples` (10–20)
- `style_dna` refinements (content ratios, vocabulary markers, catchphrases)
- `character_voice_samples`
- `scene_structure_patterns`
- `narrative_voice_analysis`
