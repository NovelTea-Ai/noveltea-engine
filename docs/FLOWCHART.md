# How NovelTea Engine works: flow charts

Diagrams are [Mermaid](https://mermaid.js.org/); GitHub renders them in this page.

## 1. The big picture

```mermaid
flowchart LR
    subgraph YOU["You"]
        U1["Your own text<br/>(.txt chapters you may use)"]
        U2["Your story ideas<br/>premise, cast, world, voice"]
    end

    subgraph CORPUS["Corpus (optional, local, git-ignored)"]
        C1["Corpus Builder<br/>upload your .txt chapters"]
        C2["Extraction pipeline<br/>structured facts per chapter"]
        C3["Local semantic search<br/>(Ollama embeddings)"]
        C4["Author brains<br/>how arcs and secrets were planned"]
    end

    subgraph PLAN["Plan: pre-generation tabs"]
        P1["Creative Brief, Author DNA,<br/>Characters, Systems, Lore"]
        P2["Conspiracy tree, Timeline,<br/>Arc planner, Chapter skeletons"]
    end

    subgraph WRITE["Write"]
        W1["Chapter interview<br/>pick 1 of 3 directions per step"]
        W2["Chapters saved to<br/>corpus/generated/"]
    end

    subgraph POST["Polish: post-writing tools"]
        T1["Reader, Editor, Critique,<br/>Revision, Continuity, Dialogue"]
    end

    ENGINE["AI engine you choose<br/>Claude, Gemini, NVIDIA, or local Ollama"]

    U1 --> C1 --> C2 --> C3
    C2 --> C4
    C3 -. "craft guidance only" .-> P2
    C4 -. "craft guidance only" .-> P2
    U2 --> P1 --> P2 --> W1 --> W2 --> T1
    ENGINE <--> C2
    ENGINE <--> P2
    ENGINE <--> W1
    ENGINE <--> T1
```

The corpus never feeds text into chapters. It informs *structure and craft* (when to plant a clue, how long arcs run) and the planning
tools are told to learn the planning, never to reuse names or events. See [COPYRIGHT_AND_USE.md](../COPYRIGHT_AND_USE.md).

## 2. Building a corpus (optional)

```mermaid
flowchart TD
    A["Corpus Builder: add a novel<br/>creates raw/&lt;novel_id&gt;/"] --> B["Upload plain-text chapters<br/>ch1.txt, ch2.txt ... (text you may use)"]
    B --> Q["Extraction queue<br/>one worker per engine key"]
    Q --> X["Extract each chapter in parts<br/>voice, plot, world, prose"]
    X --> V{"Quality checks<br/>complete and consistent?"}
    V -- "no: retry or repair" --> X
    V -- yes --> M["Merge into the novel's records<br/>novels/&lt;id&gt;/"]
    M --> R["Resolve conflicts"]
    R --> G["Narrative genome<br/>patterns across the novel"]
    R --> S["Rolling summary<br/>story so far"]
    G --> I["Knowledge index<br/>local embeddings in a SQLite file"]
    S --> I
    I --> AB["Author brain<br/>Python + semantic search first,<br/>then an AI pass with search and grep tools"]
    AB --> I2["Index the author brain<br/>arcs, threads, craft rules"]
    I --> OUT["Used by Conspiracy, Timeline,<br/>Arc planner, Lore, Cast, Author DNA"]
    I2 --> OUT
```

## 3. From idea to finished chapter

```mermaid
flowchart TD
    N["New Project wizard<br/>Guided Setup, Manual, or Corpus Template"] --> P["Project created<br/>title, genre, premise, POV, protagonist, power system"]
    P --> T["Fill the pre-generation tabs<br/>(AI assist on any field)"]

    T --> T1["Brief + Author DNA<br/>themes, reader experience, voice"]
    T --> T2["Characters, Cast roster, Antagonists"]
    T --> T3["Systems + Lore<br/>power levels, world rules, why things happen"]
    T --> T4["Conspiracy tree + Timeline<br/>hidden schemes, clues, reveals"]
    T --> T5["Arc planner, Chapter skeletons, Scene plans"]

    T1 --> G
    T2 --> G
    T3 --> G
    T4 --> G
    T5 --> G
    G["Generate: chapter interview starts"]

    G --> R1["Write the next part of the chapter"]
    R1 --> GATE{"House-style gate<br/>passes?"}
    GATE -- "no: auto-retry" --> R1
    GATE -- "still failing" --> KEEP["You decide:<br/>keep as written, or try again"]
    KEEP --> R1
    GATE -- yes --> Q["Show 3 genuinely different directions<br/>with the reason for each"]
    Q --> CH["You choose one, or write your own<br/>(Back is always available)"]
    CH --> MORE{"Chapter complete?"}
    MORE -- no --> R1
    MORE -- yes --> SAVE["Chapter saved<br/>corpus/generated/&lt;project&gt;/"]

    SAVE --> POST["Post-writing tools"]
    POST --> P1["Reader and Editor"]
    POST --> P2["Critique and Revision"]
    POST --> P3["Continuity and Facts"]
    POST --> P4["Dialogue shaping, Humor, Combat"]
    P1 --> NEXT["Next chapter"]
    P2 --> NEXT
    P3 --> NEXT
    P4 --> NEXT
    NEXT --> G
```

## 4. Where your data and keys go

```mermaid
flowchart LR
    subgraph LOCAL["Your computer"]
        APP["NovelTea Engine app<br/>listens on 127.0.0.1 only"]
        CORP["corpus/ folder<br/>(or the folder you choose in Settings)"]
        CFG["~/.noveltea-engine/config.json<br/>your API keys, outside the repo"]
        OLL["Ollama (optional)<br/>local models + embeddings"]
    end

    ENG["AI engine you select"]

    APP <--> CORP
    APP --> CFG
    APP <--> OLL
    APP -- "prompts and chapter text<br/>only to the engine you pick" --> ENG

    GIT["Git repository"]
    CORP -. "ignored: never committed" .-> GIT
    CFG -. "never in the repo" .-> GIT
```

- Choose a **local Ollama model** to keep everything on your machine.
- To use the app from a phone or another PC, opt in with `NOVELTEA_HOST` (see the README) and only on a network you trust.
