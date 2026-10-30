import sys
import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".noveltea-engine" / "config.json"


# The corpus folder shipped with the repository: the pipeline scripts plus empty raw/ novels/ projects/ generated/ folders.
BUNDLED_CORPUS = Path(__file__).parent.parent.parent / "corpus"
CORPUS_SUBDIRS = ("raw", "novels", "projects", "generated")


def ensure_corpus_layout(path) -> None:
    """Make `path` a usable corpus folder: create the data folders and, if it is not the bundled folder, copy the pipeline scripts
    into it (the backend runs them from the corpus folder). Existing files are never overwritten. Safe to call on every start."""
    import shutil
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    for d in CORPUS_SUBDIRS:
        (p / d).mkdir(exist_ok=True)
    try:
        if BUNDLED_CORPUS.exists() and BUNDLED_CORPUS.resolve() != p.resolve():
            for f in list(BUNDLED_CORPUS.glob("*.py")) + [BUNDLED_CORPUS / "requirements.txt", BUNDLED_CORPUS / "SCHEMA_V3.md"]:
                if f.exists() and not (p / f.name).exists():
                    shutil.copy2(f, p / f.name)
    except Exception:
        pass


def _candidate_corpus_dirs():
    """Places to look for the NovelTea Engine corpus, in priority order.
    Works both from source and when frozen into a single exe."""
    cands = []
    # When frozen, the exe lives somewhere the user placed it — look nearby.
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        cands += [
            exe_dir / "NovelTea Engine",
            exe_dir.parent / "NovelTea Engine",
            exe_dir / "corpus",
        ]
    # Source-tree default: the repository's own (empty) corpus folder.
    cands.append(BUNDLED_CORPUS)
    return cands


def _is_populated_corpus(p: Path) -> bool:
    """A corpus dir that actually has extracted novels (not just an empty shell)."""
    nov = p / "novels"
    return nov.exists() and any(d.is_dir() for d in nov.iterdir())


def get_corpus_path() -> Path:
    """Return the path to the NovelTea Engine corpus directory.
    1) explicit config (~/.noveltea-engine/config.json),
    2) first candidate that actually CONTAINS novels (avoids picking an empty
       AppData shell created by a prior run),
    3) first merely-existing candidate, 4) source-tree default."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            if cfg.get("corpus_path"):
                return Path(cfg["corpus_path"])
        except Exception:
            pass
    cands = _candidate_corpus_dirs()
    # Prefer a candidate with real corpus content
    for c in cands:
        try:
            if _is_populated_corpus(c):
                return c
        except Exception:
            continue
    # Fall back to any existing dir, then the bundled (empty) corpus folder
    for c in cands:
        if c.exists():
            return c
    return BUNDLED_CORPUS

def set_corpus_path(path: str):
    ensure_corpus_layout(path)           # a new location is created and given the pipeline scripts + data folders
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    cfg["corpus_path"] = str(path)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

CORPUS_PATH = get_corpus_path()
try:
    ensure_corpus_layout(CORPUS_PATH)
except Exception:
    pass
NOVELS_PATH = CORPUS_PATH / "novels"
CHARACTER_DNA_PATH = CORPUS_PATH / "character_dna"
