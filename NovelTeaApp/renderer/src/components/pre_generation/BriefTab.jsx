import { useEffect, useState } from 'react'
import { FieldSurveyButton, Panel, PanelTitle, Spinner } from '../shared/projectUi'

// Standard web-novel genre tags (multi-select; custom tags allowed)
export const GENRE_TAGS = [
  'Action','Adult','Adventure','Comedy','Drama','Ecchi','Fantasy','Gender Bender',
  'Harem','Historical','Horror','Josei','Game','Martial Arts','Mature','Mecha',
  'Mystery','Psychological','Romance','School Life','Sci-fi','Seinen','Shoujo',
  'Shounen Ai','Shounen','Slice of Life','Smut','Sports','Supernatural','Tragedy',
  'Wuxia','Xianxia','Xuanhuan','Yaoi','Eastern','Reincarnation',
]

/* ══════════════════════════════════════
   CREATIVE BRIEF TAB
══════════════════════════════════════ */
export const THEME_OPTIONS = ['Power','Identity','Destiny','Revenge','Redemption','Loyalty','Betrayal','Family','Freedom','Sacrifice','Love','Honor','Survival','Truth','Ambition','Justice']

export function BriefTab({ brief, setLocalBrief, project, onSave, saving, projectId, afterGenerate }) {
  const [form, setForm] = useState({
    premise: brief.premise || '',
    tagline: project.tagline || '',
    themes: brief.themes || [],
    genre_tags: project.genre_tags || [],
    reader_experience: brief.reader_experience || { epicness: 5, comedy: 4, mystery: 6, romance: 3, adventure: 7 },
  })

  useEffect(() => {
    setForm({
      premise: brief.premise || '',
      tagline: project.tagline || '',
      themes: brief.themes || [],
      genre_tags: project.genre_tags || [],
      reader_experience: brief.reader_experience || { epicness: 5, comedy: 4, mystery: 6, romance: 3, adventure: 7 },
    })
  }, [project.id])

  function toggleTheme(t) {
    setForm(f => ({ ...f, themes: f.themes.includes(t) ? f.themes.filter(x => x !== t) : [...f.themes, t] }))
  }

  function toggleGenreTag(t) {
    setForm(f => ({ ...f, genre_tags: f.genre_tags.includes(t) ? f.genre_tags.filter(x => x !== t) : [...f.genre_tags, t] }))
  }

  async function handleSave() {
    const updatedBrief = { ...brief, premise: form.premise, themes: form.themes, reader_experience: form.reader_experience }
    setLocalBrief(updatedBrief)
    await onSave({ creative_brief: updatedBrief, tagline: form.tagline, genre_tags: form.genre_tags })
  }

  const RE_SLIDERS = [
    { key: 'epicness',  label: 'Epicness',  color: 'var(--accent)' },
    { key: 'comedy',    label: 'Comedy',    color: 'var(--amber)' },
    { key: 'mystery',   label: 'Mystery',   color: 'var(--cyan)' },
    { key: 'romance',   label: 'Romance',   color: 'var(--pink)' },
    { key: 'adventure', label: 'Adventure', color: 'var(--teal)' },
    { key: 'tragedy',   label: 'Tragedy',   color: 'var(--red)' },
  ]

  function onGenDone(res) {
    afterGenerate(res)
    if (res.field === 'premise' && res.result) setForm(f => ({ ...f, premise: res.result }))
    if (res.field === 'tagline' && res.result) setForm(f => ({ ...f, tagline: res.result }))
    if (res.field === 'themes' && res.result)  setForm(f => ({ ...f, themes: res.result }))
  }

  return (
    <div className="split-flex" style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', gap: 16 }}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 14 }}>

        <Panel>
          <PanelTitle action={<FieldSurveyButton field="premise" projectId={projectId} onDone={onGenDone} small />}>Premise</PanelTitle>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
            The core conflict, protagonist, stakes, and world hook. 1–3 sentences.
          </div>
          <textarea value={form.premise} onChange={e => setForm(f => ({ ...f, premise: e.target.value }))}
            placeholder={`In a world where cultivation determines rank, ${project.protagonist_name || 'the protagonist'} discovers a forgotten technique that challenges the entire hierarchy…`}
            rows={5} style={{ width: '100%', padding: '10px 12px', fontSize: 12, borderRadius: 'var(--radius)', resize: 'vertical', lineHeight: 1.6 }}
          />
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 5 }}>{form.premise.length} chars</div>
        </Panel>

        <Panel>
          <PanelTitle action={<FieldSurveyButton field="tagline" projectId={projectId} onDone={onGenDone} small />}>Tagline</PanelTitle>
          <input value={form.tagline} onChange={e => setForm(f => ({ ...f, tagline: e.target.value }))}
            placeholder="One line. Bold. Under 15 words."
            style={{ width: '100%', padding: '7px 10px', fontSize: 13, fontStyle: 'italic', borderRadius: 'var(--radius-sm)' }}
          />
        </Panel>

        <Panel>
          <PanelTitle action={<FieldSurveyButton field="themes" projectId={projectId} onDone={onGenDone} small />}>Themes</PanelTitle>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
            {THEME_OPTIONS.map(t => (
              <button key={t} onClick={() => toggleTheme(t)} style={{
                padding: '4px 12px', fontSize: 11, borderRadius: 20,
                background: form.themes.includes(t) ? 'var(--accent)' : 'var(--bg-elevated)',
                border: `1px solid ${form.themes.includes(t) ? 'var(--accent)' : 'var(--border)'}`,
                color: form.themes.includes(t) ? '#fff' : 'var(--text-secondary)',
                transition: 'all 0.1s',
              }}>{t}</button>
            ))}
          </div>
          <input placeholder="+ custom theme (Enter to add)"
            style={{ width: '100%', padding: '5px 10px', fontSize: 11, borderRadius: 'var(--radius-sm)' }}
            onKeyDown={e => { if (e.key === 'Enter' && e.target.value.trim()) { toggleTheme(e.target.value.trim()); e.target.value = '' } }}
          />
        </Panel>

        <Panel>
          <PanelTitle>Genre Tags</PanelTitle>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8 }}>
            Standard web-novel genre tags. Select any that apply, or add your own.
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
            {[...GENRE_TAGS, ...form.genre_tags.filter(t => !GENRE_TAGS.includes(t))].map(t => {
              const on = form.genre_tags.includes(t)
              const isCustom = !GENRE_TAGS.includes(t)
              return (
                <button key={t} onClick={() => toggleGenreTag(t)} title={isCustom ? 'Custom tag' : undefined} style={{
                  padding: '4px 12px', fontSize: 11, borderRadius: 20,
                  background: on ? 'var(--accent)' : 'var(--bg-elevated)',
                  border: `1px solid ${on ? 'var(--accent)' : (isCustom ? 'var(--accent-light)' : 'var(--border)')}`,
                  color: on ? '#fff' : 'var(--text-secondary)',
                  transition: 'all 0.1s',
                }}>{isCustom && !on ? '＋ ' : ''}{t}</button>
              )
            })}
          </div>
          <input placeholder="+ custom genre tag (Enter to add)"
            style={{ width: '100%', padding: '5px 10px', fontSize: 11, borderRadius: 'var(--radius-sm)' }}
            onKeyDown={e => { if (e.key === 'Enter' && e.target.value.trim()) { toggleGenreTag(e.target.value.trim()); e.target.value = '' } }}
          />
        </Panel>
      </div>

      <div className="split-flex-sidebar" style={{ width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Panel>
          <PanelTitle>Reader Experience</PanelTitle>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 10 }}>Target intensities (0–10)</div>
          {RE_SLIDERS.map(s => (
            <div key={s.key} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{s.label}</span>
                <span style={{ fontSize: 11, color: s.color, fontWeight: 700 }}>{form.reader_experience[s.key] ?? 5}</span>
              </div>
              <input type="range" min={0} max={10} value={form.reader_experience[s.key] ?? 5}
                onChange={e => setForm(f => ({ ...f, reader_experience: { ...f.reader_experience, [s.key]: Number(e.target.value) } }))}
                style={{ width: '100%', accentColor: s.color, height: 4 }} />
            </div>
          ))}
        </Panel>

        <button onClick={handleSave} disabled={saving} className="btn-primary" style={{ width: '100%', padding: '10px', fontSize: 13 }}>
          {saving ? <Spinner /> : '✓ Save Brief'}
        </button>
      </div>
    </div>
  )
}
