import React, { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import './first-boot.css'
import { VesperPresenceIcon, askPresenceState, processPresenceState, type VesperPresenceState } from './components/presence'

type View = 'home' | 'projects' | 'tasks' | 'calendar' | 'ideas' | 'processes' | 'observability' | 'memory' | 'approvals' | 'connections' | 'settings'
type Resource = Record<string, any>
const requestId = () => crypto.randomUUID()
const localDateTime = (date: Date) => { const pad = (value: number) => String(value).padStart(2, '0'); return { date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`, time: `${pad(date.getHours())}:${pad(date.getMinutes())}` } }
export const makeCalendarDefaults = (now = new Date()) => {
  const boundary = new Date(now)
  boundary.setSeconds(0, 0)
  boundary.setMinutes(Math.ceil((boundary.getMinutes() + 1) / 30) * 30)
  if (boundary.getHours() === 0 && boundary.getDate() !== now.getDate()) boundary.setHours(0)
  const end = new Date(boundary.getTime() + 60 * 60 * 1000)
  if (end.getDate() !== boundary.getDate()) boundary.setHours(boundary.getHours() - 1)
  const start = localDateTime(boundary)
  return { date: start.date, startTime: start.time, endTime: localDateTime(new Date(boundary.getTime() + 60 * 60 * 1000)).time }
}

function PresenceFixture() {
  const [blocked, setBlocked] = useState(true)
  const states: VesperPresenceState[] = ['idle', 'thinking', 'retrieving', 'writing', 'waiting', 'blocked']
  return <section data-testid="presence-fixture">{states.map(state => <VesperPresenceIcon key={state} state={state} size={24} testId={`presence-state-${state}`} />)}{([16, 24, 32, 48] as const).map(size => <VesperPresenceIcon key={size} state="idle" size={size} testId={`presence-size-${size}`} />)}<VesperPresenceIcon state="idle" label="Custom Vesper label" testId="presence-labelled" /><VesperPresenceIcon state="idle" decorative testId="presence-decorative" />{blocked && <VesperPresenceIcon state="blocked" testId="presence-blocked" />}<VesperPresenceIcon state="retrieving" testId="presence-retrieving" /><VesperPresenceIcon state="writing" testId="presence-writing" /><button data-testid="presence-fixture-toggle" onClick={() => setBlocked(value => !value)}>Toggle blocked</button></section>
}

function App() {
  const [view, setView] = useState<View>('home')
  const [firstBoot, setFirstBoot] = useState<boolean | null>(null)
  const [setupStep, setSetupStep] = useState<'welcome' | 'connection' | 'model' | 'director'>('welcome')
  const [setupProvider, setSetupProvider] = useState('openai')
  const [setupName, setSetupName] = useState('OpenAI')
  const [setupEndpoint, setSetupEndpoint] = useState('https://api.openai.com/v1')
  const [setupStyle, setSetupStyle] = useState('official')
  const [setupCredential, setSetupCredential] = useState('')
  const [setupModel, setSetupModel] = useState('')
  const [setupConnectionId, setSetupConnectionId] = useState('')
  const [setupDirector, setSetupDirector] = useState('')
  const [setupError, setSetupError] = useState('')
  const [setupBusy, setSetupBusy] = useState(false)
  const [projects, setProjects] = useState<Resource[]>([])
  const [tasks, setTasks] = useState<Resource[]>([])
  const [calendar, setCalendar] = useState<Resource[]>([])
  const [ideas, setIdeas] = useState<Resource[]>([])
  const [processes, setProcesses] = useState<Resource[]>([])
  const [approvals, setApprovals] = useState<Resource[]>([])
  const [connections, setConnections] = useState<Resource[]>([])
  const [mcp, setMcp] = useState<Resource>({ servers: [], capabilities: [], observations: [], effects: [] })
  const [memoryItems, setMemoryItems] = useState<Resource[]>([])
  const [effects, setEffects] = useState<Resource[]>([])
  const [observability, setObservability] = useState<Resource>({})
  const [settings, setSettings] = useState<Resource>({})
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')
  const [idea, setIdea] = useState('')
  const [projectName, setProjectName] = useState('')
  const [taskTitle, setTaskTitle] = useState('')
  const [eventTitle, setEventTitle] = useState('')
  const [eventDate, setEventDate] = useState('')
  const [eventStartTime, setEventStartTime] = useState('')
  const [eventEndTime, setEventEndTime] = useState('')
  const [eventEndTouched, setEventEndTouched] = useState(false)
  const [selectedProject, setSelectedProject] = useState<Resource | null>(null)
  const [askPrompt, setAskPrompt] = useState('')
  const [askConversationId, setAskConversationId] = useState<string | null>(null)
  const [askMessages, setAskMessages] = useState<any[]>([])
  const [askState, setAskState] = useState<'idle' | 'sending' | 'response' | 'failure'>('idle')
  const [askError, setAskError] = useState('')
  const askComposing = useRef(false)
  const askConversationRef = useRef<string | null>(null)
  const askRestoreRequestRef = useRef(0)
  const askRequestIdRef = useRef<string | null>(null)
  const askTranscriptRef = useRef<HTMLDivElement>(null)
  const [searchResults, setSearchResults] = useState<Resource | null>(null)
  const presenceFixture = new URLSearchParams(window.location.search).has('presenceFixture')

  const json = async (url: string) => { const response = await fetch(url); if (!response.ok) throw new Error('Runtime unavailable'); return response.json() }
  const load = async () => {
    const [p, t, c, i, proc, a, con, mcpResult, s, today, effectsResult, memories] = await Promise.all([
      json('/api/projects'), json('/api/tasks'), json('/api/calendar'), json('/api/ideas'), json('/api/processes'), json('/api/approvals'), json('/api/connections'), json('/api/mcp/overview'), json('/api/settings'), json('/api/dashboard/today'), json('/api/effects'), json('/api/memories'),
    ])
    setProjects(p.projects || []); setTasks(t.tasks || []); setCalendar(c.calendar || []); setIdeas(i.ideas || [])
    setProcesses(proc.processes || []); setApprovals(a.approvals || []); setConnections(con.connections || []); setMcp(mcpResult || { servers: [], capabilities: [], observations: [], effects: [] }); setSettings(s || {})
    setMemoryItems(memories.memories || []); setEffects(effectsResult.effects || []); setObservability(today.observability || {})
    if (view === 'processes' && (proc.processes || []).length === 0) setProcesses([])
  }
  useEffect(() => {
    json('/api/first-boot')
      .then(state => { setFirstBoot(!!state.first_boot_completed); setSetupDirector(state.director_display_name || '') })
      .catch(() => { setFirstBoot(false); setNotice('Runtime unavailable') })
    load().catch(() => setNotice('Runtime unavailable'))
  }, [])

  const command = async (url: string, method: string, body: Resource = {}) => {
    const bootstrap = await json('/api/bootstrap')
    const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': bootstrap.session, 'X-Client-Request-ID': requestId() }, body: JSON.stringify(body) })
    if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.detail?.message || error.detail || 'Command failed') }
    return response.json()
  }
  const mergeAskMessages = (messages: any[]) => {
    const seen = new Set<string>()
    return messages.filter(message => {
      const id = String(message.message_id || '')
      if (!id || seen.has(id)) return false
      seen.add(id)
      return true
    })
  }
  const restoreAskConversation = async (conversationId: string | null, preservePending = false) => {
    const restoreRequest = ++askRestoreRequestRef.current
    if (!conversationId) { if (!preservePending) setAskMessages([]); return }
    try {
      const result = await json(`/api/conversations/${conversationId}`)
      if (restoreRequest !== askRestoreRequestRef.current || askConversationRef.current !== conversationId) return
      setAskMessages(current => {
        const persisted = result.messages || []
        if (!preservePending) return mergeAskMessages(persisted)
        const pending = current.filter(message => String(message.message_id).startsWith('pending-'))
        return mergeAskMessages([...persisted, ...pending])
      })
    } catch {
      if (restoreRequest === askRestoreRequestRef.current) { setAskConversationId(null); askConversationRef.current = null; setAskMessages([]) }
    }
  }
  useEffect(() => { askConversationRef.current = askConversationId; void restoreAskConversation(askConversationId) }, [askConversationId])
  useEffect(() => { askTranscriptRef.current?.scrollTo({ top: askTranscriptRef.current.scrollHeight, behavior: 'smooth' }) }, [askMessages, askConversationId])

  const newAskConversation = async () => { try { const result = await command('/api/conversations', 'POST', {}); askConversationRef.current = result.conversation.conversation_id; setAskConversationId(result.conversation.conversation_id); setAskMessages([]); setAskError(''); setAskState('idle') } catch (error: any) { setAskError(error.message) } }
  const invokeAsk = async () => {
    const prompt = askPrompt.trim()
    if (!prompt || askState === 'sending') return
    const clientRequestId = requestId()
    askRequestIdRef.current = clientRequestId
    const pendingMessageId = `pending-${clientRequestId}`
    setAskState('sending'); setAskError(''); setAskPrompt('')
    setAskMessages(current => [...current, { message_id: pendingMessageId, role: 'USER', content: prompt }])
    try {
      const result = await command('/api/director/submit', 'POST', { input: prompt, conversation_id: askConversationId, client_request_id: clientRequestId, principal: 'director' })
      const returnedConversationId = String(result.conversation_id || askConversationId || '')
      const status = String(result.status || result.code || result.error?.code || '').toUpperCase()
      const failure = ['FAILED', 'WAITING', 'MODEL_NOT_CONFIGURED', 'MODEL_EMPTY_OUTPUT', 'ACTION_FAILED', 'CONNECTION_NOT_FOUND', 'CREDENTIAL_NOT_CONFIGURED'].includes(status) || Boolean(result.error)
      if (failure) throw new Error(String(result.error?.message || result.message || result.error || status || 'Vesper couldn\'t complete that request.'))
      const assistant = result.assistant_message
      if (!returnedConversationId || !assistant || assistant.role !== 'ASSISTANT' || typeof assistant.content !== 'string' || assistant.content.length === 0) {
        throw new Error('Assistant response was empty or malformed')
      }
      askConversationRef.current = returnedConversationId
      if (!askConversationId) setAskConversationId(returnedConversationId)
      setAskMessages(current => {
        const withoutPending = current.filter(message => message.message_id !== pendingMessageId)
        const existingIds = new Set(withoutPending.map(message => message.message_id))
        return mergeAskMessages([...withoutPending, ...(existingIds.has(result.user_message.message_id) ? [] : [result.user_message]), ...(existingIds.has(assistant.message_id) ? [] : [assistant])])
      })
      await restoreAskConversation(returnedConversationId, false)
      setAskState('response')
    } catch (error: any) {
      const message = error.message?.toLowerCase().includes('not configured') ? 'AI connection is not configured' : error.message || 'Vesper couldn\'t complete that request.'
      setAskError(message); setAskMessages(current => [...current, { message_id: `error-${Date.now()}`, role: 'ERROR', content: message }]); setAskState('failure')
    }
  }
  const submitAsk = (e: FormEvent) => { e.preventDefault(); void invokeAsk() }
  const handleAskKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !askComposing.current) { e.preventDefault(); void invokeAsk() } }
  const createProject = async (e: FormEvent) => { e.preventDefault(); if (!projectName.trim()) return; try { await command('/api/projects', 'POST', { name: projectName.trim() }); setProjectName(''); setNotice('Project committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const createTask = async (e: FormEvent) => { e.preventDefault(); if (!taskTitle.trim()) return; try { await command('/api/tasks', 'POST', { title: taskTitle.trim() }); setTaskTitle(''); setNotice('Task committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const openCalendarCreateForm = () => { const defaults = makeCalendarDefaults(); setEventDate(defaults.date); setEventStartTime(defaults.startTime); setEventEndTime(defaults.endTime); setEventEndTouched(false); setEventTitle(''); setView('calendar'); setSearchResults(null) }
  const resetEventFormDefaults = () => { const defaults = makeCalendarDefaults(); setEventDate(defaults.date); setEventStartTime(defaults.startTime); setEventEndTime(defaults.endTime); setEventEndTouched(false) }
  const handleStartTimeChange = (value: string) => { const previousStart = eventStartTime; setEventStartTime(value); if (!eventEndTouched && eventEndTime && previousStart) { const [ph, pm] = previousStart.split(':').map(Number); const [nh, nm] = value.split(':').map(Number); const duration = (nh * 60 + nm) - (ph * 60 + pm); const [eh, em] = eventEndTime.split(':').map(Number); const end = eh * 60 + em; const next = end + duration; const normalized = ((next % 1440) + 1440) % 1440; setEventEndTime(`${String(Math.floor(normalized / 60)).padStart(2, '0')}:${String(normalized % 60).padStart(2, '0')}`) } }
  const createEvent = async (e: FormEvent) => { e.preventDefault(); const starts_at = `${eventDate}T${eventStartTime}`; const ends_at = `${eventDate}T${eventEndTime}`; if (!eventTitle || !eventDate || !eventStartTime || !eventEndTime || ends_at <= starts_at) { setNotice('End time must be after start time'); return } try { await command('/api/calendar', 'POST', { title: eventTitle, starts_at, ends_at }); setEventTitle(''); resetEventFormDefaults(); setNotice('Calendar item committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const captureIdea = async (e: FormEvent) => { e.preventDefault(); if (!idea.trim()) return; try { await command('/api/ideas', 'POST', { payload: { text: idea.trim() } }); setIdea(''); setNotice('Idea persisted'); await load() } catch (error: any) { setNotice(error.message) } }
  const handleIdeaKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && !askComposing.current) { e.preventDefault(); void captureIdea(e) } }
  const moveCalendar = async (item: Resource) => { const next = prompt('New start (ISO/local datetime)', item.starts_at); if (!next || next === item.starts_at) return; const parseWallClock = (value: string) => { const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/); if (!match) return NaN; return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5])); }; const formatWallClock = (milliseconds: number) => new Date(milliseconds).toISOString().slice(0, 16); const duration = parseWallClock(item.ends_at) - parseWallClock(item.starts_at); const nextEnd = Number.isFinite(duration) && Number.isFinite(parseWallClock(next)) ? formatWallClock(parseWallClock(next) + duration) : item.ends_at; try { await command(`/api/calendar/${item.calendar_id}`, 'PATCH', { patch: { starts_at: next, ends_at: nextEnd }, expected_revision: item.revision }); setNotice('Calendar move committed; refreshed from Kernel'); await load() } catch (error: any) { setNotice(`Move rejected: ${error.message}`); await load() } }
  const undoCalendar = async (item: Resource) => { try { await command(`/api/calendar/${item.calendar_id}/undo`, 'POST'); setNotice('Compensating undo committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const decide = async (approval: Resource, decision: string) => { try { await command(`/api/approvals/${approval.approval_id}`, 'POST', { decision: decision === 'APPROVE' ? 'APPROVED' : decision === 'REJECT' ? 'REJECTED' : decision }); setNotice(`Approval ${decision.toLowerCase()} committed`); await load() } catch (error: any) { setNotice(error.message) } }
  const saveSettings = async (e: FormEvent) => { e.preventDefault(); try { await command('/api/settings', 'POST', { patch: { director_display_name: settings.director_display_name || '', developer_diagnostics: !!settings.developer_diagnostics } }); setNotice('Settings committed'); await load() } catch (error: any) { setNotice(error.message) } }
  const search = async (e: FormEvent) => { e.preventDefault(); if (!query.trim()) return; try { setSearchResults(await json(`/api/search?q=${encodeURIComponent(query.trim())}`)); setView('home') } catch (error: any) { setNotice(error.message) } }

  const selectProvider = (provider: string) => {
    const presets: Record<string, [string, string, string]> = {
      openai: ['OpenAI', 'https://api.openai.com/v1', 'official'],
      anthropic: ['Anthropic', 'https://api.anthropic.com/v1', 'official'],
      gemini: ['Gemini', 'https://generativelanguage.googleapis.com/v1beta', 'official'],
      custom: ['Custom connection', '', 'openai-compatible'],
      local: ['Local endpoint', 'http://127.0.0.1:8080/v1', 'openai-compatible'],
    }
    const [name, endpoint, style] = presets[provider]
    setSetupProvider(provider); setSetupName(name); setSetupEndpoint(endpoint); setSetupStyle(style); setSetupCredential(''); setSetupError('')
  }
  const validateConnection = async (e: FormEvent) => {
    e.preventDefault(); setSetupBusy(true); setSetupError('')
    try {
      const result = await command('/api/first-boot/connection', 'POST', { provider: setupProvider, display_name: setupName, base_url: setupEndpoint, api_style: setupStyle, credential: setupCredential || undefined, model_id: setupModel })
      setSetupConnectionId(result.connection?.connection_id || ''); setSetupCredential(''); setSetupStep('model')
    } catch (error: any) { setSetupCredential(''); setSetupError(error.message) } finally { setSetupBusy(false) }
  }
  const finishFirstBoot = async (e: FormEvent) => {
    e.preventDefault(); setSetupBusy(true); setSetupError('')
    try {
      const model_route = setupModel && setupConnectionId ? { status: 'configured', connection_id: setupConnectionId, provider: setupProvider, model_id: setupModel, base_url: setupEndpoint, api_style: setupStyle, endpoint_type: setupProvider === 'local' ? 'local' : 'custom' } : { status: 'unconfigured' }
      await command('/api/first-boot/complete', 'POST', { director_display_name: setupDirector, model_route })
      setFirstBoot(true); await load()
    } catch (error: any) { setSetupError(error.message) } finally { setSetupBusy(false) }
  }
  const attention = useMemo(() => tasks.filter(task => task.status !== 'DONE').slice(0, 4), [tasks])
  const nav = (next: View) => { if (next === 'calendar') { openCalendarCreateForm(); return } setView(next); setSearchResults(null); if (next === 'processes') load().catch(() => setNotice('Refresh failed')) }
  const page = (name: string, body: React.ReactNode) => <section className="panel page-panel"><div className="panel-head"><h2>{name}</h2><button className="quiet" onClick={() => load().catch(() => setNotice('Refresh failed'))}>Refresh</button></div>{body}</section>

  if (firstBoot === null) return <main className="setup-shell"><p>Loading Vesper…</p></main>
  if (!firstBoot) return <main className="setup-shell"><section className="setup-card">
    {setupStep === 'welcome' && <><span className="eyebrow">FIRST BOOT</span><h1>Welcome to Vesper</h1><p>Set up your workspace in a few steps. AI is optional and can be added later.</p><button autoFocus onClick={() => setSetupStep('connection')}>Set up Vesper</button></>}
    {setupStep === 'connection' && <><span className="eyebrow">AI CONNECTION · OPTIONAL</span><h1>Connect an AI provider</h1><p>Choose a provider, a compatible proxy, or continue without AI.</p><div className="provider-grid">{[['openai','OpenAI'],['anthropic','Anthropic'],['gemini','Gemini'],['custom','Custom / OpenAI-compatible'],['local','Local endpoint']].map(([id,label]) => <button type="button" className={setupProvider === id ? 'active' : 'quiet'} onClick={() => selectProvider(id)} key={id}>{label}</button>)}</div><form className="capture" onSubmit={validateConnection}><label>Display name<input value={setupName} onChange={e => setSetupName(e.target.value)} required /></label><label>Endpoint URL<input value={setupEndpoint} onChange={e => setSetupEndpoint(e.target.value)} required /></label><label>API style<select value={setupStyle} onChange={e => setSetupStyle(e.target.value)}><option value="official">Provider API</option><option value="openai-compatible">OpenAI-compatible</option></select></label><label>API key {setupProvider === 'local' && '(optional)'}<input type="text" inputMode="text" autoComplete="off" value={setupCredential} onChange={e => setSetupCredential(e.target.value)} /></label><label>Model ID (optional)<input value={setupModel} onChange={e => setSetupModel(e.target.value)} placeholder="e.g. gpt-4.1-mini" /></label>{setupError && <p className="setup-error">{setupError}</p>}<button disabled={setupBusy}>{setupBusy ? 'Testing…' : 'Test connection'}</button></form><button className="quiet" onClick={() => { setSetupModel(''); setSetupStep('director') }}>Set up later</button></>}
    {setupStep === 'model' && <><span className="eyebrow">DEFAULT MODEL</span><h1>Choose a default model</h1><p>This is the model Vesper will use for AI requests. You can change it later in Settings.</p><form className="capture" onSubmit={e => { e.preventDefault(); if (setupModel.trim()) setSetupStep('director'); else setSetupError('Enter the model ID you want to use.') }}><label>Default model<input autoFocus value={setupModel} onChange={e => setSetupModel(e.target.value)} required /></label>{setupError && <p className="setup-error">{setupError}</p>}<button>Continue</button></form></>}
    {setupStep === 'director' && <><span className="eyebrow">DIRECTOR SETUP</span><h1>Who is directing Vesper?</h1><form className="capture" onSubmit={finishFirstBoot}><label>Director display name<input autoFocus value={setupDirector} onChange={e => setSetupDirector(e.target.value)} required /></label>{setupError && <p className="setup-error">{setupError}</p>}<button disabled={setupBusy}>{setupBusy ? 'Finishing…' : 'Finish'}</button></form></>}
  </section></main>

  return <div className="shell">
    <aside className="rail"><div className="brand"><VesperPresenceIcon state="idle" decorative size={24} testId="vesper-brand-presence" /><span>VESPER</span></div><nav>{([['home', 'Home'], ['projects', 'Projects'], ['tasks', 'Tasks'], ['calendar', 'Calendar'], ['ideas', 'Ideas'], ['processes', 'Processes'], ['observability', 'Observability'], ['memory', 'Memory'], ['approvals', 'Approvals'], ['connections', 'Connections'], ['settings', 'Settings']] as [View, string][]).map(([id, label]) => <button className={view === id ? 'active' : ''} onClick={() => nav(id)} key={id}>{label}</button>)}</nav><div className="rail-foot"><span className="pulse" /> Kernel local · ready</div></aside>
    <main className="canvas"><header className="topbar"><form onSubmit={search} className="omnibar"><span>⌕</span><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search…" /><kbd>⌘ K</kbd></form><div className="indicators"><span>{approvals.filter(a => a.decision === 'PENDING').length} approvals</span><span>{tasks.filter(t => t.status !== 'DONE').length} open</span></div></header><section className="content"><div className="eyebrow">{view === 'home' ? 'ATTENTION / TODAY' : view.toUpperCase()}</div>
      {view === 'home' && <><div className="hero"><div><h1>Good work starts here.</h1><p>Director workspace · canonical state lives in the Kernel.</p></div></div>{searchResults && <section className="panel"><h2>Search results</h2><pre>{JSON.stringify(searchResults, null, 2)}</pre></section>}<div className="grid"><section className="panel"><div className="panel-head"><h2>Tasks <small>{tasks.filter(task => task.status !== 'DONE').length} open</small></h2></div>{attention.map(task => <div className="list-row" key={task.task_id}><span className="check" /> <span>{task.title}</span><small>P{task.priority}</small></div>)}</section><section className="panel"><div className="panel-head"><h2>Today / Calendar</h2></div>{calendar.slice(0, 3).map(item => <div className="list-row" key={item.calendar_id}><span className="date-dot" /> <span>{item.title}</span><small>{item.starts_at}</small></div>)}</section></div></>}
      {view === 'projects' && page('Projects', selectedProject ? <><button className="quiet" onClick={() => setSelectedProject(null)}>← All projects</button><div className="project-detail"><h3>{selectedProject.name}</h3><p>{selectedProject.status} · {selectedProject.objective || 'No objective yet'}</p><h4>Tasks</h4>{tasks.filter(task => task.project_id === selectedProject.project_id).map(task => <div className="list-row" key={task.task_id}><span>{task.title}</span><small>{task.status}</small></div>)}{tasks.every(task => task.project_id !== selectedProject.project_id) && <p className="muted">No related tasks.</p>}<h4>Calendar / Milestones</h4>{calendar.filter(item => item.project_id === selectedProject.project_id).map(item => <div className="list-row" key={item.calendar_id}><span>{item.title}</span><small>{item.starts_at}</small></div>)}{calendar.every(item => item.project_id !== selectedProject.project_id) && <p className="muted">No related calendar items.</p>}</div></> : <><form className="inline-form" onSubmit={createProject}><input value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="New project name" /><button>+ Create</button></form>{projects.map(project => <button className="resource-card project-card" key={project.project_id} onClick={() => setSelectedProject(project)}><div><strong>{project.name}</strong><p>{project.objective || 'No objective yet'}</p></div><span className="tag">{project.status}</span></button>)}</>)}
      {view === 'tasks' && page('Tasks', <><form className="inline-form" onSubmit={createTask}><input value={taskTitle} onChange={e => setTaskTitle(e.target.value)} placeholder="Add a task" /><button>+ Create</button></form>{tasks.map(task => <div className="resource-card" key={task.task_id}><div><strong>{task.title}</strong><p>{task.status} · priority {task.priority}</p></div><button className="quiet" onClick={async () => { try { await command(`/api/tasks/${task.task_id}`, 'PATCH', { patch: { status: task.status === 'DONE' ? 'TODO' : 'DONE' }, expected_revision: task.revision }); await load() } catch (error: any) { setNotice(error.message) } }}>{task.status === 'DONE' ? 'Reopen' : 'Done'}</button></div>)}</>)}
      {view === 'calendar' && page('Calendar', <><p className="muted">Move opens a direct manipulation time editor; the server canonical value is reloaded after every command.</p><form className="event-form" onSubmit={createEvent}><input value={eventTitle} onChange={e => setEventTitle(e.target.value)} placeholder="Event title" /><label>Date<input aria-label="Date" type="date" value={eventDate} onChange={e => setEventDate(e.target.value)} /></label><label>Start time<input aria-label="Start time" type="time" value={eventStartTime} onChange={e => handleStartTimeChange(e.target.value)} /></label><label>End time<input aria-label="End time" type="time" value={eventEndTime} onChange={e => { setEventEndTouched(true); setEventEndTime(e.target.value) }} /></label><button>+ Add event</button></form>{calendar.map(item => <div className="resource-card" key={item.calendar_id}><div><strong>{item.title}</strong><p>{item.starts_at} → {item.ends_at}</p></div><div><button className="quiet" onClick={() => moveCalendar(item)}>Move</button><button className="quiet" onClick={() => undoCalendar(item)}>Undo</button></div></div>)}</>)}
      {view === 'ideas' && page('Idea Inbox', <><p className="muted">Persist first. Classification is optional and never blocks capture.</p><form className="capture" onSubmit={captureIdea}><textarea value={idea} onChange={e => setIdea(e.target.value)} onKeyDown={handleIdeaKeyDown} onCompositionStart={() => { askComposing.current = true }} onCompositionEnd={() => { askComposing.current = false }} placeholder="What are you noticing?" /><small>Enter to save · Shift+Enter for new line</small><button>Capture idea</button></form>{ideas.map(item => <div className="idea-card" key={item.memory_id}><span>✦</span><div><strong>{item.payload?.text}</strong><small>UNREVIEWED · committed memory</small></div></div>)}</>)}
      {view === 'processes' && page('Processes', <>{processes.length ? processes.map(process => <div className="resource-card" key={process.process_id}><div><strong>{process.process_id}</strong><p>{process.status} · waiting: {process.waiting_reason || 'none'} · parent: {process.parent_id || 'none'} · dependencies: {process.dependency_state}</p><small>result: {process.result_summary || 'none'} · effect: {JSON.stringify(process.effect_summary || {})}</small></div><VesperPresenceIcon state={processPresenceState(process.status)} size={24} testId={`process-presence-${process.process_id}`} /><span className="tag">{process.status}</span></div>) : <><p className="muted">No durable processes yet.</p><div data-testid="empty-processes">No durable processes yet.</div></>}</>)}
      {view === 'observability' && page('Observability', <><div className="grid"><div className="panel"><h3>Runtime counters</h3><div className="list-row"><span>Processes</span><strong>{observability.process_count || 0}</strong></div><div className="list-row"><span>Effects</span><strong>{observability.effect_count || effects.length}</strong></div><div className="list-row"><span>Approvals</span><strong>{observability.approval_count || approvals.length}</strong></div><div className="list-row"><span>Event cursor</span><strong>{observability.event_cursor || 0}</strong></div></div><div className="panel"><h3>Verification</h3><p>{observability.verification?.source || 'kernel_snapshot'} · {observability.verification?.status || 'available'}</p></div></div><h3>Recent effects</h3>{effects.length ? effects.map(effect => <div className="resource-card" key={effect.effect_id || JSON.stringify(effect)}><strong>{effect.operation || effect.effect_id || 'Effect'}</strong><p>{effect.status || 'recorded'} · process {effect.process_id || 'none'}</p></div>) : <p className="muted">No recorded effects.</p>}</>)}
      {view === 'memory' && page('Memory', <><p className="muted">Inspectable latest memory state. Provenance is shown without exposing credentials or hidden reasoning.</p>{memoryItems.length ? memoryItems.map(item => <div className="resource-card" key={`${item.memory_id}-${item.revision}`}><div><strong>{item.kind}</strong><p>{JSON.stringify(item.payload)}</p><small>memory {item.memory_id} · revision {item.revision} · validity {item.validity}</small><br /><small>provenance {JSON.stringify(item.provenance)}</small></div></div>) : <p className="muted">No memories recorded.</p>}</>)}
      {view === 'approvals' && page('Approvals', <>{approvals.length ? approvals.map(approval => <div className="resource-card" key={approval.approval_id}><div><strong>{approval.operation}</strong><p>{approval.target} · {approval.decision}</p><small>Exact structured decision required.</small></div>{approval.decision === 'PENDING' && <div><button className="quiet" onClick={() => decide(approval, 'APPROVE')}>Approve</button><button className="quiet" onClick={() => decide(approval, 'REJECT')}>Reject</button><button className="quiet" onClick={() => decide(approval, 'EDIT')}>Edit</button></div>}</div>) : <p className="muted">No pending approvals.</p>}</>)}
      {view === 'connections' && page('Connections · External Capabilities', <><p className="muted">MCP is a transport only. Observations remain untrusted evidence; Vesper Kernel retains authority and effects require explicit approval. Credentials are never displayed here.</p><section className="panel"><h3>MCP connections</h3>{(mcp.servers || []).length ? (mcp.servers || []).map((server: Resource) => <div className="resource-card" key={server.server_id}><div><strong>{server.display_name}</strong><p>Transport: {server.transport} · health: {server.health}</p><small>{server.approved_local ? 'Approved local/custom sandbox' : 'Not approved'}</small>{server.last_error_code && <><br /><small>Last error: {server.last_error_code}</small></>}</div><span className="tag">{server.health}</span></div>) : <p className="muted">No MCP sandbox registered.</p>}</section><section className="panel"><h3>Discovered capabilities</h3>{(mcp.capabilities || []).length ? (mcp.capabilities || []).map((capability: Resource) => <div className="resource-card" key={capability.capability_id}><div><strong>{capability.name}</strong><p>{capability.effect_class} · policy state: {capability.state}</p><small>Schema {capability.schema_hash?.slice(0, 12)} · generation {capability.generation} · untrusted external contract</small></div><span className="tag">{capability.risk_class}</span></div>) : <p className="muted">Discover a registered local/custom MCP server to expose candidate capabilities.</p>}</section><section className="panel"><h3>Evidence and effect recovery</h3>{(mcp.observations || []).map((observation: Resource) => <div className="list-row" key={observation.observation_id}><span>Observation {observation.capability_id} · evidence only</span><small>{observation.stale ? 'STALE' : observation.observed_at}</small></div>)}{(mcp.effects || []).map((effect: Resource) => <div className="list-row" key={effect.effect_id}><span>Effect {effect.capability_id} · {effect.status}</span><small>{effect.error_code || (effect.receipt ? 'Kernel receipt confirmed' : 'Awaiting explicit approval')}</small></div>)}{!(mcp.observations || []).length && !(mcp.effects || []).length && <p className="muted">No MCP evidence or effect records.</p>}</section>{connections.length ? <section className="panel"><h3>Legacy connection records</h3>{connections.map(connection => <div className="resource-card" key={`${connection.provider}-${connection.name}`}><div><strong>{connection.name}</strong><p>Provider: {connection.provider} · health: {connection.health} · status: {connection.status}</p></div><span className="tag">{connection.risk_class}</span></div>)}</section> : null}</>)}
      {view === 'settings' && page('Settings', <form className="capture" onSubmit={saveSettings}><label>Director display name<input value={settings.director_display_name || ''} onChange={e => setSettings({ ...settings, director_display_name: e.target.value })} /></label><label><input type="checkbox" checked={!!settings.developer_diagnostics} onChange={e => setSettings({ ...settings, developer_diagnostics: e.target.checked })} /> Developer diagnostics</label><p className="muted">Model route: {settings.model_route?.status || 'unconfigured'} · Web research: {settings.web_research?.status || 'unconfigured'}</p><button>Save settings</button></form>)}
      <section className="persistent"><div className="panel-head"><strong>Ask V.</strong><VesperPresenceIcon state={askPresenceState(askState)} size={24} testId="ask-presence-icon" /><button type="button" className="quiet" onClick={newAskConversation}>New conversation</button></div><div className="ask-transcript" ref={askTranscriptRef} aria-live="polite">{askMessages.map(message => <div className={`ask-turn ${message.role.toLowerCase()}`} key={message.message_id}><strong>{message.role === 'USER' ? 'You' : message.role === 'ASSISTANT' ? 'Vesper' : 'Status'}</strong><p>{message.content}</p></div>)}{askState === 'sending' && <div className="ask-turn system_status"><p>Vesper is thinking…</p></div>}</div>{askState === 'response' && <span role="status" className="sr-only">VESPER_READY</span>}<form onSubmit={submitAsk}><div><VesperPresenceIcon state={askPresenceState(askState)} size={16} decorative /><textarea aria-label="Ask Vesper" value={askPrompt} onChange={e => setAskPrompt(e.target.value)} onKeyDown={handleAskKeyDown} onCompositionStart={() => { askComposing.current = true }} onCompositionEnd={() => { askComposing.current = false }} placeholder="Ask Vesper, or leave a note…" rows={1} /><button type="submit" disabled={askState === 'sending' || !askPrompt.trim()}>{askState === 'sending' ? 'Sending…' : 'Send'}</button></div></form>{askState === 'failure' && <p role="alert">{askError}{askError === 'AI connection is not configured' && <> <button type="button" onClick={() => nav('connections')}>Set up AI</button></>}</p>}<small>Persistent surface · Enter to send · Shift+Enter for new line</small></section>{presenceFixture && <PresenceFixture />}{notice && <div className="notice" onClick={() => setNotice('')}>{notice}</div>}</section></main></div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
export {}
