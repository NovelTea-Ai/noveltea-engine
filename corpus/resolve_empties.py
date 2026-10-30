"""
resolve_empties.py - Settle "nothing to extract" vs "the extraction missed it".

For every chapter whose important fields (reveals, knowledge_state, facts, timeline_events, prose_samples,
character_voice_samples) are empty and were never ruled on (see delta_audit.py's resolve_candidates), ask
ONE targeted question per chapter: extract it if it's there, or answer "none" if the chapter genuinely has
nothing. A "none" is recorded in the delta's confirmed_empty list, so the field stops being flagged as a
possible gap; real content is written into the field. Originals are kept as chNN.pre-resolve-original.json.

Not locked to a model: by default it uses whichever engine/model is selected in the app (the Corpus Pipeline
card shows which); --model claude-sonnet-5-5 (or any Claude model id) forces one instead.

This is a thin launcher (its own script name so the Corpus Pipeline card can tell it apart from the upgrade job);
all logic lives in upgrade_deltas.resolve_main.

    python resolve_empties.py --dry-run --limit 3      # ask, print, write nothing
    python resolve_empties.py                          # everything unresolved, all novels
    python resolve_empties.py --novel my_novel
"""
import upgrade_deltas

if __name__ == "__main__":
    upgrade_deltas.resolve_main()
