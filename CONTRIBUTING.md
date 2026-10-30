# Contributing

Thanks for helping. This is a solo project, so small, focused changes are easiest to review.

## Set up

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt pytest httpx
cd NovelTeaApp/renderer && npm ci
```

Run the backend (`cd NovelTeaApp/backend && python main.py`) and the UI (`cd NovelTeaApp/renderer && npm run dev`).

## Where things go

The code follows the three stages of writing a book. Put new work where it belongs:

| Stage | Backend (`NovelTeaApp/backend/routers/`) | UI (`NovelTeaApp/renderer/src/components/`) |
|---|---|---|
| Pre-generation: plan | `pre_generation/` | `pre_generation/` |
| Generation: write | `generation/` | `generation/` |
| Post-generation: read, check, polish | `post_generation/` | `post_generation/` |
| Corpus (optional) | `corpus_tools/` | `corpus/` |
| Projects, settings, system | `workspace/` | `shared/`, `layout/` |

A new backend router is one file in the right folder plus one `include_router` line in `backend/main.py`. A new tab is one component
file and one entry in the tab list in `pages/ProjectView.jsx`.

## Before you open a pull request

- `cd NovelTeaApp/backend && python -m pytest` passes (tests use a temporary home and corpus, never your data).
- `cd NovelTeaApp/renderer && npm run build` succeeds.
- No keys, tokens, personal paths, or corpus text in the diff. `corpus/` data folders are git-ignored; keep it that way.
- The app teaches craft and structure; it must never copy source text into a chapter. Read [COPYRIGHT_AND_USE.md](COPYRIGHT_AND_USE.md).
- Match the surrounding style. Keep comments short and about *why*.
