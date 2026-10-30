"""
generate_genome.py - Generate narrative_genome.json for a novel

Reads chapter summaries, reveals, schemes, and reader psychology from the
merged wiki brain, then uses Claude to identify recurring narrative patterns.

Usage:
    python generate_genome.py --novel my_novel
    python generate_genome.py --novel my_novel
    python generate_genome.py                              # every novel, skipping ones already up to date

No-args mode is what the app's Corpus Pipeline dashboard launches (same
"bare script = process every novel" convention every other pipeline job
follows) — see is_stale() for what "up to date" means, since this is a real
LLM call per novel and shouldn't re-pay that cost on an unchanged novel.
"""

import json
import re
import argparse
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# LLM calls go through llm_client (API key OR Claude subscription CLI).
client = None

NOVELS_PATH = Path("novels")


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_context(novel_id: str) -> str:
    """Assemble a rich context from all available merged data."""
    d = NOVELS_PATH / novel_id

    # Chapter summaries from deltas_v3
    delta_dir = d / "deltas_v3"
    summaries = []
    if delta_dir.exists():
        for f in sorted(delta_dir.glob("*.json")):
            delta = load_json(f)
            if delta and delta.get("summary"):
                ch = delta.get("chapter_number", f.stem)
                summaries.append(f"Ch{ch}: {delta['summary']}")

    # Reader psychology — satisfaction peaks
    psych = load_json(d / "reader_psychology" / "chapters.json") or []
    high_points = []
    for entry in psych:
        ch = entry.get("chapter_number", "?")
        for cat, score in (entry.get("payoff_categories") or {}).items():
            if isinstance(score, (int, float)) and score >= 8:
                high_points.append(f"Ch{ch} {cat}={score}")

    # Reveals
    reveals = load_json(d / "reveals" / "log.json") or []
    reveal_lines = [
        f"  - [{r.get('reveal_type','?')}] Ch{r.get('chapter_revealed','?')}: {r.get('reveal_statement','')[:100]}"
        for r in reveals[:30]
    ]

    # Schemes
    schemes = load_json(d / "schemes" / "instances.json") or []
    scheme_lines = [
        f"  - [{s.get('scheme_type','?')}] Ch{s.get('introduced_chapter','?')}–{s.get('resolved_chapter','?')}: {s.get('description','')[:100]}"
        for s in schemes[:20]
    ]

    # Arcs
    arcs = load_json(d / "timeline" / "arcs.json") or []
    arc_lines = [
        f"  - Arc {i+1}: {a.get('label','')} (ch {a.get('start_chapter','?')}–{a.get('end_chapter','?')}): {a.get('summary','')[:100]}"
        for i, a in enumerate(arcs[:10])
    ]

    # Novel metadata
    meta = load_json(d / "novel_metadata.json") or {}
    title = meta.get("title", novel_id)
    genre = ", ".join((meta.get("genre_signals") or {}).keys())[:80]

    lines = [f"NOVEL: {title}", f"GENRE SIGNALS: {genre}", ""]

    if arc_lines:
        lines += ["STORY ARCS:"] + arc_lines + [""]
    if summaries:
        # Cap at 80 summaries, each truncated to 150 chars
        capped = [s[:150] for s in summaries[:80]]
        lines += [f"CHAPTER SUMMARIES ({len(summaries)} chapters, showing first {len(capped)}):"] + capped + [""]
    if high_points:
        lines += ["HIGH SATISFACTION MOMENTS (reader_psychology peaks ≥8):"] + [f"  {h}" for h in high_points[:30]] + [""]
    if reveal_lines:
        lines += ["KEY REVEALS (first 20):"] + reveal_lines[:20] + [""]
    if scheme_lines:
        lines += ["SCHEMES/PLOTS (first 15):"] + scheme_lines[:15] + [""]

    return "\n".join(lines)


GENOME_PROMPT = """You are a narrative analyst studying a web novel's structural DNA.

Read the chapter summaries, reveals, and reader data below. Identify 5-10 RECURRING NARRATIVE PATTERNS — story moves that repeat multiple times across chapters, each with a recognizable setup→payoff structure.

Focus on patterns that:
- Repeat at least 3+ times
- Have a clear escalation (each repetition raises stakes or varies the formula)
- Generate strong reader satisfaction when they pay off

For each pattern output:
{
  "pattern_id": "snake_case_name",
  "pattern_type": "antagonist_arc | power_reveal | relationship_beat | comedy_sequence | mystery_unfolding | cultivation_milestone | betrayal_arc | rescue_sequence",
  "description": "2-3 sentences: what the setup looks like, what triggers it, how it resolves",
  "occurrences": <integer — how many times you see this in the summaries>,
  "chapter_range": [first_chapter, last_chapter],
  "average_chapter_span": <float — avg chapters from setup to payoff>,
  "payoff_delay_avg_chapters": <float — how long between setup and payoff>,
  "reader_satisfaction_on_payoff": <float 1-10 — estimated satisfaction based on psychology data>,
  "escalation_pattern": "One sentence: how each new instance raises the stakes vs previous",
  "failure_conditions": ["What would make this pattern feel stale or fail"],
  "common_variants": ["Variation 1", "Variation 2"],
  "gen_guidance": "2-3 sentences of guidance for an author wanting to use this pattern"
}

Output a JSON object:
{
  "schema_version": "3.0",
  "novel_id": "<novel_id>",
  "description": "One sentence describing this novel's core narrative engine",
  "patterns": [ ...5-10 pattern objects... ]
}

Output ONLY valid JSON."""


def _chapter_summary_count(novel_id: str) -> int:
    """How many chapter summaries this novel currently has extracted — the
    staleness signal for is_stale(): a genome built when the novel had far
    fewer chapters extracted is worth regenerating; one built at/near the
    current count isn't."""
    delta_dir = NOVELS_PATH / novel_id / "deltas_v3"
    if not delta_dir.exists():
        return 0
    return sum(1 for f in delta_dir.glob("*.json") if load_json(f) and load_json(f).get("summary"))


def is_stale(novel_id: str) -> bool:
    """True if this novel has no genome yet, or has grown by 15+ newly-
    extracted chapters (or 20%+, whichever is smaller a bar) since its genome
    was last built — regenerating on every single new chapter would burn an
    LLM call for a change too small to shift the recurring-pattern picture;
    waiting until the corpus barely changed at all wastes the opposite way.
    15 chapters (or 20%) is a middle ground, not derived from anything
    stricter. source_chapter_count is written by generate_genome() below;
    an existing genome from before this field existed is always stale."""
    out_path = NOVELS_PATH / novel_id / "narrative_genome.json"
    genome = load_json(out_path)
    if not genome or "source_chapter_count" not in genome:
        return True
    built_at = genome.get("source_chapter_count", 0)
    current = _chapter_summary_count(novel_id)
    if current <= built_at:
        return False
    grown = current - built_at
    return grown >= min(15, max(1, int(built_at * 0.2)))


_POOL = None     # set by main() while the agents run


def generate_genome(novel_id: str):
    context = build_context(novel_id)

    if len(context) < 500:
        print(f"[SKIP] Not enough data for {novel_id} (context too thin)")
        return

    print(f"\n[{novel_id}] Sending {len(context):,} chars to the LLM (model announced below)...")

    from llm_client import call_llm, write_live_status
    if _POOL is not None:       # agent row on the card (see agent_pool.py)
        _POOL.step("pattern analysis", context[:160])
    else:
        write_live_status("narrative_genome", novel=novel_id, kind="pattern analysis", preview=context[:200])
    raw = call_llm(
        system="You are an expert at analyzing web-novel narrative structure. Output only what is requested.",
        user=f"{GENOME_PROMPT}\n\nNOVEL ID: {novel_id}\n\n{context}",
        model="claude-sonnet-4-6",
        max_tokens=8000,
        temperature=0.3,
    ).strip()

    # Extract JSON
    json_match = re.search(r'```json\s*\n(.*?)\n```', raw, re.DOTALL)
    if json_match:
        raw = json_match.group(1)

    try:
        genome = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON parse failed: {e}")
        # Save raw for inspection
        (NOVELS_PATH / novel_id / "narrative_genome_raw.txt").write_text(raw, encoding="utf-8")
        print(f"[Saved] Raw response to narrative_genome_raw.txt")
        return

    # Save — source_chapter_count stamps how many chapters this genome was
    # actually built from, so a later run's is_stale() can tell a genuinely
    # outdated genome (worth another LLM call) from one that's already
    # current for this novel's corpus state.
    genome["source_chapter_count"] = _chapter_summary_count(novel_id)
    out_path = NOVELS_PATH / novel_id / "narrative_genome.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(genome, f, indent=2, ensure_ascii=False)

    pattern_count = len(genome.get("patterns", []))
    print(f"[OK] Saved {pattern_count} patterns to {out_path}")
    for p in genome.get("patterns", []):
        print(f"  - [{p.get('pattern_type','?')}] {p.get('pattern_id','')} (x{p.get('occurrences','?')}, sat={p.get('reader_satisfaction_on_payoff','?')})")


def main():
    parser = argparse.ArgumentParser(description="Generate narrative_genome.json for a novel")
    parser.add_argument("--novel", help="Novel ID (folder name in novels/) — omit to process every novel")
    parser.add_argument("--force", action="store_true", help="Regenerate even if is_stale() says it's current (only meaningful with --novel; no-args mode always respects staleness)")
    args = parser.parse_args()

    if args.novel:
        novel_path = NOVELS_PATH / args.novel
        if not novel_path.exists():
            print(f"[ERROR] Novel not found: {novel_path}")
            return
        if not args.force and not is_stale(args.novel):
            print(f"[SKIP] {args.novel} — genome already current (use --force to regenerate anyway)")
            return
        generate_genome(args.novel)
        return

    # No --novel: process every novel directory, same "bare script = all
    # novels" convention build_knowledge_index.py and the other pipeline
    # jobs already use — this is what the app's Corpus Pipeline dashboard
    # launches. Always respects is_stale() here (no --force override) since
    # an unattended dashboard run should never re-pay for LLM calls on
    # novels that haven't meaningfully changed.
    novel_ids = sorted(p.name for p in NOVELS_PATH.iterdir() if p.is_dir())
    # Same agent method as Chapter Mechanics: one agent per Nvidia key, one novel each.
    global _POOL
    from agent_pool import AgentPool
    from llm_client import current_model_label
    stale = [n for n in novel_ids if is_stale(n)]
    skipped = len(novel_ids) - len(stale)
    _POOL = AgentPool("narrative_genome", model=current_model_label(None), want=4)
    res = _POOL.run([{"novel": n, "unit": "genome"} for n in stale], lambda it: generate_genome(it["novel"]))
    processed = sum(1 for _it, r in res if not isinstance(r, Exception))
    print(f"\n[DONE] {processed} novel(s) regenerated, {skipped} already current.")


if __name__ == "__main__":
    main()
