"""Deterministic repair of the ways the extraction model breaks its JSON.

Built from 44 real unparseable answers the Corpus Builder saved (corpus/_split_parts/_bad_answers/). The faults, by how often:
  - a string value in SINGLE quotes ('Somatic fear ("blood freeze")') - the most common
  - a string value with no opening quote  ("meaning": the hero faces ...",)
  - a string that opens with a backslash-quote  (\\"Hahaha, if you ...\\"",)
  - an unquoted key (quotes: [...]) or a key whose closing quote is missing ("victim_aware: true,)
  - a double quote inside a string that was never escaped
  - brackets that were never closed
The answers are pretty-printed, one value per line, so the repair works line by line and only ever changes QUOTING: the words
inside a value are never touched. If the result still does not parse, the caller falls back to its salvage / re-ask.
"""
import json
import re

_KEY_LINE = re.compile(r'^(\s*)(?:"([^"\n]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*:\s*(.*)$')
_BROKEN_KEY = re.compile(r'^(\s*)"([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$')          # "victim_aware: true,
_LITERAL = re.compile(r'^(?:-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)$')


def _valid(core: str) -> bool:
    try:
        json.loads(core)
        return True
    except ValueError:
        return False


def _as_string(core: str) -> str:
    """The text of a value written with the wrong quoting, as a proper JSON string."""
    t = core.strip()
    t = re.sub(r'^[\\"\'*\s]+', "", t)
    t = re.sub(r'[\\"\'*\s]+$', "", t)
    t = t.replace("\\'", "'").replace('\\"', '"')
    return json.dumps(t, ensure_ascii=False)


def _fix_value(val: str) -> str:
    v = val.rstrip()
    comma = v.endswith(",")
    core = v[:-1].rstrip() if comma else v
    tail = "," if comma else ""
    if not core:
        return val
    if core[0] in "{[}]" or _valid(core) or _LITERAL.match(core):
        return val                       # structure, a valid string/number/literal: leave it exactly as it is
    if core[0] == "|":
        return val
    return _as_string(core) + tail


def normalize_lines(s: str) -> str:
    out = []
    for line in s.split("\n"):
        m = _KEY_LINE.match(line)
        if m:
            indent, k1, k2, val = m.groups()
            out.append(f'{indent}"{k1 or k2}": {_fix_value(val)}')
            continue
        m = _BROKEN_KEY.match(line)
        if m:
            indent, key, val = m.groups()
            out.append(f'{indent}"{key}": {_fix_value(val)}')
            continue
        st = line.strip()
        if st and st[0] in "'\\":                       # an array item written with single quotes / a backslash-quote
            out.append(line[:len(line) - len(line.lstrip())] + _fix_value(st))
            continue
        out.append(line)
    return "\n".join(out)


def escape_inner_quotes(s: str) -> str:
    """A quote only closes a string when what follows is JSON structure; any other quote inside a string is escaped."""
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
    return "".join(out)


def close_brackets(s: str) -> str:
    """Add the closers an answer left out (and drop a dangling comma before them). Strings are skipped over."""
    stack, in_str, i, n, out = [], False, 0, len(s), []
    while i < n:
        c = s[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(s[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
                out.append(c)
            elif c in "{[":
                stack.append("}" if c == "{" else "]")
                out.append(c)
            elif c in "}]":
                while stack and stack[-1] != c:         # a closer for something still open: close what is open first
                    out.append(stack.pop())
                if stack:
                    stack.pop()
                out.append(c)
            else:
                out.append(c)
        i += 1
    text = "".join(out).rstrip()
    if in_str:
        return None                                       # cut off inside a string: not repairable here
    text = re.sub(r",\s*$", "", text)
    return text + "".join(reversed(stack))


def repair(s: str):
    """The parsed dict, or None when no combination of the fixes makes the text parse."""
    steps = (
        lambda t: t,
        normalize_lines,
        lambda t: escape_inner_quotes(normalize_lines(t)),
        lambda t: close_brackets(normalize_lines(t)),
        lambda t: close_brackets(escape_inner_quotes(normalize_lines(t))),
    )
    for step in steps:
        try:
            t = step(s)
            if t is None:
                continue
            obj = json.loads(t, strict=False)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None
