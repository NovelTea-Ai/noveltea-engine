import { useCallback, useEffect, useRef, useState } from 'react'
import useStore from '../store/useStore'
import { api } from '../api'
import { EngineConsoleMerged } from '../components/layout/EngineConsole'
import LoreTab from '../components/pre_generation/LoreTab'
import ConspiracyTab from '../components/pre_generation/ConspiracyTab'
import TimelineTab from '../components/pre_generation/TimelineTab'
import CastRosterTab from '../components/pre_generation/CastRosterTab'
import AntagonistsTab from '../components/pre_generation/AntagonistsTab'
import ScenePlanTab from '../components/pre_generation/ScenePlanTab'
import HumorTab from '../components/pre_generation/HumorTab'
import CombatTab from '../components/pre_generation/CombatTab'
import ProjectWorkspace from '../components/generation/ProjectWorkspace'
import { SkeletonDetail, Spinner, coverImageUrl } from '../components/shared/projectUi'
import { FrontCoverTool } from '../components/pre_generation/FrontCoverTool'
import { OverviewTab } from '../components/pre_generation/OverviewTab'
import { SystemsTab } from '../components/pre_generation/SystemsTab'
import { BriefTab } from '../components/pre_generation/BriefTab'
import { CharactersTab } from '../components/pre_generation/CharactersTab'
import { ArcPlannerTab } from '../components/pre_generation/ArcPlannerTab'
import { ChapterSkeletonTab } from '../components/pre_generation/ChapterSkeletonTab'
import { AuthorProfileTab } from '../components/pre_generation/AuthorProfileTab'
import { MapTab } from '../components/pre_generation/MapTab'
import { ReaderTab } from '../components/post_generation/ReaderTab'
import { EditorTab } from '../components/post_generation/EditorTab'
import { RevisionTab } from '../components/post_generation/RevisionTab'
import { CritiqueTab } from '../components/post_generation/CritiqueTab'
import { GenerateTab } from '../components/generation/GenerateTab'
import { AssistantTab } from '../components/post_generation/AssistantTab'

const COVER_GRADIENTS = [
  { label: 'Indigo Night',  value: '135deg, #1e1b4b, #312e81' },
  { label: 'Deep Ocean',    value: '135deg, #0c1a2e, #0f3460' },
  { label: 'Dark Void',     value: '135deg, #1a0a2e, #44006b' },
  { label: 'Forest',        value: '135deg, #0a1f0a, #0d4f1f' },
  { label: 'Blood',         value: '135deg, #1f0a0a, #4f0d0d' },
  { label: 'Steel',         value: '135deg, #0a1a2e, #0d3360' },
  { label: 'Ember',         value: '135deg, #2d1200, #7c2d00' },
  { label: 'Aurora',        value: '135deg, #064e3b, #065f46' },
  { label: 'Dusk',          value: '135deg, #1e1b4b, #9333ea' },
  { label: 'Crimson',       value: '135deg, #450a0a, #991b1b' },
  { label: 'Gold',          value: '135deg, #1c1400, #713f12' },
  { label: 'Abyss',         value: '135deg, #000000, #1a1a2e' },
]

const COVER_EMOJIS = [
  '⚡','🔥','⚔️','🌙','🐉','💀','👑','🌟','🌊','🍃',
  '🗡️','🔮','💎','🏔️','🌸','🎭','🌀','🦋','🌑','☄️',
  '🏯','⛩️','🗺️','📜','🧬','🔑','🪄','🎴','🧿','✨',
]

/* ── cover editor modal ── */
function CoverEditor({ project, projectId, onSave, onClose, onUploaded }) {
  const [emoji, setEmoji] = useState(project.cover_emoji || '⚡')
  const [gradient, setGradient] = useState(project.cover_gradient || COVER_GRADIENTS[0].value)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErr, setUploadErr] = useState('')
  const [generating, setGenerating] = useState(false)
  const [genErr, setGenErr] = useState('')
  const fileRef = useRef(null)
  const previewGrad = `linear-gradient(${gradient})`
  const currentImg = coverImageUrl(project)
  const { setConsoleRunning, clearConsoleRunning, consoleOpen } = useStore()

  async function handleGenerateAI() {
    setGenErr('')
    setGenerating(true)
    setConsoleRunning('cover')   // activates the merged console + progress poller
    try {
      await api.generateCover(projectId)
      await onUploaded()
    } catch (err) {
      setGenErr(err.message || 'Cover generation failed')
    } finally {
      setGenerating(false)
      clearConsoleRunning()
    }
  }

  async function handleSave() {
    setSaving(true)
    try {
      await onSave({ cover_emoji: emoji, cover_gradient: gradient })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  async function handleFilePicked(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadErr('')
    setUploading(true)
    try {
      await api.uploadCoverImage(projectId, file)
      await onUploaded()
      onClose()
    } catch (err) {
      setUploadErr(err.message || 'Upload failed')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function handleRemoveImage() {
    setUploading(true)
    try {
      await api.removeCoverImage(projectId)
      await onUploaded()
    } catch (err) {
      setUploadErr(err.message || 'Remove failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 200,
      background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 16,
    }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 480, maxWidth: '100%', maxHeight: '90vh', overflowY: 'auto',
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)',
      }}>
        {/* preview */}
        <div style={{
          height: 180, background: currentImg ? '#000' : previewGrad,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 60, position: 'relative', overflow: 'hidden',
        }}>
          {currentImg
            ? <img src={currentImg} alt="Cover" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            : emoji}
          <div style={{ position: 'absolute', top: 10, right: 12, fontSize: 11, color: 'rgba(255,255,255,0.5)' }}>Preview</div>
        </div>

        <div style={{ padding: 18 }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 14 }}>Edit Cover</div>

          {/* image upload */}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600 }}>Custom Image</div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif"
              onChange={handleFilePicked} disabled={uploading} style={{ display: 'none' }} id="cover-file-input" />
            <button onClick={() => fileRef.current?.click()} disabled={uploading} className="btn-ghost" style={{ padding: '7px 14px', fontSize: 11 }}>
              {uploading ? <Spinner size={11} /> : '⬆ Upload Image'}
            </button>
            <button onClick={handleGenerateAI} disabled={generating || uploading} className="btn-ghost" style={{ padding: '7px 14px', fontSize: 11 }}
              title="Expands your title + premise into an art-directed prompt, then renders it via NVIDIA FLUX (falls back to a local Stable Diffusion webui if FLUX is unavailable/filtered)">
              {generating ? <Spinner size={11} /> : '🎨 Generate with AI'}
            </button>
            {currentImg && (
              <button onClick={handleRemoveImage} disabled={uploading} style={{
                fontSize: 11, padding: '7px 12px', color: 'var(--red)',
                border: '1px solid var(--red)', borderRadius: 'var(--radius-sm)',
                background: 'transparent',
              }}>Remove Image</button>
            )}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 16 }}>
            JPG, PNG, WEBP or GIF, up to 8MB. Overrides the icon/background below while set.
          </div>
          {uploadErr && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 12 }}>{uploadErr}</div>}
          {genErr && <div style={{ fontSize: 11, color: 'var(--red)', marginBottom: 12 }}>{genErr}</div>}
          {(generating || consoleOpen) && <div style={{ marginBottom: 16 }}><EngineConsoleMerged /></div>}

          {/* emoji grid */}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600 }}>Icon (used when no image is set)</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
            {COVER_EMOJIS.map(e => (
              <button key={e} onClick={() => setEmoji(e)} style={{
                width: 36, height: 36, fontSize: 20, borderRadius: 'var(--radius-sm)',
                background: emoji === e ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                border: `1px solid ${emoji === e ? 'var(--accent)' : 'var(--border)'}`,
                transition: 'all 0.1s',
              }}>{e}</button>
            ))}
          </div>

          {/* gradient grid */}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, fontWeight: 600 }}>Background</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 6, marginBottom: 18 }}>
            {COVER_GRADIENTS.map(g => (
              <button key={g.value} title={g.label} onClick={() => setGradient(g.value)} style={{
                height: 34, borderRadius: 'var(--radius-sm)',
                background: `linear-gradient(${g.value})`,
                border: `2px solid ${gradient === g.value ? '#fff' : 'transparent'}`,
                transition: 'border-color 0.1s',
              }} />
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={handleSave} disabled={saving} className="btn-primary" style={{ flex: 1, padding: '8px' }}>
              {saving ? <Spinner /> : 'Save Cover'}
            </button>
            <button onClick={onClose} className="btn-ghost" style={{ padding: '8px 16px' }}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════
   MAIN COMPONENT
══════════════════════════════════════ */
export default function ProjectView() {
  const { activeProjectId, projectData, loadProjectData, setProjectTab: setTab } = useStore()
  const [saving, setSaving]       = useState(false)
  // bumped whenever project data is saved/regenerated — the workspace re-creates a slide-out tool the next time it is opened after that
  const [wsRevision, setWsRevision] = useState(0)
  const [saveMsg, setSaveMsg]     = useState('')
  const [showCoverEditor, setShowCoverEditor] = useState(false)

  const [localBrief, setLocalBrief] = useState(null)
  const [localArcs, setLocalArcs]   = useState(null)

  useEffect(() => {
    if (activeProjectId) loadProjectData(activeProjectId)
  }, [activeProjectId])

  const project = projectData[activeProjectId]

  useEffect(() => {
    if (project) {
      setLocalBrief(b => b ?? project.creative_brief ?? {})
      setLocalArcs(a => a ?? project.arcs ?? [])
    }
  }, [project?.id])

  // reset local state when project changes
  useEffect(() => {
    setLocalBrief(null)
    setLocalArcs(null)
  }, [activeProjectId])

  const saveField = useCallback(async (patch) => {
    setSaving(true)
    try {
      await api.updateProject(activeProjectId, patch)
      await loadProjectData(activeProjectId)
      setWsRevision(r => r + 1)
      setSaveMsg('Saved ✓')
      setTimeout(() => setSaveMsg(''), 2000)
    } catch {
      setSaveMsg('Save failed')
    } finally {
      setSaving(false)
    }
  }, [activeProjectId])

  // after AI generates a field, reload and sync local state
  const afterGenerate = useCallback(async (res) => {
    await loadProjectData(activeProjectId)
    setWsRevision(r => r + 1)
    if (res.undone) {
      setSaveMsg(res.field === 'project' ? '⤺ Reverted assistant changes' : `⤺ Reverted ${res.field} to previous version`)
    } else if (res.field === 'project') {
      setSaveMsg('✦ Project updated by assistant')
    } else {
      setSaveMsg(`✦ Generated ${res.field} via ${res.provider}`)
    }
    setTimeout(() => setSaveMsg(''), 3000)
    // reset local caches so they pick up new data
    setLocalBrief(null)
    setLocalArcs(null)
  }, [activeProjectId])

  if (!project) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 10 }}>
        <Spinner size={20} />
        <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading project…</div>
      </div>
    )
  }

  const health   = project.planning_health || {}
  const state    = project.story_state || {}
  const brief    = localBrief ?? project.creative_brief ?? {}
  const arcs     = localArcs  ?? project.arcs ?? []
  const chapters = project.chapter_skeletons || []

  const overallHealth = Object.values(health).some(v => v > 0)
    ? Math.round(Object.values(health).reduce((a, b) => a + b, 0) / Object.keys(health).length)
    : 0

  const gradient = project.cover_gradient
    ? `linear-gradient(${project.cover_gradient})`
    : 'linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)'

  const hasPremise    = !!(brief.premise?.trim().length > 10)
  const hasThemes     = !!(brief.themes?.length > 0)
  const hasArcs       = arcs.length > 0
  const hasChapters   = chapters.length > 0
  const hasCharacters = !!(project.character_count > 0)

  // ── Workspace layout: every old tab as a slide-out tool. PRE = planning, left; POST = after the chapter exists, right.
  //    The page (the chapter) is the one constant. Reader/Editor stay as tools until the page absorbs their features.
  const wsTools = [
    { id: 'cover',      stage: 'pre',  icon: '🖼', short: 'Cover',     label: 'Front Cover',
      render: () => <FrontCoverTool project={project} gradient={gradient} onEditCover={() => setShowCoverEditor(true)} onSaveTitle={t => saveField({ title: t })} /> },
    { id: 'overview',   stage: 'pre',  icon: '◧', short: 'Overview',  label: 'Overview',
      render: () => <OverviewTab project={project} arcs={arcs} chapters={chapters} health={health} state={state} brief={brief} overallHealth={overallHealth} gradient={gradient} hasPremise={hasPremise} hasThemes={hasThemes} hasArcs={hasArcs} hasChapters={hasChapters} hasCharacters={hasCharacters} setTab={setTab} onCoverEdit={() => setShowCoverEditor(true)} onTitleEdit={() => setTab('cover')} saveField={saveField} afterGenerate={afterGenerate} projectId={activeProjectId} /> },
    { id: 'lore',       stage: 'pre',  icon: '☷', short: 'Lore',      label: 'Lore (why it happens)',
      render: () => <LoreTab projectId={activeProjectId} part="pre" afterGenerate={afterGenerate} /> },
    { id: 'conspiracy', stage: 'pre',  icon: '⛬', short: 'Plot',      label: 'Conspiracy',
      render: () => <ConspiracyTab projectId={activeProjectId} /> },
    { id: 'timeline',   stage: 'pre',  icon: '⏱', short: 'Timeline',  label: 'Timeline',
      render: () => <TimelineTab projectId={activeProjectId} /> },
    { id: 'systems',    stage: 'pre',  icon: '⚙', short: 'Systems',   label: 'Systems',
      render: () => <SystemsTab project={project} projectId={activeProjectId} afterGenerate={afterGenerate} onSave={saveField} /> },
    { id: 'brief',      stage: 'pre',  icon: '✎', short: 'Brief',     label: 'Creative Brief',
      render: () => <BriefTab brief={brief} setLocalBrief={setLocalBrief} project={project} onSave={saveField} saving={saving} projectId={activeProjectId} afterGenerate={afterGenerate} /> },
    { id: 'characters', stage: 'pre',  icon: '♟', short: 'Cast',      label: 'Characters',
      render: () => <CharactersTab project={project} projectId={activeProjectId} afterGenerate={afterGenerate} onSave={saveField} /> },
    { id: 'castroster', stage: 'pre', icon: '☺', short: 'Roster',   label: 'Cast roster',
      render: () => <CastRosterTab projectId={activeProjectId} /> },
    { id: 'antagonists', stage: 'pre', icon: '☠', short: 'Foes',      label: 'Antagonists',
      render: () => <AntagonistsTab projectId={activeProjectId} /> },
    { id: 'arcs',       stage: 'pre',  icon: '⌇', short: 'Arcs',      label: 'Arc Planner',
      render: () => <ArcPlannerTab arcs={arcs} setLocalArcs={setLocalArcs} project={project} onSave={saveField} saving={saving} projectId={activeProjectId} afterGenerate={afterGenerate} /> },
    { id: 'chapters',   stage: 'pre',  icon: '☰', short: 'Skeleton',  label: 'Chapter Skeleton',
      render: () => <ChapterSkeletonTab chapters={chapters} arcs={arcs} projectId={activeProjectId} afterGenerate={afterGenerate} onSave={saveField} /> },
    { id: 'scenes',     stage: 'pre',  icon: '▤', short: 'Scenes',    label: 'Scene plans',
      render: () => <ScenePlanTab projectId={activeProjectId} /> },
    { id: 'author',     stage: 'pre',  icon: '♪', short: 'Voice',     label: 'Author DNA',
      render: () => <AuthorProfileTab projectId={activeProjectId} /> },
    { id: 'humor',      stage: 'pre',  icon: '☺', short: 'Humor',     label: 'Humor',
      render: () => <HumorTab projectId={activeProjectId} part="pre" /> },
    { id: 'combat',     stage: 'pre',  icon: '⚔', short: 'Combat',    label: 'Combat',
      render: () => <CombatTab projectId={activeProjectId} part="pre" /> },
    { id: 'map',        stage: 'pre',  icon: '⌖', short: 'Map',       label: 'Map', heavy: true,
      render: () => <MapTab project={project} projectId={activeProjectId} afterGenerate={afterGenerate} onSave={saveField} /> },
    { id: 'reader',     stage: 'post', icon: '📖', short: 'Reader',   label: 'Reader',
      render: () => <ReaderTab projectId={activeProjectId} onEdit={() => setTab('editor')} /> },
    { id: 'editor',     stage: 'post', icon: '✍', short: 'Editor',    label: 'Editor',
      render: () => <EditorTab projectId={activeProjectId} /> },
    { id: 'humor_post', stage: 'post', icon: '☺', short: 'Humor',     label: 'Humor (after writing)',
      render: () => <HumorTab projectId={activeProjectId} part="post" /> },
    { id: 'combat_post', stage: 'post', icon: '⚔', short: 'Combat',   label: 'Combat (after writing)',
      render: () => <CombatTab projectId={activeProjectId} part="post" /> },
    { id: 'lore_post', stage: 'post', icon: '☷', short: 'Lore',      label: 'Lore (after reading)',
      render: () => <LoreTab projectId={activeProjectId} part="post" afterGenerate={afterGenerate} /> },
    { id: 'revision',   stage: 'post', icon: '⟲', short: 'Revision',  label: 'Revision',
      render: () => <RevisionTab project={project} projectId={activeProjectId} afterGenerate={afterGenerate} onSave={saveField} /> },
    { id: 'critique',   stage: 'post', icon: '✱', short: 'Critique',  label: 'Critique',
      render: () => <CritiqueTab project={project} projectId={activeProjectId} afterGenerate={afterGenerate} onSave={saveField} /> },
    { id: 'chaptertools', stage: 'post', icon: '⚒', short: 'Polish', label: 'Chapter tools',
      render: ({ chapterNum }) => <GenerateTab chapterNumber={chapterNum} project={project} arcs={arcs} chapters={chapters} hasPremise={hasPremise} hasArcs={hasArcs} onSave={saveField} reload={() => { loadProjectData(activeProjectId); setLocalBrief(null); setLocalArcs(null) }} projectId={activeProjectId} afterGenerate={afterGenerate} onOpenReader={() => setTab('reader')} /> },
    { id: 'assistant',  stage: 'post', icon: '✦', short: 'Assistant', label: 'Assistant',
      render: () => <AssistantTab projectId={activeProjectId} project={project} afterGenerate={afterGenerate} /> },
  ]

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* the "Saved ✓" message lived in the top bar; the workspace shows it as a small floating notice instead */}
      {saveMsg && (
        <div role="status" style={{
          position: 'fixed', zIndex: 200, left: '50%', transform: 'translateX(-50%)', bottom: 18, maxWidth: 'calc(100% - 24px)',
          padding: '8px 16px', borderRadius: 999, fontSize: 12, fontWeight: 600, pointerEvents: 'none',
          background: 'var(--bg-card)', boxShadow: '0 8px 28px rgba(0,0,0,0.5)',
          color: saveMsg.includes('✓') || saveMsg.includes('✦') ? 'var(--green)' : 'var(--red)',
          border: `1px solid ${saveMsg.includes('✓') || saveMsg.includes('✦') ? 'var(--green)' : 'var(--red)'}`,
        }}>{saveMsg}</div>
      )}

      {/* ── the workspace: the page, with the Pre-/Post-generation tools sliding out ── */}
      <ProjectWorkspace projectId={activeProjectId} revision={wsRevision} tools={wsTools} renderPlan={plan => <ChapterPlanView plan={plan} />} />

      {showCoverEditor && (
        <CoverEditor
          project={project}
          projectId={activeProjectId}
          onSave={saveField}
          onUploaded={() => loadProjectData(activeProjectId)}
          onClose={() => setShowCoverEditor(false)}
        />
      )}
    </div>
  )
}

// A chapter's plan — arc, skeleton goal, characters, themes — used by the workspace's "View Plan" button.
function ChapterPlanView({ plan: planData }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {planData.arc && (
        <div>
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>ARC</span>
          <div style={{ fontSize: 11, color: 'var(--accent-light)', fontWeight: 600 }}>{planData.arc.label}</div>
          <div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{planData.arc.description}</div>
        </div>
      )}
      {planData.chapter_skeleton && (
        <div>
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>CHAPTER GOAL</span>
          <div style={{ fontSize: 11, color: 'var(--text-primary)', fontWeight: 600 }}>{planData.chapter_skeleton.title}</div>
          {/* Same two-schema gap as SkeletonDetail below: the interactive interview has no
              top-level purpose/key_event, only per-scene purpose and a chapter-level
              ending_hook — fall back to those rather than render nothing. */}
          <div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
            {planData.chapter_skeleton.purpose || planData.chapter_skeleton.scenes?.[0]?.purpose}
          </div>
          {(planData.chapter_skeleton.key_event || planData.chapter_skeleton.ending_hook) && (
            <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 2 }}>
              ⚡ {planData.chapter_skeleton.key_event || planData.chapter_skeleton.ending_hook}
            </div>
          )}
          {/* Full structural-discipline detail (scenes, canon_lock,
              characters_in_chapter, anti_patterns, hard_constraints) —
              same expandable block used on the Chapter Skeleton tab's
              cards, so the plan you're about to write from shows
              everything the Interactive interview actually captured. */}
          <SkeletonDetail ch={planData.chapter_skeleton} />
        </div>
      )}
      {planData.protagonist && (
        <div>
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>PROTAGONIST</span>
          <div style={{ fontSize: 11, color: 'var(--text-primary)' }}>{planData.protagonist} — {planData.power_system}</div>
        </div>
      )}
      {planData.characters?.length > 0 && (
        <div>
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>CHARACTERS IN PLAY</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
            {planData.characters.slice(0, 6).map(c => (
              <span key={c.name} style={{
                fontSize: 9, padding: '2px 6px', borderRadius: 10,
                background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                color: 'var(--text-secondary)',
              }}>{c.name}</span>
            ))}
          </div>
        </div>
      )}
      {planData.themes?.length > 0 && (
        <div>
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>THEMES</span>
          <div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>{planData.themes.join(' · ')}</div>
        </div>
      )}
      {!planData.chapter_skeleton && (
        <div style={{ fontSize: 10, color: 'var(--amber)', fontStyle: 'italic' }}>
          No skeleton entry for ch{planData.chapter_number} — generate Chapter Skeleton first for better output.
        </div>
      )}
    </div>
  )
}
