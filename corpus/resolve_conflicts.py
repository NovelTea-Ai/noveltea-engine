#!/usr/bin/env python3
"""Resolve conflicts.json warnings for a novel — automatically where safe.

Run by the pipeline after every merge (and runnable standalone):

    python resolve_conflicts.py --novel <novel_id>

What it fixes:
  * near_miss_name_warnings — decides whether the two names are the SAME
    entity. Names identical after normalization (case/punctuation/spacing)
    merge automatically; ambiguous pairs are adjudicated by the LLM in ONE
    batched call. "Same" → merged via merge.py's apply_entity_aliasing and
    entity files rewritten; "different" → recorded so it stops nagging.
    Every outcome is logged under conflicts.resolved_name_warnings.
  * unresolved_callbacks — retries humor callback linking with fuzzy text +
    participant matching against the humor log.
  * merge_notes_log — drops empty entries, dedupes, caps growth.

Never fails the pipeline: exits 0 even when items stay unresolved.
"""
import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

BRAIN_DIR = Path(__file__).parent
sys.path.insert(0, str(BRAIN_DIR))

from merge import load_all_entities, build_alias_index, apply_entity_aliasing, save_json  # noqa: E402


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _entity_summary(ent: dict) -> str:
    facts = []
    for f in (ent.get("facts") or [])[:3]:
        txt = f.get("fact") or f.get("text") or f.get("content") or ""
        if txt:
            facts.append(str(txt)[:110])
    return (
        f"canonical={ent.get('canonical_name')!r}, type={ent.get('type', '?')}, "
        f"aliases={ent.get('aliases', [])[:4]}, first_ch={ent.get('created_chapter')}, "
        f"appears_in={len(ent.get('appearances', []))} chapters"
        + (f", facts: {' | '.join(facts)}" if facts else "")
    )


def resolve_name_warnings(ndir: Path, conflicts: dict) -> tuple[int, int]:
    warnings = conflicts.get("near_miss_name_warnings") or []
    if not warnings:
        return 0, 0
    entities_dir = ndir / "entities"
    entities = load_all_entities(entities_dir)
    original_slugs = set(entities.keys())
    alias_index = build_alias_index(entities)
    resolved = conflicts.setdefault("resolved_name_warnings", [])

    def finish(w, resolution, why):
        resolved.append({**w, "resolution": resolution, "why": why,
                         "at": time.strftime("%Y-%m-%d %H:%M")})

    auto, keep, ambiguous = 0, [], []
    for w in warnings:
        new_name = w.get("new_name", "")
        canon = w.get("similar_entity_canonical", "")
        s_new = alias_index.get(new_name.lower().strip())
        s_old = alias_index.get(canon.lower().strip())
        if not s_new or not s_old or s_new == s_old:
            finish(w, "stale", "one side no longer exists as a separate entity")
            auto += 1
            continue
        if _norm(new_name) == _norm(canon) or _norm(new_name) == _norm(w.get("similar_to_name", "")):
            # same letters, different punctuation/spacing — certainly the same
            _merge_pair(w, entities, alias_index, conflicts, finish)
            auto += 1
        else:
            ambiguous.append(w)

    # ── one batched LLM call for everything genuinely ambiguous ──
    llm_merged = 0
    if ambiguous:
        try:
            from llm_client import call_llm
            lines = []
            for i, w in enumerate(ambiguous):
                a = entities.get(alias_index.get(w["new_name"].lower().strip()), {})
                b = entities.get(alias_index.get(w["similar_entity_canonical"].lower().strip()), {})
                lines.append(f"PAIR {i}:\n  A: {_entity_summary(a) or w['new_name']}\n"
                             f"  B: {_entity_summary(b) or w['similar_entity_canonical']}")
            system = (
                "You adjudicate entity identity in a web novel wiki. For each pair decide whether "
                "name A and name B refer to the SAME character/location/faction (a variant spelling, "
                "title, or alias) or DIFFERENT ones. Web novels often have near-identical names for "
                "different characters (e.g. 'Jiang Chen' vs 'Jiang Cheng') — when the evidence is "
                "thin, answer different (merging wrongly is worse than keeping separate).\n\n"
                'verdicts — array of {"pair": <number>, "same": true|false, "reason": "<short>"}'
            )
            out = call_llm(system=system, user="\n\n".join(lines) +
                           '\n\nReturn ONLY JSON: {"verdicts":[...]}',
                           model="claude-haiku-4-5-20251001", max_tokens=2000,
                           required_keys=["verdicts"])
            verdicts = {v.get("pair"): v for v in json.loads(out).get("verdicts", [])
                        if isinstance(v, dict)}
        except Exception as e:
            print(f"  [conflicts] LLM adjudication unavailable ({str(e)[:90]}) — leaving "
                  f"{len(ambiguous)} warnings for next run")
            verdicts = {}
        for i, w in enumerate(ambiguous):
            v = verdicts.get(i)
            if v is None:
                keep.append(w)
                continue
            if v.get("same"):
                _merge_pair(w, entities, alias_index, conflicts, finish,
                            why=str(v.get("reason", ""))[:160])
                llm_merged += 1
            else:
                finish(w, "kept_separate", str(v.get("reason", ""))[:160])

    # write entities back: changed records saved, merged-away slugs deleted
    for slug, rec in entities.items():
        save_json(entities_dir / f"{slug}.json", rec)
    for gone in original_slugs - set(entities.keys()):
        try:
            (entities_dir / f"{gone}.json").unlink()
        except OSError:
            pass

    conflicts["near_miss_name_warnings"] = keep
    return len(warnings) - len(keep), len(keep)


def _merge_pair(w, entities, alias_index, conflicts, finish, why="names normalize to the same string"):
    a_slug = alias_index.get(w["new_name"].lower().strip())
    b_slug = alias_index.get(w["similar_entity_canonical"].lower().strip())
    a, b = entities.get(a_slug, {}), entities.get(b_slug, {})
    # keep the richer record as canonical, fold the other into it
    if len(a.get("appearances", [])) > len(b.get("appearances", [])):
        old, new = w["similar_entity_canonical"], w["new_name"]
    else:
        old, new = w["new_name"], w["similar_entity_canonical"]
    apply_entity_aliasing(old, new, entities, alias_index, conflicts)
    finish(w, "merged", why)
    print(f"  [conflicts] merged entity '{old}' into '{new}' — {why}")


def resolve_callbacks(ndir: Path, conflicts: dict) -> tuple[int, int]:
    unresolved = conflicts.get("unresolved_callbacks") or []
    if not unresolved:
        return 0, 0
    humor_file = ndir / "humor" / "instances.json"
    try:
        humor = json.loads(humor_file.read_text(encoding="utf-8"))
    except Exception:
        return 0, len(unresolved)
    by_id = {h.get("id"): h for h in humor if isinstance(h, dict)}
    keep, fixed = [], 0
    llm_items = []   # (entry, inst, top-candidates) for LLM adjudication
    for entry in unresolved:
        inst = by_id.get(entry.get("instance_id"))
        text = (entry.get("callback_to_text") or "").lower()
        if not inst or not text:
            fixed += 1  # stale — drop
            continue
        inst_parts = set(p.lower() for p in (inst.get("participants") or []) if isinstance(p, str))
        scored = []
        for cand in humor:
            cid = cand.get("id", "")
            if not cid or cid >= entry["instance_id"]:
                continue  # callbacks point BACKWARD
            hay = " ".join(str(cand.get(k, "")) for k in ("setup", "payoff", "example_text")).lower()
            score = difflib.SequenceMatcher(None, text, hay[:600]).ratio()
            cand_parts = set(p.lower() for p in (cand.get("participants") or []) if isinstance(p, str))
            if inst_parts & cand_parts:
                score += 0.15
            scored.append((score, cand))
        scored.sort(key=lambda s: -s[0])
        if scored and scored[0][0] >= 0.45:
            best = scored[0][1]
            inst["callback_to_id"] = best["id"]
            conflicts.setdefault("resolved_callbacks", []).append(
                {**entry, "linked_to": best["id"], "score": round(scored[0][0], 2)})
            print(f"  [conflicts] linked callback {entry['instance_id']} -> {best['id']} "
                  f"(score {scored[0][0]:.2f})")
            fixed += 1
        else:
            llm_items.append((entry, inst, [c for _, c in scored[:5]]))

    # ── LLM fallback: pick the antecedent, or dismiss running-gag references ──
    if llm_items:
        try:
            from llm_client import call_llm
            blocks = []
            for i, (entry, inst, cands) in enumerate(llm_items):
                cl = "\n".join(f"    {c['id']}: {str(c.get('setup', ''))[:90]} / "
                               f"{str(c.get('payoff', ''))[:90]}" for c in cands) or "    (none)"
                blocks.append(f"ITEM {i}: callback text: {entry['callback_to_text']!r}\n"
                              f"  candidate earlier instances:\n{cl}")
            system = (
                "You link humor 'callback' references in a web-novel wiki. For each item, the callback "
                "text refers back to earlier humor. If exactly one candidate instance IS the thing being "
                "referenced, pick its id. If the text refers to a RUNNING PATTERN or general theme rather "
                "than one specific instance, answer null.\n\n"
                'links — array of {"item": <number>, "id": "<candidate id or null>", "reason": "<short>"}'
            )
            out = call_llm(system=system, user="\n\n".join(blocks) +
                           '\n\nReturn ONLY JSON: {"links":[...]}',
                           model="claude-haiku-4-5-20251001", max_tokens=1500,
                           required_keys=["links"])
            links = {l.get("item"): l for l in json.loads(out).get("links", []) if isinstance(l, dict)}
        except Exception as e:
            print(f"  [conflicts] LLM callback linking unavailable ({str(e)[:90]})")
            links = {}
        for i, (entry, inst, cands) in enumerate(llm_items):
            v = links.get(i)
            if v is None:
                keep.append(entry)
                continue
            cid = v.get("id")
            if cid and cid in by_id and cid < entry["instance_id"]:
                inst["callback_to_id"] = cid
                conflicts.setdefault("resolved_callbacks", []).append(
                    {**entry, "linked_to": cid, "via": "llm", "reason": str(v.get("reason", ""))[:140]})
                print(f"  [conflicts] linked callback {entry['instance_id']} -> {cid} (LLM)")
                fixed += 1
            else:
                # a theme, not a single antecedent — record and stop nagging
                conflicts.setdefault("dismissed_callbacks", []).append(
                    {**entry, "reason": str(v.get("reason", "running-gag reference, no single antecedent"))[:140]})
                fixed += 1

    if fixed:
        save_json(humor_file, humor)
    conflicts["unresolved_callbacks"] = keep
    return fixed, len(keep)


def prune_notes(conflicts: dict) -> int:
    log = conflicts.get("merge_notes_log") or []
    seen, cleaned = set(), []
    for e in log:
        notes = e.get("notes")
        if not notes:
            continue  # empty note entries carry no information
        key = (e.get("chapter"), json.dumps(notes, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(e)
    removed = len(log) - len(cleaned)
    conflicts["merge_notes_log"] = cleaned[-150:]
    return removed + max(0, len(cleaned) - 150)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--novel", required=True)
    args = ap.parse_args()
    ndir = BRAIN_DIR / "novels" / args.novel
    cfile = ndir / "conflicts.json"
    if not cfile.exists():
        print("  [conflicts] no conflicts.json — nothing to resolve")
        return
    try:
        conflicts = json.loads(cfile.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [conflicts] unreadable conflicts.json ({e}) — skipping")
        return

    n_fixed, n_left = resolve_name_warnings(ndir, conflicts)
    c_fixed, c_left = resolve_callbacks(ndir, conflicts)
    pruned = prune_notes(conflicts)
    save_json(cfile, conflicts)

    # ASCII-only output: standalone runs may land on a cp1252 console
    print(f"  [conflicts] name warnings: {n_fixed} resolved, {n_left} kept for review | "
          f"callbacks: {c_fixed} linked, {c_left} unresolved | notes pruned: {pruned}")
    if not (n_left or c_left):
        print("  [OK] conflicts.json is clean")


if __name__ == "__main__":
    main()
