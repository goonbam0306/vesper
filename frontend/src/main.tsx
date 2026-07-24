import React, { FormEvent, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type View = 'home' | 'projects' | 'tasks' | 'calendar' | 'ideas' | 'processes' | 'approvals' | 'connections' | 'settings'
type Resource = Record<string, any>
const requestId = () => crypto.randomUUID()

function App() {
  const [view, setView] = useState<View>('home')
  const [projects, setProjects] = useState<Resource[]>([])
  const [tasks, setTasks] = useState<Resource[]>([])
  const [calendar, setCalendar] = useState<Resource[]>([])
  const [ideas, setIdeas] = useState<Resource[]>([])
  const [processes, setProcesses] = useState<Resource[]>([])
  const [approvals, setApprovals] = useState<Resource[]>([])
  const [connections, setConnections] = useState<Resource[]>([])
  const [settings, setSettings] = useState<Resource>({})
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')
  const [idea, setIdea] = useState('')
  const [projectName, setProjectName] = useState('')
  const [taskTitle, setTaskTitle] = useState('')
  const [eventTitle, setEventTitle] = useState('')
  const [eventStart, setEventStart] = useState('')
  const [eventEnd, setEventEnd] = useState('')
  const [searchResults, setSearchResults] = useState<Resource | null>(null)

  const json = async (url: string) => { const response = await fetch(url); if (!response.ok) throw new Error('Runtime unavailable'); return response.json() }
  const load = async () => {
    const [p, t, c, i, proc, a, con, s] = await Promise.all([
      json('/api/projects'), json('/api/tasks'), json('/api/calendar'), json('/api/ideas'), json('/api/processes'), json('/api/approvals'), json('/api/connections'), json('/api/settings'),
    ])
    setProjects(p.projects || []); setTasks(t.tasks || []); setCalendar(c.calendar || []); setIdeas(i.ideas || [])
    setProcesses(proc.processes || []); setApprovals(a.approvals || []); setConnections(con.connections || []); setSettings(s || {})
  }
  useEffect(() => { load().catch(() => setNotice('Runtime unavailable')) }, [])

  const command = async (url: string, method: string, body: Resource = {}) => {
    const bootstrap = await json('/api/bootstrap')
    const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': bootstrap.session, 'X-Client-Request-ID': requestId() }, body: JSON.stringify(body) })
    if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail?.message || error.detail || 'Command failed') }
    return response.json()
  }
  const createProject = async (e: FormEvent) => { e.preventDefault(); if (!projectName.trim()) return; try { await command('/api/projects', 'POST', { name: projectName.trim() }); setProjectName(''); setNotice('Project committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const createTask = async (e: FormEvent) => { e.preventDefault(); if (!taskTitle.trim()) return; try { await command('/api/tasks', 'POST', { title: taskTitle.trim() }); setTaskTitle(''); setNotice('Task committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const createEvent = async (e: FormEvent) => { e.preventDefault(); if (!eventTitle || !eventStart || !eventEnd) return; try { await command('/api/calendar', 'POST', { title: eventTitle, starts_at: eventStart, ends_at: eventEnd }); setEventTitle(''); setNotice('Calendar item committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const captureIdea = async (e: FormEvent) => { e.preventDefault(); if (!idea.trim()) return; try { await command('/api/ideas', 'POST', { payload: { text: idea.trim() } }); setIdea(''); setNotice('Idea persisted'); await load() } catch (error: any) { setNotice(error.message) } }
  const moveCalendar = async (item: Resource) => { const next = prompt('New start (ISO/local datetime)', item.starts_at); if (!next || next === item.starts_at) return; const parseWallClock = (value: string) => { const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/); if (!match) return NaN; return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5])); }; const formatWallClock = (milliseconds: number) => new Date(milliseconds).toISOString().slice(0, 16); const duration = parseWallClock(item.ends_at) - parseWallClock(item.starts_at); const nextEnd = Number.isFinite(duration) && Number.isFinite(parseWallClock(next)) ? formatWallClock(parseWallClock(next) + duration) : item.ends_at; try { await command(`/api/calendar/${item.calendar_id}`, 'PATCH', { patch: { starts_at: next, ends_at: nextEnd }, expected_revision: item.revision }); setNotice('Calendar move committed; refreshed from Kernel'); await load() } catch (error: any) { setNotice(`Move rejected: ${error.message}`); await load() } }
  const undoCalendar = async (item: Resource) => { try { await command(`/api/calendar/${item.calendar_id}/undo`, 'POST'); setNotice('Compensating undo committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const decide = async (approval: Resource, decision: string) => { try { await command(`/api/approvals/${approval.approval_id}`, 'POST', { decision: decision === 'APPROVE' ? 'APPROVED' : decision === 'REJECT' ? 'REJECTED' : decision }); setNotice(`Approval ${decision.toLowerCase()} committed`); await load() } catch (error: any) { setNotice(error.message) } }
  const saveSettings = async (e: FormEvent) => { e.preventDefault(); try { await command('/api/settings', 'POST', { patch: { director_display_name: settings.director_display_name || '', developer_diagnostics: !!settings.developer_diagnostics } }); setNotice('Settings committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const search = async (e: FormEvent) => { e.preventDefault(); if (!query.trim()) return; try { setSearchResults(await json(`/api/search?q=${encodeURIComponent(query.trim())}`)); setView('home') } catch (error: any) { setNotice(error.message) } }

  const attention = useMemo(() => tasks.filter(task => task.status !== 'DONE').slice(0, 4), [tasks])
  const nav = (next: View) => { setView(next); setSearchResults(null) }
  const page = (name: string, body: React.ReactNode) => <section className="panel page-panel"><div className="panel-head"><h2>{name}</h2><button className="quiet" onClick={() => load().catch(() => setNotice('Refresh failed'))}>Refresh</button></div>{body}</section>

  return <div className="shell">
    <aside className="rail"><div className="brand"><span className="brand-mark">V</span><span>VESPER</span></div><nav>{([['home', 'Home'], ['projects', 'Projects'], ['tasks', 'Tasks'], ['calendar', 'Calendar'], ['ideas', 'Ideas'], ['processes', 'Processes'], ['approvals', 'Approvals'], ['connections', 'Connections'], ['settings', 'Settings']] as [View, string][]).map(([id, label]) => <button className={view === id ? 'active' : ''} onClick={() => nav(id)} key={id}>{label}</button>)}</nav><div className="rail-foot"><span className="pulse" /> Kernel local · ready</div></aside>
    <main className="canvas"><header className="topbar"><form onSubmit={search} className="omnibar"><span>⌕</span><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search…" /><kbd>⌘ K</kbd></form><div className="indicators"><span>{approvals.filter(a => a.decision === 'PENDING').length} approvals</span><span>{tasks.filter(t => t.status !== 'DONE').length} open</span></div></header><section className="content"><div className="eyebrow">{view === 'home' ? 'ATTENTION / TODAY' : view.toUpperCase()}</div>
      {view === 'home' && <><div className="hero"><div><h1>Good work<br /><em>starts here.</em></h1><p>Canonical state lives in the Kernel.</p></div><div className="hero-meta"><strong>{attention.length}</strong><span>open tasks</span></div></div>{searchResults && <section className="panel"><h2>Search results</h2><pre>{JSON.stringify(searchResults, null, 2)}</pre></section>}<div className="grid"><section className="panel"><div className="panel-head"><h2>Next up</h2></div>{attention.map(task => <div className="list-row" key={task.task_id}><span className="check" /> <span>{task.title}</span><small>P{task.priority}</small></div>) || <p className="muted">Nothing urgent.</p>}</section><section className="panel"><div className="panel-head"><h2>Upcoming</h2></div>{calendar.slice(0, 3).map(item => <div className="list-row" key={item.calendar_id}><span className="date-dot" /> <span>{item.title}</span><small>{item.starts_at}</small></div>)}</section></div></>}
      {view === 'projects' && page('Projects', <><form className="inline-form" onSubmit={createProject}><input value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="New project name" /><button>+ Create</button></form>{projects.map(project => <div className="resource-card" key={project.project_id}><div><strong>{project.name}</strong><p>{project.objective || 'No objective yet'}</p></div><span className="tag">{project.status}</span></div>)}</>)}
      {view === 'tasks' && page('Tasks', <><form className="inline-form" onSubmit={createTask}><input value={taskTitle} onChange={e => setTaskTitle(e.target.value)} placeholder="Add a task" /><button>+ Create</button></form>{tasks.map(task => <div className="resource-card" key={task.task_id}><div><strong>{task.title}</strong><p>{task.status} · priority {task.priority}</p></div><button className="quiet" onClick={async () => { try { await command(`/api/tasks/${task.task_id}`, 'PATCH', { patch: { status: task.status === 'DONE' ? 'TODO' : 'DONE' }, expected_revision: task.revision }); await load() } catch (error: any) { setNotice(error.message) } }}>{task.status === 'DONE' ? 'Reopen' : 'Done'}</button></div>)}</>)}
      {view === 'calendar' && page('Calendar', <><p className="muted">Move opens a direct manipulation time editor; the server canonical value is reloaded after every command.</p><form className="event-form" onSubmit={createEvent}><input value={eventTitle} onChange={e => setEventTitle(e.target.value)} placeholder="Event title" /><input type="datetime-local" value={eventStart} onChange={e => setEventStart(e.target.value)} /><input type="datetime-local" value={eventEnd} onChange={e => setEventEnd(e.target.value)} /><button>+ Add event</button></form>{calendar.map(item => <div className="resource-card" key={item.calendar_id}><div><strong>{item.title}</strong><p>{item.starts_at} → {item.ends_at}</p></div><div><button className="quiet" onClick={() => moveCalendar(item)}>Move</button><button className="quiet" onClick={() => undoCalendar(item)}>Undo</button></div></div>)}</>)}
      {view === 'ideas' && page('Idea Inbox', <><p className="muted">Persist first. Classification is optional and never blocks capture.</p><form className="capture" onSubmit={captureIdea}><textarea value={idea} onChange={e => setIdea(e.target.value)} placeholder="What are you noticing?" /><button>Capture idea</button></form>{ideas.map(item => <div className="idea-card" key={item.memory_id}><span>✦</span><div><strong>{item.payload?.text}</strong><small>UNREVIEWED · committed memory</small></div></div>)}</>)}
      {view === 'processes' && page('Processes', <>{processes.length ? processes.map(process => <div className="resource-card" key={process.process_id}><div><strong>{process.process_id}</strong><p>{process.status} · waiting: {process.waiting_reason || 'none'} · parent: {process.parent_id || 'none'} · dependencies: {process.dependency_state}</p><small>result: {process.result_summary || 'none'} · effect: {JSON.stringify(process.effect_summary || {})}</small></div><span className="tag">{process.status}</span></div>) : <p className="muted">No durable processes yet.</p>}</>)}
      {view === 'approvals' && page('Approvals', <>{approvals.length ? approvals.map(approval => <div className="resource-card" key={approval.approval_id}><div><strong>{approval.operation}</strong><p>{approval.target} · {approval.decision}</p><small>Exact structured decision required.</small></div>{approval.decision === 'PENDING' && <div><button className="quiet" onClick={() => decide(approval, 'APPROVE')}>Approve</button><button className="quiet" onClick={() => decide(approval, 'REJECT')}>Reject</button><button className="quiet" onClick={() => decide(approval, 'EDIT')}>Edit</button></div>}</div>) : <p className="muted">No pending approvals.</p>}</>)}
      {view === 'connections' && page('Connections', <>{connections.length ? connections.map(connection => <div className="resource-card" key={`${connection.provider}-${connection.name}`}><div><strong>{connection.name}</strong><p>Provider: {connection.provider} · health: {connection.health} · status: {connection.status}</p><small>{connection.description || 'No description'}</small></div><span className="tag">{connection.risk_class}</span></div>) : <p className="muted">No configured provider or MCP connections. Credentials are never displayed here.</p>}</>)}
      {view === 'settings' && page('Settings', <form className="capture" onSubmit={saveSettings}><label>Director display name<input value={settings.director_display_name || ''} onChange={e => setSettings({ ...settings, director_display_name: e.target.value })} /></label><label><input type="checkbox" checked={!!settings.developer_diagnostics} onChange={e => setSettings({ ...settings, developer_diagnostics: e.target.checked })} /> Developer diagnostics</label><p className="muted">Model route: {settings.model_route?.status || 'unconfigured'} · Web research: {settings.web_research?.status || 'unconfigured'}</p><button>Save settings</button></form>)}
      <section className="persistent"><div><span className="spark">✦</span><input placeholder="Ask Vesper, or leave a note…" /><span className="hint">↵</span></div><small>Persistent surface · model calls are optional</small></section>{notice && <div className="notice" onClick={() => setNotice('')}>{notice}</div>}</section></main></div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
export {}
