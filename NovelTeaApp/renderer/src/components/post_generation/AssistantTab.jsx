import useStore from '../../store/useStore'
import { useEffect, useRef, useState } from 'react'
import { Spinner } from '../shared/projectUi'

/* ══════════════════════════════════════
   ASSISTANT TAB — whole-project agentic chatbot
   Greps the project workspace and can edit anything in the project
   (project.json systems/world/arcs/characters + chapter prose).
   Every turn is snapshotted server-side so it can be undone.
══════════════════════════════════════ */
// Provider/model selection lives ONLY in the top bar now (AgentEngineDropdown)
// — no per-tab duplicate. ASSISTANT_ENGINE_LABELS is just a display map for
// the small read-only badge in this tab's header.
export const ASSISTANT_ENGINE_LABELS = {
  claude: 'Claude Code', gemini: 'Gemini', qoder: 'Qoder', kimi: 'Kimi K3',
  nemotron: 'Nvidia (Nemotron)', ollama: 'Ollama', colibri: 'Colibrì (local)',
}

export function AssistantTab({ projectId, project, afterGenerate }) {
  // Conversation lives in the global store now (assistantChats[projectId]),
  // not local state — the backend endpoint is stateless (whole history
  // resent every call), so this WAS the only copy anywhere. Navigate away
  // mid-reply and it either landed on an unmounted component (silently
  // dropped) or the thread reset to empty on remount. Reading from the store
  // means switching tabs/pages and coming back shows the same conversation,
  // including a reply that finished while you were elsewhere.
  const { messages, loading } = useStore(s => s.assistantChats[projectId] || { messages: [], loading: false })
  const { sendAssistantMessage, undoAssistantMessage } = useStore()
  const [input, setInput] = useState('')
  const [undoing, setUndoing] = useState(null)   // snapshot_id currently being undone
  // Read-only: which engine/model answers this chat is set globally now, via
  // the top-bar AgentEngineDropdown — no per-tab picker, just a live reflection.
  const engines = useStore(s => s.agentEngines)
  const endRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, loading])

  async function send() {
    if (!input.trim() || loading) return
    const text = input
    setInput('')
    setTimeout(() => inputRef.current?.focus(), 20)
    await sendAssistantMessage(projectId, text, afterGenerate)
  }

  async function undo(msgIdx, snapshotId) {
    if (!snapshotId || undoing) return
    setUndoing(snapshotId)
    const err = await undoAssistantMessage(projectId, msgIdx, snapshotId, afterGenerate)
    if (err && err !== true) alert('Undo failed: ' + err)
    setUndoing(null)
  }

  const suggestions = [
    'Rename the protagonist everywhere (project + all chapters) to …',
    'Add a new faction to the Factions system that opposes the main sect',
    'Make the power levels in the world bible match the Power Levels system',
    'Find every chapter where the MC breaks through and list them',
  ]

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* header */}
      <div style={{ padding: '12px 18px', borderBottom: '1px solid var(--border-soft)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>✦ Project Assistant</div>
          {engines && (
            <div title="Set in the top bar — this chat always uses whatever engine is currently selected there" style={{
              fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 'var(--radius-sm)',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)',
              whiteSpace: 'nowrap',
            }}>
              {ASSISTANT_ENGINE_LABELS[engines.current] || engines.current}
            </div>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
          Reads &amp; greps the whole project and can edit anything — systems, world, arcs, characters, and chapter prose.
          Each change is snapshotted so you can Undo. The corpus stays read-only.
        </div>
      </div>

      {/* messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        {messages.length === 0 && !loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 620 }}>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              Ask me to change anything across <b>{project?.title || 'this project'}</b>. Examples:
            </div>
            {suggestions.map((s, i) => (
              <button key={i} onClick={() => setInput(s)} style={{
                textAlign: 'left', fontSize: 12, padding: '9px 12px', borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
              }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)' }}
              >{s}</button>
            ))}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} style={{
            alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
            maxWidth: '82%',
            padding: '10px 14px', borderRadius: 12,
            background: msg.role === 'user' ? 'var(--accent-dim)' : 'var(--bg-card)',
            border: msg.role === 'assistant' ? `1px solid ${msg.error ? 'var(--red)' : 'var(--border-soft)'}` : 'none',
            color: msg.error ? 'var(--red)' : 'var(--text-primary)',
            fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap',
          }}>
            {msg.content}
            {msg.role === 'assistant' && msg.snapshot_id && !msg.undone && (
              <div style={{ marginTop: 8 }}>
                <button onClick={() => undo(i, msg.snapshot_id)} disabled={undoing === msg.snapshot_id} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  fontSize: 11, fontWeight: 600, padding: '4px 10px', borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)',
                }}>
                  {undoing === msg.snapshot_id ? <Spinner size={10} /> : <span>⤺</span>}
                  {undoing === msg.snapshot_id ? 'Undoing…' : 'Undo these changes'}
                </button>
              </div>
            )}
            {msg.role === 'assistant' && msg.undone && (
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>⤺ Changes reverted</div>
            )}
          </div>
        ))}

        {loading && (
          <div style={{ alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-muted)', fontSize: 12 }}>
            <Spinner size={13} /> Working across the project…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* input */}
      <div style={{ padding: '12px 18px', borderTop: '1px solid var(--border-soft)', flexShrink: 0, display: 'flex', gap: 8 }}>
        <textarea
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
          disabled={loading}
          placeholder="Ask the assistant to change or find anything in the project…"
          rows={2}
          style={{
            flex: 1, resize: 'none', fontSize: 13, padding: '9px 12px',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)', fontFamily: 'inherit',
          }}
        />
        <button onClick={send} disabled={!input.trim() || loading} style={{
          alignSelf: 'stretch', padding: '0 18px', fontWeight: 700, fontSize: 14,
          background: (!input.trim() || loading) ? 'var(--bg-elevated)' : 'linear-gradient(135deg,#059669,#0891b2)',
          color: (!input.trim() || loading) ? 'var(--text-muted)' : '#fff',
          border: 'none', borderRadius: 'var(--radius-sm)',
        }}>
          {loading ? <Spinner size={13} /> : '↑'}
        </button>
      </div>
    </div>
  )
}
