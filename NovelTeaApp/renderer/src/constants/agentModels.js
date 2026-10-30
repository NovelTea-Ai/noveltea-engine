// Per-provider model catalogs — single source of truth shared by SettingsPage
// (the per-engine model picker under Settings) and ProjectView's per-call
// override selector (Write Chapters card). Extracted from SettingsPage.jsx,
// which previously declared these locally with no other consumer; kept
// exactly as verified there (see each block's own provenance comment).

// Models the `claude -p` CLI can run — drives EVERY app AI button in CLI mode.
// Every id below was verified live against `claude -p --model <id>` on CLI
// 2.1.220 — a wrong id here fails every call with "model may not exist".
// Note there is no claude-haiku-5 (confirmed rejected), so Haiku stays on 4.5.
// claude-sonnet-5-5 verified on CLI 2.1.287 (older CLIs serve it too but warn it's not in their catalog).
export const CLI_MODELS = [
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5',  color: '#38bdf8',
    desc: 'Fastest, lightest on your subscription quota. Good for planning fields.' },
  { id: 'claude-sonnet-5-5',         label: 'Sonnet 5.5', color: '#22c55e',
    desc: 'Best prose quality — recommended for chapters. Uses quota faster.' },
  { id: 'claude-opus-5-5',           label: 'Opus 5.5',   color: '#a78bfa',
    desc: 'Highest quality, heaviest quota use. For final drafts.' },
  { id: 'claude-fable-5',            label: 'Fable 5',    color: '#f59e0b',
    desc: 'Anthropic’s most capable model. Heaviest quota use; needs a plan that includes Fable — your account currently reports no Fable credits.' },
]

// Pulled live from `codex debug models` (the real catalog Codex CLI sees),
// filtered to the entries marked visibility:"list" — the same ones the CLI's
// own /model picker shows. gpt-reserve and codex-auto-review are
// visibility:"hide" (internal/system use) and deliberately excluded.
export const CODEX_MODELS = [
  { id: 'gpt-5.6-terra', label: 'GPT-5.6 Terra', color: '#10a37f',
    desc: 'Balanced agentic coding model for everyday work. Codex CLI\'s default.' },
  { id: 'gpt-5.6-luna', label: 'GPT-5.6 Luna', color: '#34d399',
    desc: 'Fast and affordable agentic coding model.' },
  { id: 'gpt-5.5', label: 'GPT-5.5', color: '#38bdf8',
    desc: 'Proven previous-generation model for coding and general work.' },
  { id: 'gpt-5.4-mini', label: 'GPT-5.4 Mini', color: '#a78bfa',
    desc: 'Small, fast, and cost-efficient model for simpler coding tasks.' },
]

// Model ids taken from @google/gemini-cli 0.61's own model constants (DEFAULT_GEMINI_FLASH_MODEL,
// LATEST_GEMINI_FLASH_MODEL, PREVIEW_GEMINI_3_1_MODEL, DEFAULT_GEMINI_MODEL, LATEST_GEMINI_FLASH_LITE_MODEL)
// — the ids the installed CLI itself knows, not a guessed list. Which ones a given Google account can
// use depends on that account's plan.
export const GEMINI_MODELS = [
  { id: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash', color: '#4285f4',
    desc: 'The Gemini CLI\'s own default Flash model — fast, and the safest choice for free Google accounts.' },
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', color: '#22c55e',
    desc: 'The newest Flash model the CLI knows about.' },
  { id: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro', color: '#a78bfa',
    desc: 'Pro preview — strongest reasoning the CLI offers, slower, and may need a paid plan.' },
  { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro', color: '#38bdf8',
    desc: 'The CLI\'s stable Pro default.' },
  { id: 'gemini-3.5-flash-lite', label: '3.5 Flash-Lite', color: '#94a3b8',
    desc: 'Lightest and quickest; fine for simple fields, weaker on long extraction.' },
]

// Verified live against integrate.api.nvidia.com — all of these accept the
// tool-calling schema the agent engine depends on.
export const NEMOTRON_MODELS = [
  { id: 'nvidia/nemotron-3-ultra-550b-a55b', label: 'Ultra 550B', color: '#76b900',
    desc: 'Flagship MoE (550B/55B active) — strongest reasoning, slowest. Default.' },
  { id: 'nvidia/nemotron-3-super-120b-a12b', label: 'Super 120B', color: '#8fd400',
    desc: 'Mid-tier MoE (120B/12B active) — balances quality and latency.' },
  // Nano 30B (nemotron-3-nano-30b-a3b) and Nano 9B v2 were retired by NVIDIA on
  // 2026-09-01 (HTTP 410 Gone) and removed from this list.
  { id: 'nvidia/nemotron-3.5-lightning-30b-a3b', label: 'Lightning 30B', color: '#a3e635',
    desc: 'Small MoE (30B/3B active) — fast, good for routine edits.' },
]

// Keyed by agentEngines.current — the id SettingsPage's engine picker and
// this app's store already use ('claude' | 'codex' | 'gemini' | 'nemotron' |
// 'ollama'). No static list for 'ollama' — its models are whatever the user
// has locally pulled, not a fixed catalog; callers should treat a missing
// entry here as "no override available, use the Settings default".
export const MODELS_BY_PROVIDER = {
  claude: CLI_MODELS,
  codex: CODEX_MODELS,
  gemini: GEMINI_MODELS,
  nemotron: NEMOTRON_MODELS,
}
