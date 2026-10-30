"""Narration pronunciation: respell Chinese (pinyin) names and terms in English
sounds before the text reaches a TTS voice, so "Zhou Tien" is read "Zhoe Tee-yen"
and "qi" is read "chee". Only the spoken text changes, never the chapter.

Names come from the project's cast and foes: each capitalised
part that splits cleanly into pinyin syllables is respelled. Bump
PRON_VERSION whenever the rules change, so saved narration is remade."""
import re

PRON_VERSION = "1"

# Whole-word overrides: the author's own choices win over the generic rules.
OVERRIDES = {
    "Zhou": "Zhoe", "Tien": "Tee-yen", "Tian": "Tee-yen",
}
# Pinyin terms used as ordinary words in the prose (matched case-insensitively).
TERMS = {
    "qi": "chee", "dao": "dow", "dantian": "dahn-tee-yen", "jianghu": "jee-ahng-hoo",
    "yin": "yin", "yang": "yahng",
}

_INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h",
             "j", "q", "x", "r", "z", "c", "s", "y", "w"]
_INIT_SAY = {"j": "j", "q": "ch", "x": "sh", "zh": "j", "ch": "ch", "sh": "sh", "z": "z", "c": "ts"}
# A w-glide ("Gwaw") reads well only after these; elsewhere it is spelled "oo-" ("Hoo-ah").
_W_OK = {"g", "k", "s", "d", "t"}
_FINALS = {
    "a": "ah", "ai": "eye", "ao": "au", "an": "ahn", "ang": "ahng", "e": "uh", "ei": "ay",
    "en": "un", "eng": "ung", "o": "aw", "ou": "oh", "ong": "oong", "i": "ee",
    "ia": "ee-ah", "iao": "ee-yau", "ian": "ee-en", "ien": "ee-en", "iang": "ee-ahng", "ie": "ee-eh",
    "in": "een", "ing": "ing", "iong": "ee-oong", "iu": "ee-oh", "u": "oo", "ua": "wah",
    "uai": "wye", "uan": "wahn", "uang": "wahng", "ui": "way", "un": "wun", "uo": "waw",
    "v": "oo", "ü": "oo", "ve": "oo-eh", "üe": "oo-eh", "ue": "oo-eh",
}
# u after j/q/x/y is the rounded ü sound.
_JQX_U = {"u": "oo", "uan": "oo-en", "un": "oon", "ue": "oo-eh"}
_Y_W = {
    "ya": "yah", "yan": "yen", "yang": "yahng", "yao": "yau", "ye": "yeh", "yi": "ee",
    "yin": "yin", "ying": "ying", "yong": "yoong", "you": "yoh", "yu": "yoo", "yuan": "yoo-en",
    "yue": "yoo-eh", "yun": "yoon", "wa": "wah", "wai": "wye", "wan": "wahn", "wang": "wahng",
    "wei": "way", "wen": "wun", "weng": "wung", "wo": "waw", "wu": "woo",
}
# Syllables with no initial.
_BARE = {"a": "ah", "ai": "eye", "ao": "au", "an": "ahn", "ang": "ahng", "e": "uh", "ei": "ay",
         "en": "un", "er": "ar", "o": "aw", "ou": "oh"}


def _say_syllable(s: str):
    """Respelling for one pinyin syllable, or None if it is not one."""
    if s in _Y_W:
        return _Y_W[s]
    if s in _BARE:
        return _BARE[s]
    for ini in _INITIALS:
        if s.startswith(ini) and len(s) > len(ini):
            fin = s[len(ini):]
            if ini in ("y", "w"):
                return None
            if ini in ("j", "q", "x") and fin[0] not in "iuü":
                return None                         # "xa", "qe" are not pinyin
            if fin == "i" and ini in ("zh", "ch", "sh", "r"):
                return _INIT_SAY.get(ini, ini) + "ur"
            if fin == "i" and ini in ("z", "c", "s"):
                return _INIT_SAY.get(ini, ini) + "uh"
            if ini in ("j", "q", "x") and fin in _JQX_U:
                return _INIT_SAY[ini] + _JQX_U[fin]
            if fin in _FINALS:
                say = _FINALS[fin]
                lead = _INIT_SAY.get(ini, ini)
                if ini == "sh" and fin == "ou":
                    return "show"
                if fin == "ou":
                    say = "oe"                      # Dou -> Doe, Hou -> Hoe
                if say.startswith("w") and ini not in _W_OK:
                    # Hua -> Hoo-ah, not "Hwah" (read as letters); Shui -> Shoo-way ("-ay" alone reads "eye")
                    say = "oo-way" if say == "way" else "oo-" + say[1:]
                return lead + say
            return None
    return None


def _split_pinyin(word: str):
    """Split a lowercase word into pinyin syllables (longest match first, with
    backtracking), or None. A vowel-only syllable ("a", "e", "er") may only open
    the word or follow an apostrophe, as pinyin writes it (Xi'an, Bei'er) — this
    keeps English words like "Keeper" (ke-e-per) out."""
    out = []
    for piece in re.split(r"['’]", word):
        def seg(i):
            if i == len(piece):
                return []
            for j in range(min(len(piece), i + 6), i, -1):
                syl = piece[i:j]
                if i > 0 and syl in _BARE:
                    continue
                say = _say_syllable(syl)
                if say:
                    rest = seg(j)
                    if rest is not None:
                        return [say] + rest
            return None
        got = seg(0) if piece else None
        if not got:
            return None
        out += got
    return out


def respell_word(word: str):
    """'Xiaobei' -> 'Shyow-bay'; None if the word is not pinyin."""
    if word in OVERRIDES:
        return OVERRIDES[word]
    parts = _split_pinyin(word.lower())
    if not parts:
        return None
    say = "-".join(parts)
    return say[0].upper() + say[1:]


# Name parts that are also English words: respelled only inside a full name, or
# mid-sentence (a capitalised "Sun" mid-sentence is the name; at a sentence start
# it may be the English word).
_ENGLISH = {"Sun", "Fang", "Pang", "Sang", "Tan", "Pan", "Fan", "Wan", "Ban", "Dan", "Long", "Men",
            "Man", "Hang", "Bang", "Gang", "Ken", "Hen", "Den", "Pen", "Bo", "Ma", "Mi", "Mo", "Ye",
            "Bi", "He", "Tie", "Lie", "Die", "Ha", "Hua", "Bai", "Gan", "Shan", "Mu", "Lin", "Jin", "Ning"}

_TITLE_WORDS = re.compile(r"[A-Z][a-zü]+(?:['’][a-z]+)?")


def build_lexicon(project: dict) -> dict:
    """{name part: respelling} from every name-like field in the project."""
    names = []
    for c in project.get("character_list") or []:
        names.append(c.get("name") or "")
    for r in (project.get("antagonists") or {}).get("roster") or []:
        names.append(r.get("name") or "")
    # People only: faction and lore titles are mostly English words, and some
    # ("Gate" = ga-te) split into pinyin by accident.
    lex = {}
    for n in names:
        # The Chinese name is the run of pinyin words at the end, after any title
        # ("Sect Master Bi Hanlong") and before any epithet ("…, the Iron Tide",
        # "… of the Nine Crucibles", where "Nine" would split as ni-ne).
        n = re.split(r",| of ", n)[0]
        run = []
        for part in reversed(re.split(r"[\s\-]+", n)):
            say = respell_word(part) if _TITLE_WORDS.fullmatch(part) else None
            if not say:
                break
            run.append((part, say))
        for part, say in run:
            if part not in lex and say.lower() != part.lower():
                lex[part] = say
    for k, v in OVERRIDES.items():
        lex.setdefault(k, v)
    return lex


# Sound words with no vowel are spelled out letter by letter ("Tchk" -> "T C H K").
# Keys are the word lowercased with repeated letters collapsed ("Shhh" -> "sh").
SOUNDS = {
    "sh": "shush", "hm": "hmm", "m": "hmm", "mhm": "um-hum", "br": "burr", "gr": "gurr",
    "z": "zuzz", "hs": "hiss", "s": "hiss", "pft": "pfut", "pf": "pfut", "ngh": "nguh",
    "ng": "nguh", "hrk": "hurk", "hmph": "hurmph", "hrmph": "hurmph", "tsk": "tut",
    "tchk": "chik", "kch": "kuh-chik", "bzt": "buzzt", "pst": "psst", "shk": "shik",
}
_ABBREV = {"mr", "mrs", "ms", "dr", "st", "ch", "pt", "vs"}


def _collapse(w: str) -> str:
    return re.sub(r"(.)\1+", r"\1", w.lower())


def _sound_word(m):
    w = m.group(0)
    if w.lower() in _ABBREV or (w.isupper() and len(w) <= 3 and _collapse(w) not in SOUNDS):
        return w                                # an abbreviation or acronym: leave it
    key = _collapse(w)
    say = SOUNDS.get(key)
    if not say:
        say = re.sub(r"^t(?=ch)", "", key)      # "tch" opens like "ch"
        say = say[:-1] + "i" + say[-1] if len(say) > 1 else say + "uh"
    return say.capitalize() if w[0].isupper() else say


def apply_sounds(text: str) -> str:
    """Make vowel-less sound words ("Tchk", "Shhh", "Grr") speakable."""
    # not after/before an apostrophe: the "ll" of "I'll", the "nt" of "can'nt"
    return re.sub(r"(?<!['’])\b[b-df-hj-np-tv-xzB-DF-HJ-NP-TV-XZ]{2,}\b(?!['’])", _sound_word, text)


def marks(text: str, lex: dict) -> dict:
    """{word as written: how the voice says it} for every word in `text` that
    narration respells, for the Reader's blue highlights. The text is unchanged."""
    out = {}
    for w in set(re.findall(r"[A-Za-zü]+(?:['’][A-Za-z]+)*", text)):
        if w in lex:
            out[w] = lex[w]
        elif w.lower() in TERMS and TERMS[w.lower()] != w.lower():
            out[w] = TERMS[w.lower()]
        else:
            said = apply_sounds(w)
            if said != w:
                out[w] = said
    return out


def apply(text: str, lex: dict) -> str:
    """Respell the lexicon's names, the pinyin TERMS and vowel-less sound words in `text` for speaking."""
    text = apply_sounds(text)
    if lex:
        def name_run(m):
            words = m.group(0).split(" ")
            full = len(words) > 1
            start = m.start()
            sentence_start = start == 0 or re.search(r'(^|[.!?…]["”’]?\s+|\n\s*|["“]\s*)$', text[max(0, start - 4):start]) is not None
            out = []
            for w in words:
                say = lex.get(w)
                if say and (w not in _ENGLISH or full or not sentence_start):
                    out.append(say)
                else:
                    out.append(w)
            return " ".join(out)
        keys = sorted(lex, key=len, reverse=True)
        part = "|".join(re.escape(k) for k in keys)
        text = re.sub(rf"\b(?:{part})(?: (?:{part}))*\b", name_run, text)
    for k, v in TERMS.items():
        text = re.sub(rf"\b{k}\b", v, text, flags=re.IGNORECASE)
    return text
