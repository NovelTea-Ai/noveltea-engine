

/* ══════════════════════════════════════
   SYSTEMS TAB
══════════════════════════════════════ */
export const SYSTEM_ENGINES = [
  {
    key: 'power_levels',
    label: 'Power Level System',
    icon: '⚡',
    color: '#f59e0b',
    desc: 'Cultivation realms, ranks, bottlenecks, breakthrough conditions, and power rules',
    listKey: 'levels',
    listLabel: 'Levels',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.rank ?? item.name ?? item.level}</div>
        {item.name && item.rank && <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{item.name}</div>}
        {item.requirement && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Req: {item.requirement}</div>}
        {item.breakthrough && <div style={{ fontSize: 10, color: '#f59e0b' }}>Breakthrough: {item.breakthrough}</div>}
        {item.description && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 2 }}>{item.description}</div>}
      </div>
    ),
  },
  {
    key: 'techniques',
    label: 'Techniques & Skills',
    icon: '🌀',
    color: '#06b6d4',
    desc: 'Combat techniques, dao laws, elemental skills, and forbidden arts',
    listKey: 'techniques',
    listLabel: 'Techniques',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(6,182,212,0.15)', border: '1px solid rgba(6,182,212,0.3)', color: '#06b6d4' }}>{item.type}</span>}
          {item.element && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(245,158,11,0.15)', border: '1px solid rgba(245,158,11,0.3)', color: '#f59e0b' }}>{item.element}</span>}
          {item.tier && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>Tier {item.tier}</span>}
        </div>
        {item.effect && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3 }}>{item.effect}</div>}
        {item.dao_law && <div style={{ fontSize: 10, color: '#a855f7', marginTop: 2 }}>Dao: {item.dao_law}</div>}
        {item.who_uses && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Used by: {item.who_uses}</div>}
      </div>
    ),
  },
  {
    key: 'weapons',
    label: 'Weapons & Artifacts',
    icon: '⚔️',
    color: '#ef4444',
    desc: 'Named weapons, spirit artifacts, and legendary items with their grades and abilities',
    listKey: 'weapons',
    listLabel: 'Weapons',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.grade && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>{item.grade}</span>}
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.type}</span>}
        </div>
        {item.ability && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3 }}>{item.ability}</div>}
        {item.owner && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Owner: {item.owner}</div>}
        {item.origin && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Origin: {item.origin}</div>}
      </div>
    ),
  },
  {
    key: 'alchemy',
    label: 'Alchemy System',
    icon: '⚗️',
    color: '#10b981',
    desc: 'Pills, cauldrons, flame grades, pill formulas, and alchemy ranks',
    listKey: 'pills',
    listLabel: 'Pills & Formulas',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.grade && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(16,185,129,0.15)', border: '1px solid rgba(16,185,129,0.3)', color: '#10b981' }}>{item.grade}</span>}
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.type}</span>}
        </div>
        {item.effect && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3 }}>{item.effect}</div>}
        {item.ingredients && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Ingredients: {Array.isArray(item.ingredients) ? item.ingredients.join(', ') : item.ingredients}</div>}
        {item.rarity && <div style={{ fontSize: 10, color: '#10b981' }}>Rarity: {item.rarity}</div>}
      </div>
    ),
  },
  {
    key: 'arrays',
    label: 'Formation Arrays',
    icon: '🔷',
    color: '#8b5cf6',
    desc: 'Spirit formations, defensive arrays, killing arrays, and formation grades',
    listKey: 'formations',
    listLabel: 'Formations',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.grade && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)', color: '#8b5cf6' }}>{item.grade}</span>}
          {item.category && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.category}</span>}
        </div>
        {item.effect && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3 }}>{item.effect}</div>}
        {item.materials && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Materials: {Array.isArray(item.materials) ? item.materials.join(', ') : item.materials}</div>}
      </div>
    ),
  },
  {
    key: 'artifact_forging',
    label: 'Artifact Forging',
    icon: '🔨',
    color: '#f97316',
    desc: 'Blacksmith ranks, forging techniques, material grades, and spirit artifact creation',
    listKey: 'artifacts',
    listLabel: 'Artifacts & Materials',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.grade && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(249,115,22,0.15)', border: '1px solid rgba(249,115,22,0.3)', color: '#f97316' }}>{item.grade}</span>}
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.type}</span>}
        </div>
        {item.ability && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3 }}>{item.ability}</div>}
        {item.materials && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Materials: {Array.isArray(item.materials) ? item.materials.join(', ') : item.materials}</div>}
        {item.rank_required && <div style={{ fontSize: 10, color: '#f97316' }}>Rank required: {item.rank_required}</div>}
      </div>
    ),
  },
  {
    key: 'treasures_materials',
    label: 'Treasures & Materials',
    icon: '💎',
    color: '#eab308',
    desc: 'Heaven-and-earth treasures, spirit stones, rare materials, and other precious resources cultivators fight over',
    listKey: 'treasures',
    listLabel: 'Treasures & Materials',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.grade && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(234,179,8,0.15)', border: '1px solid rgba(234,179,8,0.3)', color: '#eab308' }}>{item.grade}</span>}
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.type}</span>}
          {item.rarity && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.3)', color: '#10b981' }}>{item.rarity}</span>}
        </div>
        {item.description && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{item.description}</div>}
        {item.effect && <div style={{ fontSize: 10, color: '#eab308', marginTop: 2 }}>✦ Effect: {item.effect}</div>}
        {item.origin && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Origin: {item.origin}</div>}
        {item.known_owners && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Known owners: {item.known_owners}</div>}
      </div>
    ),
  },
  {
    // World Bible absorbed Sacred Grounds & Ruins, Factions & Powers, and
    // Races & Species (per author decision) — this descriptor doesn't fit
    // the generic renderItem/listKey shape every other engine uses (World
    // Bible has THREE lists — factions, key_locations, races — plus meta
    // fields, not one flat item list). SystemsTab special-cases
    // `isWorldBible` to render the real WorldTab editor instead of the
    // generic list/edit UI; other SYSTEM_ENGINES consumers must skip this
    // entry's renderItem/listKey (it has none) the same way.
    key: 'world',
    isWorldBible: true,
    label: 'World Bible',
    icon: '🌍',
    color: '#22c55e',
    desc: 'The physical and political setting: world meta, factions & powers, key locations & sacred grounds, and races & species',
  },
  {
    key: 'wars',
    label: 'Wars & Conflicts',
    icon: '⚔',
    color: '#dc2626',
    desc: 'World-level wars, race wars, beast tides, invasions, ancient wars, and large-scale conflicts that shape the story',
    listKey: 'wars',
    listLabel: 'Wars & Conflicts',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(220,38,38,0.15)', border: '1px solid rgba(220,38,38,0.35)', color: '#dc2626' }}>{item.type}</span>}
          {item.scale && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.3)', color: '#f59e0b' }}>{item.scale}</span>}
          {item.status && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.status}</span>}
        </div>
        {item.description && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{item.description}</div>}
        {item.factions_involved && <div style={{ fontSize: 10, color: '#0ea5e9', marginTop: 2 }}>⚑ Sides: {item.factions_involved}</div>}
        {item.cause && <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 2 }}>⚠ Cause: {item.cause}</div>}
        {item.key_battles && <div style={{ fontSize: 10, color: '#ef4444', marginTop: 2 }}>⚔ Key Battles: {item.key_battles}</div>}
        {item.turning_point && <div style={{ fontSize: 10, color: '#a855f7', marginTop: 2 }}>↺ Turning Point: {item.turning_point}</div>}
        {item.outcome && <div style={{ fontSize: 10, color: '#10b981', marginTop: 2 }}>✓ Outcome: {item.outcome}</div>}
        {item.impact && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Impact: {item.impact}</div>}
      </div>
    ),
  },
  {
    key: 'relationships',
    label: 'Relationships',
    icon: '💞',
    color: '#ec4899',
    desc: 'Bonds between named characters — romances, rivalries, mentorships, nemeses, sworn kinships — and how each one formed and changed',
    listKey: 'relationships',
    listLabel: 'Relationships',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(236,72,153,0.15)', border: '1px solid rgba(236,72,153,0.3)', color: '#ec4899' }}>{item.type}</span>}
          {item.status && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.status}</span>}
        </div>
        {item.participants && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>👥 {item.participants}</div>}
        {item.description && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{item.description}</div>}
      </div>
    ),
  },
  {
    key: 'encounters',
    label: 'Encounters',
    icon: '⚡',
    color: '#f97316',
    desc: 'Reusable scenario templates — ambushes, dungeon delves, tournaments, heists, rescues, negotiations — with stakes, danger, and loot',
    listKey: 'encounters',
    listLabel: 'Encounters',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(249,115,22,0.15)', border: '1px solid rgba(249,115,22,0.3)', color: '#f97316' }}>{item.type}</span>}
          {item.danger_level && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>⚠ {item.danger_level}</span>}
        </div>
        {item.participants && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>👥 {item.participants}</div>}
        {item.stakes && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{item.stakes}</div>}
        {item.complications && <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 2 }}>⚙ Complications: {item.complications}</div>}
        {item.loot_reward && <div style={{ fontSize: 10, color: '#10b981', marginTop: 2 }}>✦ Loot/Reward: {item.loot_reward}</div>}
        {item.outcome && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Outcome: {item.outcome}</div>}
      </div>
    ),
  },
  {
    key: 'currency_commerce',
    label: 'Currency & Commerce',
    icon: '💰',
    color: '#eab308',
    desc: 'Chambers of commerce, auction houses, currencies, gambling, appraisals, merchants, and material/beast-core trade — everything money touches in this world',
    listKey: 'entities',
    listLabel: 'Currency & Commerce',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(234,179,8,0.15)', border: '1px solid rgba(234,179,8,0.3)', color: '#eab308' }}>{item.type}</span>}
          {item.tier && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.tier}</span>}
        </div>
        {item.description && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{item.description}</div>}
        {item.trades_in && <div style={{ fontSize: 10, color: '#eab308', marginTop: 2 }}>⚖ Trades in: {item.trades_in}</div>}
        {item.who_controls && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Controlled by: {item.who_controls}</div>}
      </div>
    ),
  },
  {
    key: 'pets_mounts',
    label: 'Pets & Mounts',
    icon: '🐉',
    color: '#22c55e',
    desc: 'Bonded companions and rideable beasts — species, grade, how the bond forms, abilities, temperament, and who they belong to',
    listKey: 'companions',
    listLabel: 'Pets & Mounts',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.species && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(34,197,94,0.15)', border: '1px solid rgba(34,197,94,0.3)', color: '#22c55e' }}>{item.species}</span>}
          {item.grade && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.grade}</span>}
        </div>
        {item.bond && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>🔗 Bond: {item.bond}</div>}
        {item.abilities && <div style={{ fontSize: 10, color: '#22c55e', marginTop: 2 }}>✦ Abilities: {item.abilities}</div>}
        {item.temperament && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Temperament: {item.temperament}</div>}
        {item.owner && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>Owner: {item.owner}</div>}
      </div>
    ),
  },
  {
    key: 'bosses_monsters',
    label: 'Bosses & Monsters',
    icon: '👹',
    color: '#dc2626',
    desc: 'Named threats and dangerous beasts — tier, habitat, abilities, weaknesses, and what defeating them is worth',
    listKey: 'monsters',
    listLabel: 'Bosses & Monsters',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.type && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(220,38,38,0.15)', border: '1px solid rgba(220,38,38,0.3)', color: '#dc2626' }}>{item.type}</span>}
          {item.threat_tier && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>⚠ {item.threat_tier}</span>}
        </div>
        {item.habitat && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>📍 {item.habitat}</div>}
        {item.abilities && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>✦ Abilities: {item.abilities}</div>}
        {item.weaknesses && <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 2 }}>⚔ Weaknesses: {item.weaknesses}</div>}
        {item.loot_reward && <div style={{ fontSize: 10, color: '#10b981', marginTop: 2 }}>✦ Loot/Reward: {item.loot_reward}</div>}
      </div>
    ),
  },
]

// Blueprint-page-only entries — NOT included in SYSTEM_ENGINES, so they never
// appear as a Project Systems tab card (no AI-generate-from-scratch button
// for these, per author decision — Character Templates are meant to be
// SOURCED from something real via paste-to-LLM extraction, not invented).
// BlueprintsPage.jsx merges this with SYSTEM_ENGINES for its own nav;
// SystemsTab (Project page) only ever sees SYSTEM_ENGINES.
export const BLUEPRINT_ONLY_ENGINES = [
  {
    key: 'character_templates',
    label: 'Character Templates',
    icon: '🎭',
    color: '#8b5cf6',
    desc: 'Reusable character profiles — archetype, role, powers/items, backstory flavor — pulled into a project\'s Cast verbatim or adapted',
    listKey: 'characters',
    listLabel: 'Characters',
    renderItem: item => (
      <div>
        <div style={{ fontWeight: 700, fontSize: 12 }}>{item.name}</div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
          {item.role && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.3)', color: '#8b5cf6' }}>{item.role}</span>}
          {item.archetype && <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>{item.archetype}</span>}
        </div>
        {item.description && <div style={{ fontSize: 10, color: 'var(--text-secondary)', marginTop: 3, lineHeight: 1.4 }}>{item.description}</div>}
        {item.powers_items && <div style={{ fontSize: 10, color: '#8b5cf6', marginTop: 2 }}>⚡ Powers/Items: {item.powers_items}</div>}
      </div>
    ),
  },
]

// Returns the ordered field keys for each engine's item editor
export const ENGINE_FIELDS = {
  power_levels:     ['rank', 'name', 'description', 'requirement', 'breakthrough'],
  techniques:       ['name', 'type', 'tier', 'element', 'dao_law', 'effect', 'who_uses'],
  weapons:          ['name', 'type', 'grade', 'ability', 'owner', 'origin'],
  alchemy:          ['name', 'grade', 'type', 'effect', 'ingredients', 'rarity'],
  arrays:           ['name', 'grade', 'category', 'effect', 'materials'],
  artifact_forging: ['name', 'type', 'grade', 'ability', 'materials', 'rank_required'],
  treasures_materials: ['name', 'type', 'grade', 'rarity', 'description', 'effect', 'origin', 'known_owners'],
  wars:             ['name', 'type', 'scale', 'status', 'description', 'factions_involved', 'cause', 'key_battles', 'turning_point', 'outcome', 'impact'],
  relationships:    ['name', 'participants', 'type', 'status', 'description'],
  encounters:       ['name', 'type', 'danger_level', 'participants', 'stakes', 'complications', 'loot_reward', 'outcome'],
  currency_commerce: ['name', 'type', 'tier', 'description', 'trades_in', 'who_controls'],
  pets_mounts:      ['name', 'species', 'grade', 'bond', 'abilities', 'temperament', 'owner'],
  bosses_monsters:  ['name', 'type', 'threat_tier', 'habitat', 'abilities', 'weaknesses', 'loot_reward'],
  // Blueprint-only (not in SYSTEM_ENGINES, but BlueprintsPage's field editor
  // still needs this entry — see BLUEPRINT_ONLY_ENGINES above).
  character_templates: ['name', 'role', 'archetype', 'description', 'powers_items'],
  // 'world' (World Bible) deliberately has NO entry here — it doesn't use the
  // generic ENGINE_FIELDS/renderItem editor at all (SystemsTab special-cases
  // `isWorldBible` to render the real WorldTab component instead).
}

// Which fields are arrays (comma-separated in the UI)
export const ARRAY_FIELDS = new Set(['ingredients', 'materials'])

// Which fields use textarea
export const LONG_FIELDS = new Set(['description', 'effect', 'ability', 'requirement', 'breakthrough', 'conditions', 'dangers', 'rewards', 'scheme', 'innate_abilities', 'weakness', 'cause', 'key_battles', 'turning_point', 'outcome', 'impact', 'goal', 'secret', 'specialty', 'stakes', 'complications', 'loot_reward', 'powers_items'])
