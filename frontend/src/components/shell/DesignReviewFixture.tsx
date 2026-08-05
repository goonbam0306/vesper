import React, { useEffect, useState } from 'react'
import { VesperPresenceIcon } from '../presence'
import { CalmAuroraEdge } from './CalmAuroraEdge'

const compactMedia = '(max-width: 1179px)'

export function DesignReviewFixture() {
  const [auroraActive, setAuroraActive] = useState(true)
  const [compact, setCompact] = useState(() => typeof window !== 'undefined' && window.matchMedia(compactMedia).matches)

  useEffect(() => {
    const media = window.matchMedia(compactMedia)
    const update = () => setCompact(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  return <div className="fixture-shell" data-testid="design-review-fixture" data-layout={compact ? 'compact' : 'large'}><div className="fixture-contract" data-testid="desktop-shell" data-layout={compact ? 'compact' : 'large'}>
    <aside className="fixture-sidebar" data-testid="sidebar" data-collapsed={String(compact)}>
      <div className="brand"><VesperPresenceIcon state="idle" decorative size={24} /><span>VESPER</span></div>
      <span className="system-label">WORKSPACE</span>
      <button className="nav-row active">Home</button><button className="nav-row">Projects</button><button className="nav-row">Tasks</button>
      <span className="system-label">SYSTEM</span>
      <button className="nav-row">Processes</button><button className="nav-row">Approvals</button>
    </aside>
    <main className="fixture-workspace" data-testid="workspace">
      <header className="fixture-toolbar"><span className="crumb">Home / Design review</span><label className="fixture-search">⌕ <input aria-label="Fixture search" placeholder="Search…" /><kbd>⌘ K</kbd></label></header>
      <section className="fixture-content">
        <p className="fixture-label">DEMO · DETERMINISTIC REVIEW DATA</p>
        <h1>Workspace overview</h1><p className="muted">Visual contract preview. This content is not persisted product data.</p>
        <div className="fixture-controls"><button>Primary action</button><button className="quiet">Secondary</button><span className="tag">STATUS</span><label className="fixture-toggle">Diagnostics <input type="checkbox" /></label></div>
        <div className="fixture-grid"><section className="panel"><div className="panel-head"><h2>Attention</h2><span className="tag">2 open</span></div><div className="list-row"><span>Review interface migration</span><small>Task</small></div><div className="list-row"><span>Director visual review</span><small>Approval</small></div></section><section className="panel"><div className="panel-head"><h2>Presence</h2></div><div className="fixture-presence"><VesperPresenceIcon state="idle" size={24}/><VesperPresenceIcon state="thinking" size={24} testId="fixture-process-running"/><VesperPresenceIcon state="waiting" size={24}/><VesperPresenceIcon state="blocked" size={24}/></div></section></div>
        <section className="panel fixture-aurora"><div className="panel-head"><h2>Calm Aurora edge</h2><button className="quiet" type="button" onClick={() => setAuroraActive(value => !value)}>Preview {auroraActive ? 'off' : 'on'}</button></div><div className="aurora-preview"><CalmAuroraEdge active={auroraActive} preview /></div><small>Fixture-only presentation preview. Production Aurora remains inactive.</small></section>
      </section>
    </main>
    <aside className="fixture-inspector" data-testid="inspector" data-drawer={String(compact)}><p className="system-label">INSPECTOR</p><h2>Review context</h2><div className="inspector-item"><span>Mode</span><strong>Design preview</strong></div><div className="inspector-item"><span>Aurora</span><strong>Presentation only</strong></div><p className="muted">No provider, process, or Ask state activates this preview.</p></aside>
  </div></div>
}
