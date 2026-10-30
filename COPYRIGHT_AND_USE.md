# Copyright and responsible use

NovelTea Engine is a tool for planning and writing **original** fiction. This page says what the software does with other people's
writing, where the line sits, and how to stay on the right side of it. It is not legal advice; the rules differ by country, and if
you plan to publish or sell what you make, check them (or ask a lawyer) for yours.

## The principle

Copyright protects an author's **expression** (their actual words, and distinctive creative arrangements of them), not the
**ideas, methods and general concepts** behind it. Learning how a genre works, how a long serial is paced, or how a hidden scheme is
planted and revealed, and then writing something new in your own voice, is ordinary practice. Copying passages, lightly rewording
them, or producing a close adaptation of someone's book is not, and owning a copy of a book does not give you the right to do it.

| What you want to do | Generally fine? |
|---|---|
| Learn a general technique (pacing, reveal timing, power curves) and use it in your own story | Yes |
| Combine lessons from many books into your own original work | Generally yes |
| Add your own characters, world, plot, examples and voice | Yes |
| Copy passages, or copy and change a few words | No: potential infringement |
| Reproduce an author's unique framework, scenes, characters or distinctive plot as your own | Permission may be needed |
| Rewrite a whole book (or its opening chapters) scene by scene in new words | May need permission, even if every sentence is new |

## What each part of NovelTea Engine does with source text

NovelTea Engine ships **no novels and no extracted data**. The corpus folder starts empty and is git-ignored; whatever you put in it stays on
your machine. There is **no downloader or scraper**: you add text yourself.

| Function | What it does | Where it sits |
|---|---|---|
| **Corpus extraction** (Corpus Builder, merge, summaries) | Reads chapters you upload and records structured facts about them: summaries, scheme and reveal patterns, power progression, pacing, character traits, plus a small number of short sample lines and excerpts used as voice data. | Analysis of text you uploaded. Only upload text you wrote, are licensed to use, or that is in the public domain. Keep extracted data private; do not publish it. |
| **Local semantic search** | Embeds your corpus on your machine (Ollama) so tools can find similar scenes and patterns. | Local, private. |
| **Author brains** | Reconstructs how an author planned: arcs, long secrets with seed, clue and reveal timing, working rules. | Ideas and methods, written as notes. |
| **Planning tools** (Conspiracy, Timeline, Arc planner, Lore, Cast, Author DNA) | Read the corpus as craft guidance, such as when to plant a clue and how long to wait before a reveal. Their prompts tell the model to learn the planning and never reuse names or events. | Ideas and methods. |
| **Chapter interview** (Generate) | The model writes one part at a time and offers three directions you choose between. | Original prose. The generator never splices or copies corpus text into chapters. Corpus voice excerpts, if any, reach the model as a "study, do not copy" style reference, and raw chapter text is not put into prompts. |
| **Corpus Reader and read-aloud** | Shows and reads the chapters in your own corpus on your own machine. | Personal use of text you uploaded; do not redistribute it. |

## Guidelines for using it well

1. **Learn the structure, then write your own story.** Use the planning tools for how a story is built, not as a source of scenes.
2. **Make it yours.** Your own cast, world, power system, plot and voice. If a reader of the source would recognise the scenes in
   order, you have adapted it, not been inspired by it.
3. **Do not copy.** If you notice generated text that reads like a known book, rewrite it from your own plan.
4. **Only add text you may use.** Your own writing, licensed material, public-domain works, or text the rights holder has permitted.
5. **Credit sources** where you rely on specific research or claims. Credit helps, but it is not permission to reproduce.
6. **Review before you publish or sell.** Check that the finished book is original and not a rewritten version of one author's work.
7. **Do not commit your corpus.** The `.gitignore` excludes it; keep it that way when you fork or contribute.

## Maintainers' commitments

- No novel text, extracted corpus data or keys in this repository.
- No scraping or download features.
- No features that copy corpus text into generated chapters.
- No feature re-writes a source book scene by scene, and none reproduces an author's characters or plot as your own.

Questions or concerns about the software's use of source text: please open an issue.
