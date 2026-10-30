import { useEffect, useState } from 'react'
import { api } from '../../api'
import NeuralBrain from './NeuralBrain'

/* Corpus teapot — the 3D node mesh (a teapot pouring into a teacup) driven by real corpus data.
   Each novel owns a slice of the teapot; click any node to fire that novel's
   region and inspect its data. The teacup = the pipeline, the stream = the core.
   Stat tiles live OUTSIDE the canvas so the teapot gets the whole graphic space
   (especially on mobile). */

export default function BrainGraph({ height = 460, isMobile = false }) {
  const [data, setData] = useState(null)
  const [sel, setSel] = useState(null)

  useEffect(() => {
    api.brainGraph().then(setData).catch(() => setData({ nodes: [], totals: {}, novel_count: 0 }))
  }, [])

  if (!data) {
    return <div style={{ height, display: 'grid', placeItems: 'center', color: 'var(--text-muted)' }}>Loading teapot…</div>
  }

  const totals = data.totals || {}
  const novel = sel?.type === 'novel' ? sel.novel : null

  return (
    <div style={{ width: '100%' }}>
      {/* ── the graphic space: the teapot only ── */}
      <div style={{
        position: 'relative', width: '100%', height,
        borderRadius: 12, overflow: 'hidden',
        border: '1px solid rgba(139,47,214,0.35)', background: '#000',
      }}>
        <NeuralBrain data={data} interactive onSelect={setSel} />

        {/* HUD */}
        <div style={{ position: 'absolute', left: 14, top: 12, pointerEvents: 'none' }}>
          <div style={{
            fontSize: isMobile ? 11 : 13, fontWeight: 600, letterSpacing: '0.35em',
            textTransform: 'uppercase', color: '#d9c8ff',
            fontFamily: "ui-monospace,'SF Mono',Menlo,Consolas,monospace",
          }}>Corpus Teapot</div>
          <div style={{
            fontSize: 10, letterSpacing: '0.12em', color: '#8a7fa8', marginTop: 4,
            fontFamily: "ui-monospace,'SF Mono',Menlo,Consolas,monospace",
          }}>
            {data.novel_count} NOVELS · {(totals.chapters ?? 0).toLocaleString()} CHAPTERS · LIVE
          </div>
        </div>

        {/* hint (desktop only) */}
        {!isMobile && (
          <div style={{
            position: 'absolute', right: 14, bottom: 12, textAlign: 'right', pointerEvents: 'none',
            color: '#8a7fa8', fontSize: 10, letterSpacing: '0.15em', lineHeight: 1.9,
            fontFamily: "ui-monospace,'SF Mono',Menlo,Consolas,monospace",
          }}>
            DRAG TO ROTATE<br />CLICK A NODE TO FIRE IT<br />SCROLL TO ZOOM
          </div>
        )}

        {/* inspector panel */}
        {sel && (
          <div style={{
            position: 'absolute', left: 14, bottom: 12, zIndex: 5,
            minWidth: 210, maxWidth: isMobile ? 'calc(100% - 28px)' : 300,
            background: 'rgba(12,6,24,0.85)', border: '1px solid rgba(139,47,214,0.45)',
            borderRadius: 10, padding: '12px 14px', color: '#e9e4f5',
            backdropFilter: 'blur(8px)', pointerEvents: 'none',
            fontFamily: "ui-monospace,'SF Mono',Menlo,Consolas,monospace",
          }}>
            <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.08em', color: '#e3b8ff' }}>
              {novel ? novel.id.replace(/_/g, ' ') : sel.region}
            </div>
            <div style={{ fontSize: 10, color: '#8a7fa8', marginTop: 6, lineHeight: 1.7, letterSpacing: '0.05em' }}>
              NODE <b style={{ color: '#7fd4ff', fontWeight: 600 }}>#{String(sel.nodeIndex).padStart(3, '0')}</b>
              {' · '}LINKS <b style={{ color: '#7fd4ff', fontWeight: 600 }}>{sel.synapses}</b>
            </div>
            {novel ? (
              <div style={{ marginTop: 8 }}>
                {[
                  ['Chapters', novel.chapters],
                  ['Reader psych', novel.psych],
                  ['Reveals', novel.reveals],
                  ['Prose samples', novel.prose],
                  ['Schemes', novel.schemes || '—'],
                  ['Arcs', novel.arcs],
                  ['Genome', novel.has_genome ? `v${novel.genome_version} · ${novel.genome_patterns} patterns` : '—'],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, padding: '2px 0' }}>
                    <span style={{ color: '#8a7fa8' }}>{k}</span>
                    <span style={{ color: '#b9e2ff', fontWeight: 600 }}>{typeof v === 'number' ? v.toLocaleString() : v}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 10, color: '#b9aed6', marginTop: 8, lineHeight: 1.55 }}>{sel.desc}</div>
            )}
          </div>
        )}
      </div>

      {/* ── stat tiles: OUTSIDE the graphic space ── */}
      <div style={{
        display: 'grid', gap: 8, marginTop: 10,
        gridTemplateColumns: isMobile ? 'repeat(4, 1fr)' : 'repeat(8, 1fr)',
      }}>
        <Stat label="Novels" value={data.novel_count} />
        <Stat label="Chapters" value={totals.chapters} />
        <Stat label="Psych" value={totals.psych} />
        <Stat label="Reveals" value={totals.reveals} />
        <Stat label="Prose" value={totals.prose} />
        <Stat label="Schemes" value={totals.schemes} />
        <Stat label="Arcs" value={totals.arcs} />
        <Stat label="Genomes" value={totals.genomes} accent />
      </div>
    </div>
  )
}

function Stat({ label, value, accent }) {
  return (
    <div style={{
      padding: '8px 6px', borderRadius: 8, textAlign: 'center',
      background: 'var(--bg-surface, rgba(8,14,24,0.6))',
      border: `1px solid ${accent ? 'rgba(52,211,153,0.5)' : 'var(--border-soft, rgba(255,255,255,0.08))'}`,
      minWidth: 0,
    }}>
      <div style={{
        fontSize: 16, fontWeight: 800, color: accent ? '#34d399' : 'var(--text-primary, #dceeff)',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{(value ?? 0).toLocaleString()}</div>
      <div style={{
        fontSize: 9, letterSpacing: '0.12em', color: 'var(--text-muted, #5b7a99)', textTransform: 'uppercase', marginTop: 2,
      }}>{label}</div>
    </div>
  )
}
