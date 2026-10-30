import { useState } from 'react'
import useStore from '../store/useStore'
import { api } from '../api'

function Panel({ title, icon, color, children }) {
  return (
    <div style={{
      background: 'var(--bg-surface)', border: '1px solid var(--border)',
      borderTop: `2px solid ${color}`, borderRadius: 'var(--radius-lg)',
      padding: 16, display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 18 }}>{icon}</span>
        <span style={{ fontWeight: 700, fontSize: 13, color }}>{title}</span>
      </div>
      {children}
    </div>
  )
}

function LogBox({ logs }) {
  if (!logs || logs.length === 0) return null
  return (
    <div style={{
      background: 'var(--bg-base)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)', padding: '8px 10px',
      fontFamily: 'monospace', fontSize: 11, color: 'var(--green)',
      maxHeight: 120, overflowY: 'auto', whiteSpace: 'pre-wrap',
    }}>{logs.join('\n')}</div>
  )
}

function ResultBox({ result }) {
  if (!result) return null
  return (
    <div style={{
      background: 'var(--bg-base)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)', padding: '10px 12px',
      fontSize: 11, color: 'var(--text-secondary)',
      maxHeight: 200, overflowY: 'auto', whiteSpace: 'pre-wrap',
    }}>
      {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
    </div>
  )
}

export default function AIStudioPage() {
  const { registry, activeNovelId, engineRunning, runEngine } = useStore()
  const novels = registry?.novels || []
  const [novelId, setNovelId] = useState(activeNovelId || novels[0]?.id || '')
  const [chapterNum, setChapterNum] = useState(111)
  const [extractStart, setExtractStart] = useState(1)
  const [extractEnd, setExtractEnd] = useState(50)

  const [planResult, setPlanResult] = useState(null)
  const [genResult, setGenResult] = useState(null)
  const [extractResult, setExtractResult] = useState(null)
  const [validateResult, setValidateResult] = useState(null)
  const [logs, setLogs] = useState({})

  const addLog = (engine, msg) => setLogs(l => ({ ...l, [engine]: [...(l[engine] || []), msg] }))

  async function runPlan() {
    addLog('plan', `Planning chapter ${chapterNum} for ${novelId}...`)
    try {
      const r = await runEngine(() => api.planChapter(novelId, chapterNum))
      setPlanResult(r.plan)
      addLog('plan', r.logs || 'Done.')
    } catch (e) { addLog('plan', `Error: ${e.message}`) }
  }

  async function runGenerate() {
    addLog('gen', `Generating chapter ${chapterNum} for ${novelId}...`)
    try {
      const r = await runEngine(() => api.generateChapter(novelId, chapterNum))
      setGenResult(r.text || r.logs)
      addLog('gen', 'Generation complete.')
    } catch (e) { addLog('gen', `Error: ${e.message}`) }
  }

  async function runExtract() {
    addLog('extract', `Extracting chapters ${extractStart}-${extractEnd}...`)
    try {
      const r = await runEngine(() => api.extractChapters(novelId, extractStart, extractEnd))
      setExtractResult(r.logs)
      addLog('extract', 'Extraction complete.')
    } catch (e) { addLog('extract', `Error: ${e.message}`) }
  }

  async function runValidate() {
    addLog('validate', 'Validating novel...')
    try {
      const r = await runEngine(() => api.validateNovel(novelId))
      setValidateResult(r.conflicts)
      addLog('validate', r.logs || 'Validation complete.')
    } catch (e) { addLog('validate', `Error: ${e.message}`) }
  }

  const inp = (val, set, type = 'text') => (
    <input type={type} value={val} onChange={e => set(type === 'number' ? Number(e.target.value) : e.target.value)}
      style={{ padding: '5px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)', width: type === 'number' ? 70 : '100%' }} />
  )

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>AI Studio</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Active Novel:</span>
          <select value={novelId} onChange={e => setNovelId(e.target.value)}
            style={{ padding: '4px 8px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
            {novels.map(n => <option key={n.id} value={n.id}>{n.title}</option>)}
          </select>
        </div>
      </div>

      {engineRunning && (
        <div style={{
          background: 'var(--amber-dim)', border: '1px solid var(--amber)',
          borderRadius: 'var(--radius-sm)', padding: '8px 14px',
          fontSize: 12, color: 'var(--amber)', display: 'flex', alignItems: 'center', gap: 8,
        }}>⟳ Engine running — do not close the app</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>

        {/* Chapter Planner */}
        <Panel title="Chapter Planner" icon="◈" color="var(--accent)">
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Runs planner.py — analyses current story state and creates a structured chapter plan.
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>Chapter:</span>
            {inp(chapterNum, setChapterNum, 'number')}
          </div>
          <button onClick={runPlan} disabled={engineRunning || !novelId} style={{
            padding: '7px 14px', background: 'var(--accent)', color: '#fff',
            borderRadius: 'var(--radius-sm)', fontWeight: 600, fontSize: 12,
            opacity: engineRunning ? 0.5 : 1,
          }}>◈ Plan Chapter {chapterNum}</button>
          <LogBox logs={logs.plan} />
          {planResult && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 }}>PLAN OUTPUT</div>
              <ResultBox result={planResult} />
            </div>
          )}
        </Panel>

        {/* Chapter Generator */}
        <Panel title="Chapter Generator" icon="✎" color="var(--teal)">
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Runs generator.py — sends structured plan to Claude/GPT and writes the chapter.
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>Chapter:</span>
            {inp(chapterNum, setChapterNum, 'number')}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={async () => { await runPlan(); await runGenerate() }}
              disabled={engineRunning || !novelId} style={{
              padding: '7px 14px', background: 'var(--teal)', color: '#fff',
              borderRadius: 'var(--radius-sm)', fontWeight: 600, fontSize: 12,
              opacity: engineRunning ? 0.5 : 1, flex: 1,
            }}>✎ Plan + Generate</button>
            <button onClick={runGenerate} disabled={engineRunning || !novelId} style={{
              padding: '7px 14px', background: 'var(--bg-elevated)', color: 'var(--teal)',
              border: '1px solid var(--teal)', borderRadius: 'var(--radius-sm)', fontSize: 12,
              opacity: engineRunning ? 0.5 : 1,
            }}>Generate only</button>
          </div>
          <LogBox logs={logs.gen} />
          {genResult && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 }}>GENERATED TEXT</div>
              <ResultBox result={genResult} />
            </div>
          )}
        </Panel>

        {/* Extractor */}
        <Panel title="Story DNA Extractor" icon="◉" color="var(--amber)">
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Runs extract_v3.py — reads raw chapter files and extracts structured Story DNA.
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>Chapters:</span>
            {inp(extractStart, setExtractStart, 'number')}
            <span style={{ color: 'var(--text-muted)' }}>to</span>
            {inp(extractEnd, setExtractEnd, 'number')}
          </div>
          <button onClick={runExtract} disabled={engineRunning || !novelId} style={{
            padding: '7px 14px', background: 'var(--amber)', color: '#000',
            borderRadius: 'var(--radius-sm)', fontWeight: 600, fontSize: 12,
            opacity: engineRunning ? 0.5 : 1,
          }}>◉ Extract Chapters {extractStart}–{extractEnd}</button>
          <LogBox logs={logs.extract} />
          {extractResult && <ResultBox result={extractResult} />}
        </Panel>

        {/* Validator */}
        <Panel title="Continuity Validator" icon="◎" color="var(--green)">
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            Runs validate.py — checks power scaling, character consistency, timeline, lore, and active plot threads.
          </div>
          <button onClick={runValidate} disabled={engineRunning || !novelId} style={{
            padding: '7px 14px', background: 'var(--green)', color: '#000',
            borderRadius: 'var(--radius-sm)', fontWeight: 600, fontSize: 12,
            opacity: engineRunning ? 0.5 : 1,
          }}>◎ Validate {novelId}</button>
          <LogBox logs={logs.validate} />
          {validateResult && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 }}>
                {Array.isArray(validateResult) && validateResult.length === 0
                  ? '✓ No conflicts found'
                  : 'CONFLICTS DETECTED'}
              </div>
              <ResultBox result={validateResult} />
            </div>
          )}
        </Panel>

      </div>

      {/* AI Model config */}
      <div style={{
        background: 'var(--bg-surface)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)', padding: 16,
      }}>
        <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 12 }}>AI Model Configuration</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
          {[
            { label: 'Planning Model', value: 'claude-sonnet-5-5', color: 'var(--accent)' },
            { label: 'Writing Model',  value: 'claude-sonnet-5-5', color: 'var(--teal)' },
            { label: 'Validator Model',value: 'claude-haiku-4-5', color: 'var(--green)' },
            { label: 'Extractor Model',value: 'claude-sonnet-5-5', color: 'var(--amber)' },
          ].map(m => (
            <div key={m.label} style={{
              background: 'var(--bg-elevated)', border: `1px solid ${m.color}44`,
              borderRadius: 'var(--radius)', padding: '10px 12px',
            }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>{m.label}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: m.color }}>{m.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
