import { useState, useEffect, useRef } from 'react'
import useStore from '../../store/useStore'
import { api } from '../../api'

const SETUP_MODES = [
  {
    id: 'blueprint',
    icon: '✦',
    label: 'Guided Setup (AI later)',
    desc: 'Answer the wizard (genre, DNA, culture, inspirations) → the project is created with all of it filled in. Then build the premise, cast, systems, arcs and chapter plans with the AI, tab by tab, in the project.',
  },
  {
    id: 'manual',
    icon: '✎',
    label: 'Manual + AI Assist',
    desc: 'Create the project with the basics and fill each pre-generation tab yourself, with AI assist on any field.',
  },
  {
    id: 'template',
    icon: '⊕',
    label: 'Corpus Template',
    desc: 'Pick inspiration novels → NovelTea Engine blends their Story DNA into a starting template. You edit from there.',
  },
]

// where a new project goes next: the pre-generation tabs the chapter generator reads (ids from ProjectView's tab list)
const NEXT_TABS = [
  { tab: 'brief', label: 'Creative Brief' },
  { tab: 'author', label: 'Author DNA' },
  { tab: 'characters', label: 'Characters' },
  { tab: 'systems', label: 'Systems' },
  { tab: 'arcs', label: 'Arc Planner' },
]

const GENRES = ['Cultivation','LitRPG','Xianxia','Xuanhuan','Academy','Kingdom Building','Political','Romance','Mystery','Horror','Sci-Fi','Fantasy','Slice of Life']
const SUBGENRES = ['Power Fantasy','Dark Comedy','Revenge','Hidden Identity','Tournament Arc','Political Intrigue','Alchemy','Beast Taming','Reincarnation','System']
// Standard web-novel genre tags (multi-select, custom tags allowed)
export const GENRE_TAGS = [
  'Action','Adult','Adventure','Comedy','Drama','Ecchi','Fantasy','Gender Bender',
  'Harem','Historical','Horror','Josei','Game','Martial Arts','Mature','Mecha',
  'Mystery','Psychological','Romance','School Life','Sci-fi','Seinen','Shoujo',
  'Shounen Ai','Shounen','Slice of Life','Smut','Sports','Supernatural','Tragedy',
  'Wuxia','Xianxia','Xuanhuan','Yaoi','Eastern','Reincarnation',
]
const AUDIENCES = ['Young Adult','Adult','All Ages','Mature']
const CULTURES = ['Chinese','Japanese','Korean','Western','European','Middle Eastern','Indian','African','Latin American','Nordic','Original']

const DNA_SLIDERS = [
  { key: 'power_fantasy',    label: 'Power Fantasy',    color: 'var(--accent)' },
  { key: 'conflict',         label: 'Conflict & Violence', color: 'var(--red)',
    desc: 'How much direct antagonism, physical danger, and fighting appear from early chapters — bullies, rivals, assassins, hunts, extortion. Low = slow-burn/mystery-paced tension; high = the protagonist is in real physical danger within the first few chapters and it keeps escalating.' },
  { key: 'comedy',           label: 'Comedy',           color: 'var(--amber)' },
  { key: 'mystery',          label: 'Mystery',          color: 'var(--cyan)' },
  { key: 'romance',          label: 'Romance',          color: 'var(--pink)' },
  { key: 'politics',         label: 'Politics',         color: 'var(--purple)' },
  { key: 'adventure',        label: 'Adventure',        color: 'var(--teal)' },
  { key: 'kingdom_building', label: 'Kingdom Building', color: 'var(--green)' },
  { key: 'cultivation',      label: 'Cultivation',      color: 'var(--orange)' },
  { key: 'tragedy',          label: 'Tragedy',          color: 'var(--red)' },
]

// Conflict archetypes as short "X vs Y" template chips — grepped from real
// schemes/instances.json data across the corpus novels (hundreds of
// scheme instances surveyed). Clicking one appends it to
// Value Conflicts so the author doesn't have to type conflict ideas from
// scratch — same corpus grounding as the backend's _CONFLICT_ARCHETYPES.
const CONFLICT_TEMPLATES = [
  { label: 'Coveted treasure, many eyes watching', value: 'protagonist holds a coveted treasure many rivals want' },
  { label: 'Privileged bully with powerful backing', value: 'a privileged bully with powerful family/sect backing torments the protagonist' },
  { label: 'Hidden assassination order', value: 'a hidden enemy has secretly ordered the protagonist killed or captured' },
  { label: 'Group hunt — many vs one', value: 'a coalition of rivals hunts the protagonist together during a trial or open event' },
  { label: 'Corrupt authority abuses power', value: 'a corrupt superior or official abuses their authority over the protagonist' },
  { label: 'Predatory debt / entrapment', value: 'an enemy lures the protagonist into crippling debt or a rigged deal to trap them' },
  { label: 'Economic / reputation warfare', value: 'a rival family wages economic and reputation warfare before resorting to violence' },
  { label: 'False frame-up', value: 'the protagonist is falsely accused by someone with family or legal backing' },
  { label: 'Entitled prince/noble preys on the weak', value: 'an entitled noble or prince treats the protagonist or their people as property or sport' },
  { label: 'Oppressed village vs ruling power', value: "the protagonist's village or clan is being crushed by a far stronger ruling power" },
  { label: 'Treasure falls into your lap — everyone else wants it too', value: 'a treasure falls into the protagonist\'s hands in front of many powerful fighters competing for it, forcing them to flee rather than fight' },
]

const CULT_SLIDERS = [
  { key: 'hierarchy',      label: 'Hierarchy' },
  { key: 'individualism',  label: 'Individualism' },
  { key: 'family',         label: 'Family Importance' },
  { key: 'honor',          label: 'Honor' },
  { key: 'revenge',        label: 'Revenge Acceptance' },
  { key: 'romance_open',   label: 'Romance Openness' },
]

function Overlay({ children }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.8)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      {children}
    </div>
  )
}

function Step({ n, label, active, done }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{
        width: 22, height: 22, borderRadius: '50%',
        background: done ? 'var(--green)' : active ? 'var(--accent)' : 'var(--bg-elevated)',
        border: `1.5px solid ${done ? 'var(--green)' : active ? 'var(--accent)' : 'var(--border)'}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 700,
        color: done || active ? '#fff' : 'var(--text-muted)',
        flexShrink: 0,
      }}>{done ? '✓' : n}</div>
      <span style={{ fontSize: 11, color: active ? 'var(--text-primary)' : 'var(--text-muted)' }}>{label}</span>
    </div>
  )
}

function Slider({ label, value, onChange, color = 'var(--accent)', desc = '' }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }} title={desc}>{label}</span>
        <span style={{ fontSize: 11, color, fontWeight: 600 }}>{value}</span>
      </div>
      <input type="range" min={0} max={10} value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ width: '100%', accentColor: color, height: 4 }}
        title={desc}
      />
      {desc && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{desc}</div>}
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <label style={{ display: 'block', fontSize: 11, color: 'var(--text-secondary)', marginBottom: 5, fontWeight: 600 }}>{label}</label>
      {children}
    </div>
  )
}

function Input({ value, onChange, placeholder }) {
  return (
    <input
      value={value} onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}
    />
  )
}

function Select({ value, onChange, options }) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }}>
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  )
}

function TagSelect({ options, selected, onToggle }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
      {options.map(o => (
        <button key={o} onClick={() => onToggle(o)} style={{
          padding: '3px 10px', fontSize: 11, borderRadius: 10,
          background: selected.includes(o) ? 'var(--accent)' : 'var(--bg-elevated)',
          border: `1px solid ${selected.includes(o) ? 'var(--accent)' : 'var(--border)'}`,
          color: selected.includes(o) ? '#fff' : 'var(--text-secondary)',
          transition: 'all 0.1s',
        }}>{o}</button>
      ))}
    </div>
  )
}

// Tag selector that also lets the user type and add their own custom tags.
export function TagSelectWithCustom({ options, selected, onToggle }) {
  const [custom, setCustom] = useState('')
  // Show preset options plus any selected tags that aren't in the presets (custom ones)
  const allOptions = [...options, ...selected.filter(s => !options.includes(s))]

  function addCustom() {
    const t = custom.trim()
    if (!t) return
    if (!selected.includes(t)) onToggle(t)
    setCustom('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
        {allOptions.map(o => {
          const isCustom = !options.includes(o)
          const on = selected.includes(o)
          return (
            <button key={o} onClick={() => onToggle(o)} title={isCustom ? 'Custom tag' : undefined} style={{
              padding: '3px 10px', fontSize: 11, borderRadius: 10,
              background: on ? 'var(--accent)' : 'var(--bg-elevated)',
              border: `1px solid ${on ? 'var(--accent)' : (isCustom ? 'var(--accent-light)' : 'var(--border)')}`,
              color: on ? '#fff' : 'var(--text-secondary)',
              transition: 'all 0.1s',
            }}>{isCustom && !on ? '＋ ' : ''}{o}</button>
          )
        })}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={custom}
          onChange={e => setCustom(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCustom() } }}
          placeholder="Add a custom tag…"
          style={{
            flex: 1, fontSize: 11, padding: '5px 9px',
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)', color: 'var(--text-primary)',
          }}
        />
        <button onClick={addCustom} disabled={!custom.trim()} style={{
          fontSize: 11, fontWeight: 600, padding: '5px 12px', borderRadius: 'var(--radius-sm)',
          background: custom.trim() ? 'var(--accent)' : 'var(--bg-elevated)',
          border: '1px solid var(--border)', color: custom.trim() ? '#fff' : 'var(--text-muted)',
        }}>Add</button>
      </div>
    </div>
  )
}

export default function NewProjectWizard() {
  const { closeWizard, addProject, openProject, setProjectTab, removeProject } = useStore()
  const [step, setStep] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const [corpusNovels, setCorpusNovels] = useState([])
  useEffect(() => {
    api.registry().then(r => setCorpusNovels(r.novels || [])).catch(() => {})
  }, [])

  const [form, setForm] = useState({
    setup_mode: 'blueprint',
    title: '',
    novel_id: '',
    genre: 'Cultivation',
    subgenres: [],
    genre_tags: [],
    audience: 'Young Adult',
    age_rating: '16+',
    target_chapters: 350,
    language: 'English',
    cultural_dna: {},
    cultural_traits: {},
    story_dna: Object.fromEntries(DNA_SLIDERS.map(s => [s.key, 5])),
    inspiration_novels: [],
    power_system: '',
    protagonist_name: '',
    protagonist_archetype: '',
    value_conflicts: '',
    pov: '3rd Person Limited',
    premise: '',
  })

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const steps = form.setup_mode === 'blueprint'
    ? ['Mode', 'Basic Info', 'Story DNA', 'Culture DNA', 'Inspirations', 'Generate']
    : form.setup_mode === 'manual'
    ? ['Mode', 'Basic Info', 'Story DNA', 'Culture DNA', 'Characters', 'Generate']
    : ['Mode', 'Basic Info', 'Inspirations', 'Blend', 'Generate']

  const TOTAL = steps.length - 1

  function toNovelId(title) {
    return title.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
  }

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    try {
      const payload = {
        title: form.title,
        genre: form.genre,
        subgenres: form.subgenres,
        genre_tags: form.genre_tags,
        audience: form.audience,
        pov: form.pov,
        premise: form.premise,
        target_chapters: Number(form.target_chapters),
        story_dna: form.story_dna,
        cultural_dna: form.cultural_dna,
        cultural_traits: form.cultural_traits,
        power_system: form.power_system,
        protagonist_name: form.protagonist_name,
        protagonist_archetype: form.protagonist_archetype,
        inspiration_novels: form.inspiration_novels,
        setup_mode: form.setup_mode,
        creative_brief: {
          premise: form.premise,
          themes: [],
          reader_experience: {
            epicness: form.story_dna.power_fantasy || 5,
            comedy: form.story_dna.comedy || 5,
            mystery: form.story_dna.mystery || 5,
            romance: form.story_dna.romance || 5,
            adventure: form.story_dna.adventure || 5,
            conflict: form.story_dna.conflict || 5,
          },
        },
        tagline: form.power_system
          ? `A story of power, destiny, and ${form.protagonist_name || 'a lone cultivator'}`
          : '',
      }
      const created = await api.createProject(payload)
      setResult(created)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const toggleInspiration = (id) => {
    set('inspiration_novels', form.inspiration_novels.includes(id)
      ? form.inspiration_novels.filter(x => x !== id)
      : [...form.inspiration_novels, id]
    )
  }

  const inspirationsStep = (
    <div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
        Select corpus novels to inspire your story. NovelTea Engine will blend their patterns, pacing, and
        narrative DNA into your project.{' '}
        <span style={{ color: 'var(--text-secondary)' }}>
          Pick 1–5 for best results.
        </span>
      </div>
      {corpusNovels.length === 0 ? (
        <div style={{
          padding: '24px', textAlign: 'center',
          color: 'var(--text-muted)', fontSize: 12,
          background: 'var(--bg-elevated)', borderRadius: 'var(--radius)',
          border: '1px solid var(--border)',
        }}>
          Loading corpus…
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {corpusNovels.map(novel => {
            const selected = form.inspiration_novels.includes(novel.id)
            return (
              <button key={novel.id} onClick={() => toggleInspiration(novel.id)} style={{
                padding: '10px 14px', textAlign: 'left',
                background: selected ? 'var(--accent-glow)' : 'var(--bg-elevated)',
                border: `1.5px solid ${selected ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 'var(--radius)',
                transition: 'all 0.12s',
                display: 'flex', alignItems: 'center', gap: 12,
              }}>
                <div style={{
                  width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                  background: selected ? 'var(--accent)' : 'var(--bg-surface)',
                  border: `1.5px solid ${selected ? 'var(--accent)' : 'var(--border)'}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 11, color: '#fff', fontWeight: 700,
                }}>
                  {selected ? '✓' : ''}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontWeight: 600, fontSize: 12,
                    color: selected ? 'var(--text-primary)' : 'var(--text-secondary)',
                    marginBottom: 2,
                  }}>
                    {novel.title || novel.id}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', gap: 10 }}>
                    {novel.chapters_extracted && (
                      <span>{novel.chapters_extracted} ch</span>
                    )}
                    {novel.status && (
                      <span style={{ color: novel.status === 'active' ? 'var(--green)' : 'var(--text-muted)' }}>
                        {novel.status}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      )}
      {form.inspiration_novels.length > 0 && (
        <div style={{
          marginTop: 14, padding: '8px 12px',
          background: 'var(--accent-glow)', border: '1px solid var(--accent)',
          borderRadius: 'var(--radius-sm)', fontSize: 11, color: 'var(--text-secondary)',
        }}>
          <span style={{ color: 'var(--accent)', fontWeight: 600 }}>
            {form.inspiration_novels.length} novel{form.inspiration_novels.length > 1 ? 's' : ''} selected
          </span>
          {' — '}
          {form.inspiration_novels.join(', ')}
        </div>
      )}
    </div>
  )

  const STEP_CONTENT = {
    0: (
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Choose setup mode</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
          You can change this later or combine modes.
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {SETUP_MODES.map(m => (
            <button key={m.id} onClick={() => set('setup_mode', m.id)} style={{
              padding: '14px 16px', textAlign: 'left',
              background: form.setup_mode === m.id ? 'var(--accent-glow)' : 'var(--bg-elevated)',
              border: `1.5px solid ${form.setup_mode === m.id ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 'var(--radius)',
              transition: 'all 0.15s',
            }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <span style={{ fontSize: 20 }}>{m.icon}</span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', marginBottom: 4 }}>
                    {m.label}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{m.desc}</div>
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    ),

    1: (
      <div>
        <Field label="Novel Title *">
          <Input value={form.title} onChange={v => { set('title', v); set('novel_id', toNovelId(v)) }}
            placeholder="The Ashen Sovereign" />
        </Field>
        <Field label="Novel ID (auto-generated)">
          <Input value={form.novel_id} onChange={v => set('novel_id', v)} placeholder="the_ashen_sovereign" />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Primary Genre">
            <Select value={form.genre} onChange={v => set('genre', v)} options={GENRES} />
          </Field>
          <Field label="Target Length">
            <input type="number" value={form.target_chapters}
              onChange={e => set('target_chapters', e.target.value)}
              style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)' }} />
          </Field>
          <Field label="Audience">
            <Select value={form.audience} onChange={v => set('audience', v)} options={AUDIENCES} />
          </Field>
          <Field label="Age Rating">
            <Select value={form.age_rating} onChange={v => set('age_rating', v)} options={['13+','16+','18+','All Ages']} />
          </Field>
        </div>
        <Field label="Subgenres">
          <TagSelect options={SUBGENRES} selected={form.subgenres}
            onToggle={s => set('subgenres', form.subgenres.includes(s)
              ? form.subgenres.filter(x => x !== s)
              : [...form.subgenres, s]
            )} />
        </Field>
        <Field label="Genre Tags">
          <TagSelectWithCustom options={GENRE_TAGS} selected={form.genre_tags}
            onToggle={t => set('genre_tags', form.genre_tags.includes(t)
              ? form.genre_tags.filter(x => x !== t)
              : [...form.genre_tags, t]
            )} />
        </Field>
        <Field label="Point of view">
          <Select value={form.pov} onChange={v => set('pov', v)}
            options={['3rd Person Limited', '3rd Person Omniscient', '1st Person', '2nd Person']} />
        </Field>
        <Field label="Premise">
          <textarea value={form.premise} onChange={e => set('premise', e.target.value)} rows={3}
            placeholder="One or two paragraphs: who the hero is, what is wrong with his place in the world, what he wants."
            style={{ width: '100%', padding: '6px 10px', fontSize: 12, borderRadius: 'var(--radius-sm)', resize: 'vertical' }} />
        </Field>
        <Field label="Protagonist Name">
          <Input value={form.protagonist_name} onChange={v => set('protagonist_name', v)} placeholder="Jiang Chen" />
        </Field>
        <Field label="Power System">
          <Input value={form.power_system} onChange={v => set('power_system', v)} placeholder="Cultivation realms, qi, dragon marks..." />
        </Field>
      </div>
    ),

    2: (
      <div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
          Set target intensities for your novel's story elements (0 = minimal, 10 = dominant).
        </div>
        {DNA_SLIDERS.map(s => (
          <Slider key={s.key} label={s.label} color={s.color} desc={s.desc}
            value={form.story_dna[s.key] ?? 5}
            onChange={v => set('story_dna', { ...form.story_dna, [s.key]: v })} />
        ))}
        <Field label="Value Conflicts (comma separated)">
          <Input value={form.value_conflicts}
            onChange={v => set('value_conflicts', v)}
            placeholder="mercy vs strength, honor vs pragmatism" />
        </Field>
        <div style={{ marginTop: 4, marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
            Or click to add a conflict template (grepped from {corpusNovels.length || 'the'} corpus novels — click adds it to the field above):
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {CONFLICT_TEMPLATES.map(t => (
              <button key={t.label} type="button" onClick={() => {
                const existing = form.value_conflicts.trim()
                const next = existing ? `${existing}, ${t.value}` : t.value
                set('value_conflicts', next)
              }} style={{
                fontSize: 11, padding: '5px 10px', borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
                border: '1px solid var(--border)', cursor: 'pointer',
              }}>+ {t.label}</button>
            ))}
          </div>
        </div>
      </div>
    ),

    3: (
      <div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14 }}>
          Cultural influences shape dialogue, pacing, morality, and reader expectations.
        </div>
        <Field label="Regional Influences">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
            {CULTURES.map(c => {
              const val = form.cultural_dna[c] || 0
              return (
                <div key={c} style={{ width: '48%' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{c}</span>
                    <span style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 600 }}>{val}%</span>
                  </div>
                  <input type="range" min={0} max={100} value={val}
                    onChange={e => set('cultural_dna', { ...form.cultural_dna, [c]: Number(e.target.value) })}
                    style={{ width: '100%', accentColor: 'var(--accent)', height: 4 }} />
                </div>
              )
            })}
          </div>
        </Field>
        <Field label="Cultural Traits">
          {CULT_SLIDERS.map(s => (
            <Slider key={s.key} label={s.label}
              value={form.cultural_traits[s.key] ?? 5}
              onChange={v => set('cultural_traits', { ...form.cultural_traits, [s.key]: v })} />
          ))}
        </Field>
      </div>
    ),
  }

  const lastStepContent = (
    <div style={{ textAlign: 'center', padding: '20px 0' }}>
      {loading ? (
        <>
          <div style={{ fontSize: 40, marginBottom: 16, animation: 'spin 2s linear infinite' }}>⟳</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>
            Creating Novel...
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Setting up the project...
          </div>
        </>
      ) : result ? (
        <>
          <div style={{ fontSize: 40, marginBottom: 12, color: 'var(--green)' }}>✓</div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: 'var(--green)' }}>
            Novel Created!
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 16 }}>
            <b>{form.title}</b> is ready. Build its pre-generation tabs next; the chapter generator reads all of them.
          </div>
          <div style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', padding: '10px 14px',
            fontSize: 11, color: 'var(--text-secondary)', textAlign: 'left', marginBottom: 16,
          }}>
            <div>Genre: <b style={{ color: 'var(--text-primary)' }}>{result.genre}</b></div>
            <div>Length: <b style={{ color: 'var(--text-primary)' }}>{result.target_chapters} chapters planned</b></div>
            <div>Status: <b style={{ color: 'var(--green)' }}>{result.status}</b></div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>Start with:</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginBottom: 14 }}>
            {NEXT_TABS.map(t => (
              <button key={t.tab} onClick={() => { addProject(result); closeWizard(); openProject(result.id); setProjectTab(t.tab) }} style={{
                padding: '5px 12px', fontSize: 11, borderRadius: 'var(--radius-sm)',
                background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
              }}>{t.label}</button>
            ))}
          </div>
          <button onClick={() => {
            addProject(result)
            closeWizard()
            openProject(result.id)
          }} style={{
            padding: '8px 24px', background: 'var(--accent)', color: '#fff',
            borderRadius: 'var(--radius-sm)', fontWeight: 600, fontSize: 13,
          }}>Open Project →</button>
        </>
      ) : (
        <>
          <div style={{ fontSize: 13, marginBottom: 20, color: 'var(--text-secondary)' }}>
            Ready to create <b style={{ color: 'var(--text-primary)' }}>{form.title || 'your novel'}</b>
            {form.setup_mode === 'blueprint' && ' from your wizard answers.'}
            {form.setup_mode === 'manual' && ' with manual setup.'}
            {form.setup_mode === 'template' && ' from corpus template.'}
          </div>
          {error && (
            <div style={{
              background: 'var(--red-dim)', border: '1px solid var(--red)',
              borderRadius: 'var(--radius-sm)', padding: '8px 12px',
              fontSize: 11, color: 'var(--red)', marginBottom: 14,
            }}>{error}</div>
          )}
          <button onClick={handleGenerate} disabled={!form.title} style={{
            padding: '10px 28px',
            background: form.title ? 'var(--accent)' : 'var(--bg-elevated)',
            color: form.title ? '#fff' : 'var(--text-muted)',
            borderRadius: 'var(--radius-sm)', fontWeight: 700, fontSize: 14,
            boxShadow: form.title ? '0 0 16px var(--accent-glow)' : 'none',
            transition: 'all 0.15s',
          }}>
            {form.setup_mode === 'blueprint' ? '✦ Create Project' : '+ Create Novel'}
          </button>
        </>
      )}
    </div>
  )

  const currentStepContent = step === TOTAL
    ? lastStepContent
    : steps[step] === 'Inspirations'
    ? inspirationsStep
    : STEP_CONTENT[step] || <div style={{ color: 'var(--text-muted)' }}>Step content coming soon.</div>

  return (
    <Overlay>
      <div style={{
        width: 640,
        maxWidth: '96vw',
        maxHeight: '88vh',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>New Project</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Novel creation engine</div>
          </div>
          <button onClick={closeWizard} style={{ color: 'var(--text-muted)', fontSize: 18 }}>✕</button>
        </div>

        {/* Step indicators */}
        <div style={{
          padding: '12px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex', gap: 16, flexWrap: 'wrap',
        }}>
          {steps.map((s, i) => (
            <Step key={i} n={i + 1} label={s} active={step === i} done={step > i} />
          ))}
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px' }}>
          {currentStepContent}
        </div>

        {/* Footer */}
        {!result && (
          <div style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <button onClick={() => setStep(s => Math.max(0, s - 1))}
              disabled={step === 0}
              style={{
                padding: '6px 16px', fontSize: 12,
                background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                color: step === 0 ? 'var(--text-muted)' : 'var(--text-primary)',
              }}>← Back</button>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              Step {step + 1} of {steps.length}
            </span>
            {step < TOTAL ? (
              <button onClick={() => setStep(s => Math.min(TOTAL, s + 1))}
                style={{
                  padding: '6px 16px', fontSize: 12, fontWeight: 600,
                  background: 'var(--accent)', color: '#fff',
                  borderRadius: 'var(--radius-sm)',
                }}>Next →</button>
            ) : (
              <span />
            )}
          </div>
        )}
      </div>
    </Overlay>
  )
}
