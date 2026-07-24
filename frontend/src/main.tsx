import React, { FormEvent, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type View = 'home' | 'projects' | 'tasks' | 'calendar' | 'ideas' | 'operations'
type Resource = Record<string, any>

const requestId = () => crypto.randomUUID()

function App() {
  const [view, setView] = useState<View>('home')
  const [projects, setProjects] = useState<Resource[]>([])
  const [tasks, setTasks] = useState<Resource[]>([])
  const [calendar, setCalendar] = useState<Resource[]>([])
  const [ideas, setIdeas] = useState<Resource[]>([])
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')
  const [idea, setIdea] = useState('')
  const [projectName, setProjectName] = useState('')
  const [taskTitle, setTaskTitle] = useState('')
  const [eventTitle, setEventTitle] = useState('')
  const [eventStart, setEventStart] = useState('')
  const [eventEnd, setEventEnd] = useState('')
  const [searchResults, setSearchResults] = useState<Resource | null>(null)

  const load = async () => {
    const [p, t, c] = await Promise.all([fetch('/api/projects'), fetch('/api/tasks'), fetch('/api/calendar')])
    setProjects((await p.json()).projects)
    setTasks((await t.json()).tasks)
    setCalendar((await c.json()).calendar)
  }
  useEffect(() => { load().catch(() => setNotice('Runtime unavailable')) }, [])

  const command = async (url: string, method: string, body: Resource) => {
    const bootstrap = await fetch('/api/bootstrap').then(r => r.json())
    const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': bootstrap.session, 'X-Client-Request-ID': requestId() }, body: JSON.stringify(body) })
    if (!response.ok) throw new Error((await response.json()).detail?.message || 'Command failed')
    return response.json()
  }

  const createProject = async (e: FormEvent) => { e.preventDefault(); if (!projectName.trim()) return; try { await command('/api/projects', 'POST', { name: projectName.trim() }); setProjectName(''); setNotice('Project committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const createTask = async (e: FormEvent) => { e.preventDefault(); if (!taskTitle.trim()) return; try { await command('/api/tasks', 'POST', { title: taskTitle.trim() }); setTaskTitle(''); setNotice('Task committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const createEvent = async (e: FormEvent) => { e.preventDefault(); if (!eventTitle || !eventStart || !eventEnd) return; try { await command('/api/calendar', 'POST', { title: eventTitle, starts_at: eventStart, ends_at: eventEnd }); setEventTitle(''); setNotice('Calendar item committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const captureIdea = async (e: FormEvent) => { e.preventDefault(); if (!idea.trim()) return; try { const result = await command('/api/ideas', 'POST', { payload: { text: idea.trim() } }); setIdeas(current => [result.idea, ...current]); setIdea(''); setNotice('Idea captured before classification') } catch (error: any) { setNotice(error.message) } }
  const search = async (e: FormEvent) => { e.preventDefault(); if (!query.trim()) return; const result = await fetch(`/api/search?q=${encodeURIComponent(query.trim())}`).then(r => r.json()); setSearchResults(result); setView('home') }

  const attention = useMemo(() => tasks.filter(task => task.status !== 'DONE').slice(0, 4), [tasks])
  const nav = (next: View) => { setView(next); setSearchResults(null) }

  return <div className="shell">
    <aside className="rail">
      <div className="brand"><span className="brand-mark">V</span><span>VESPER</span></div>
      <nav>{([['home', 'Home'], ['projects', 'Projects'], ['tasks', 'Tasks'], ['calendar', 'Calendar'], ['ideas', 'Ideas'], ['operations', 'Operations']] as [View, string][]).map(([id, label]) => <button className={view === id ? 'active' : ''} onClick={() => nav(id)} key={id}>{label}</button>)}</nav>
      <div className="rail-foot"><span className="pulse" /> Kernel local · ready</div>
    </aside>
    <main className="canvas">
      <header className="topbar"><form onSubmit={search} className="omnibar"><span>⌕</span><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search or command…" /><kbd>⌘ K</kbd></form><div className="indicators"><span>0 approvals</span><span>{tasks.filter(t => t.status !== 'DONE').length} open</span></div></header>
      <section className="content">
        <div className="eyebrow">{view === 'home' ? 'ATTENTION / TODAY' : view.toUpperCase()}</div>
        {view === 'home' && <><div className="hero"><div><h1>Good work<br /><em>starts here.</em></h1><p>One canvas for what needs your attention. Canonical state lives in the Kernel.</p></div><div className="hero-meta"><strong>{attention.length}</strong><span>open tasks</span></div></div>{searchResults && <section className="panel"><h2>Search results</h2><p>{searchResults.projects?.length || 0} projects · {searchResults.tasks?.length || 0} tasks · {searchResults.ideas?.length || 0} ideas</p><pre>{JSON.stringify(searchResults, null, 2)}</pre></section>}<div className="grid"><section className="panel"><div className="panel-head"><h2>Next up</h2><button onClick={() => nav('tasks')}>View all →</button></div>{attention.length ? attention.map(task => <div className="list-row" key={task.task_id}><span className="check" /> <span>{task.title}</span><small>P{task.priority}</small></div>) : <p className="muted">Nothing urgent. Capture the next thought below.</p>}</section><section className="panel"><div className="panel-head"><h2>Upcoming</h2><button onClick={() => nav('calendar')}>Calendar →</button></div>{calendar.slice(0, 3).map(item => <div className="list-row" key={item.calendar_id}><span className="date-dot" /> <span>{item.title}</span><small>{item.starts_at}</small></div>)}{!calendar.length && <p className="muted">Your local schedule is clear.</p>}</section></div></>}
        {view === 'projects' && <section className="panel page-panel"><div className="panel-head"><div><h2>Projects</h2><p className="muted">Objectives and work relationships owned by Vesper.</p></div></div><form className="inline-form" onSubmit={createProject}><input value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="New project name" /><button>+ Create</button></form>{projects.map(project => <div className="resource-card" key={project.project_id}><div><strong>{project.name}</strong><p>{project.objective || 'No objective yet'}</p></div><span className="tag">{project.status}</span></div>)}{!projects.length && <p className="muted">No projects yet.</p>}</section>}
        {view === 'tasks' && <section className="panel page-panel"><div className="panel-head"><div><h2>Tasks</h2><p className="muted">Today and upcoming work. Ideas remain separate.</p></div></div><form className="inline-form" onSubmit={createTask}><input value={taskTitle} onChange={e => setTaskTitle(e.target.value)} placeholder="Add a task" /><button>+ Create</button></form>{tasks.map(task => <div className="resource-card" key={task.task_id}><div><strong>{task.title}</strong><p>{task.status} · priority {task.priority}</p></div><button className="quiet" onClick={async () => { await command(`/api/tasks/${task.task_id}`, 'PATCH', { patch: { status: task.status === 'DONE' ? 'TODO' : 'DONE' }, expected_revision: task.revision }); await load() }}>{task.status === 'DONE' ? 'Reopen' : 'Done'}</button></div>)}</section>}
        {view === 'calendar' && <section className="panel page-panel"><div className="panel-head"><div><h2>Calendar</h2><p className="muted">Local schedule, changed through Kernel Commands.</p></div></div><form className="event-form" onSubmit={createEvent}><input value={eventTitle} onChange={e => setEventTitle(e.target.value)} placeholder="Event title" /><input type="datetime-local" value={eventStart} onChange={e => setEventStart(e.target.value)} /><input type="datetime-local" value={eventEnd} onChange={e => setEventEnd(e.target.value)} /><button>+ Add event</button></form>{calendar.map(item => <div className="resource-card" key={item.calendar_id}><div><strong>{item.title}</strong><p>{item.starts_at} → {item.ends_at}</p></div><span className="tag">LOCAL</span></div>)}</section>}
        {view === 'ideas' && <section className="panel page-panel"><div className="panel-head"><div><h2>Idea Inbox</h2><p className="muted">Capture first. Optional organization comes later.</p></div></div><form className="capture" onSubmit={captureIdea}><textarea value={idea} onChange={e => setIdea(e.target.value)} placeholder="What are you noticing?" /><button>Capture idea</button></form>{ideas.map(item => <div className="idea-card" key={item.memory_id}><span>✦</span><div><strong>{item.payload?.text}</strong><small>UNREVIEWED · committed memory</small></div></div>)}</section>}
        {view === 'operations' && <section className="panel page-panel"><h2>Operations</h2><div className="ops-grid"><div><strong>Processes</strong><span>Kernel execution identities</span></div><div><strong>Approvals</strong><span>0 waiting for review</span></div><div><strong>Connections</strong><span>Local runtime only</span></div><div><strong>Settings</strong><span>Loopback boundary active</span></div></div></section>}
        <section className="persistent"><div><span className="spark">✦</span><input placeholder="Ask Vesper, or leave a note…" /><span className="hint">↵</span></div><small>Persistent surface · model calls are optional</small></section>
        {notice && <div className="notice" onClick={() => setNotice('')}>{notice}</div>}
      </section>
    </main>
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)

export {}
