import { expect, test } from '@playwright/test'
import { readRuntimeEvidence } from './support/runtime-evidence'
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http'
import { mkdtemp, rm, readFile, readdir } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawn, type ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoDir = path.resolve(frontendDir, '..')
const pythonCommand = process.env.VESPER_E2E_PYTHON ?? process.env.PYTHON ?? 'python3'

type Child = { process: ChildProcess; output: () => string }
type WireRequest = { path: string; model?: string; authorization?: string; body: any }
type Harness = { home: string; dbPath: string; secretRoot: string; fake: Server; fakePort: number; backendPort: number; frontendPort: number; requests: WireRequest[]; backend: Child; frontend: Child; frontendUrl: string; restart: () => Promise<void>; close: () => Promise<void> }

async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const s = createServer(); s.once('error', reject)
    s.listen(0, '127.0.0.1', () => { const port = (s.address() as { port: number }).port; s.close(e => e ? reject(e) : resolve(port)) })
  })
}
function child(command: string, args: string[], cwd: string, env: NodeJS.ProcessEnv): Child {
  const process = spawn(command, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] }); let output = ''
  process.stdout?.on('data', c => { output += String(c) }); process.stderr?.on('data', c => { output += String(c) })
  return { process, output: () => output }
}
async function stop(c: Child) { if (c.process.exitCode === null) { c.process.kill('SIGTERM'); await new Promise(r => setTimeout(r, 250)); if (c.process.exitCode === null) c.process.kill('SIGKILL') } }
async function waitFor(url: string, process?: Child) { for (let i = 0; i < 100; i++) { try { if ((await fetch(url, { headers: { Host: '127.0.0.1' } })).ok) return } catch {} await new Promise(r => setTimeout(r, 100)) } throw new Error(`not ready: ${url}\n${process?.output() ?? ''}`) }
async function fakeProvider(): Promise<{ server: Server; port: number; requests: WireRequest[] }> {
  const requests: WireRequest[] = []
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const chunks: Buffer[] = []; req.on('data', c => chunks.push(Buffer.from(c))); req.on('end', () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {}
      requests.push({ path: req.url || '', model: body.model, authorization: req.headers.authorization, body })
      if (req.headers.authorization?.includes('WRONG_CREDENTIAL')) { const text = JSON.stringify({ error: { message: 'authentication failed' } }); res.writeHead(401, { 'content-type': 'application/json' }); res.end(text); return }
      if (body.model === 'missing-model') { const text = JSON.stringify({ error: { message: 'model unavailable' } }); res.writeHead(404, { 'content-type': 'application/json' }); res.end(text); return }
      const userText = JSON.stringify(body.messages ?? body.prompt ?? body.input ?? body)
      const answer = userText.includes('할 일로 Kernel browser conformance task') ? '{"action":"CREATE_TASK","title":"Kernel browser conformance task"}' : userText.includes('두 번째 Kernel execution test') ? 'AUDIT_RESPONSE_2' : userText.includes('안녕 Vesper') ? 'AUDIT_RESPONSE_1' : 'AUDIT_RESPONSE_UNKNOWN'
      const payload = req.url?.endsWith('/models') ? { data: [{ id: 'vesper-test-model' }] } : { choices: [{ message: { content: answer } }] }
      const text = JSON.stringify(payload); res.writeHead(200, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(text) }); res.end(text)
    })
  })
  await new Promise<void>((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', () => resolve()) })
  return { server, port: (server.address() as { port: number }).port, requests }
}
async function start(): Promise<Harness> {
  const home = await mkdtemp(path.join(tmpdir(), 'vesper-first-boot-')); const secretRoot = await mkdtemp(path.join(tmpdir(), 'vesper-secrets-')); const bp = await freePort(); const fp = await freePort(); const fake = await fakeProvider()
  const env = { ...process.env, VESPER_HOME: home, VESPER_TEST_SECRET_ROOT: secretRoot, PYTHONUNBUFFERED: '1' }
  const program = [
    'from pathlib import Path', 'from vesper.api import Runtime, create_app', 'import uvicorn',
    'from tests.e2e_secret_store import FileBackedTestSecretStore', `runtime = Runtime(Path(${JSON.stringify(home)}), secret_store=FileBackedTestSecretStore(Path(${JSON.stringify(secretRoot)})))`, 'runtime.start()', 'app = create_app(runtime)',
    `uvicorn.run(app, host='127.0.0.1', port=${bp})`,
  ].join('\n')
  let backend = child(pythonCommand, ['-c', program], repoDir, env)
  await waitFor(`http://127.0.0.1:${bp}/health`, backend)
  let frontend = child('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(fp), '--strictPort'], frontendDir, { ...env, VESPER_API_TARGET: `http://127.0.0.1:${bp}` })
  const frontendUrl = `http://127.0.0.1:${fp}`; await waitFor(frontendUrl)
  const restart = async () => {
    await stop(frontend); await stop(backend)
    backend = child(pythonCommand, ['-c', program], repoDir, env)
    await waitFor(`http://127.0.0.1:${bp}/health`, backend)
    frontend = child('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(fp), '--strictPort'], frontendDir, { ...env, VESPER_API_TARGET: `http://127.0.0.1:${bp}` })
    await waitFor(frontendUrl, frontend)
  }
  return { home, dbPath: path.join(home, 'vesper.sqlite3'), secretRoot, fake: fake.server, fakePort: fake.port, backendPort: bp, frontendPort: fp, requests: fake.requests, get backend() { return backend }, get frontend() { return frontend }, frontendUrl, restart, close: async () => { await stop(frontend); await stop(backend); await new Promise<void>(r => fake.server.close(() => r())); await rm(home, { recursive: true, force: true }); await rm(secretRoot, { recursive: true, force: true }) } }
}

test('Closure A.7 configured Browser Director path', async ({ page }) => {
  const h = await start(); const network = { director: 0, legacy: 0 }
  try {
    page.on('request', request => { if (request.url().includes('/api/director/submit')) network.director++; if (request.url().includes('/api/model/invoke')) network.legacy++ })
    const credential = `A7_${crypto.randomUUID()}`
    await page.goto(h.frontendUrl); await page.getByRole('button', { name: 'Set up Vesper' }).click(); await page.getByRole('button', { name: 'Local endpoint' }).click()
    await page.getByLabel('Endpoint URL').fill(`http://127.0.0.1:${h.fakePort}/v1`); await page.getByLabel('API key (optional)').fill(credential); await page.getByLabel('Model ID (optional)').fill('vesper-test-model'); await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByRole('heading', { name: 'Choose a default model' })).toBeVisible(); await page.getByLabel('Default model').fill('vesper-test-model'); await page.getByRole('button', { name: 'Continue' }).click(); await page.getByLabel('Director display name').fill('A7 Director'); await page.getByRole('button', { name: 'Finish' }).click(); await expect(page.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
    const ask = page.getByLabel('Ask Vesper'); await ask.fill('안녕 Vesper'); await ask.press('Enter'); await expect(page.getByRole('status')).toHaveText(/AUDIT_RESPONSE_1|VESPER_READY/); await expect(page.locator('.ask-transcript').getByText(/AUDIT_RESPONSE_1|VESPER_READY/)).toBeVisible()
    await ask.fill('두 번째 Kernel execution test'); await ask.press('Enter'); await expect(page.getByRole('status')).toHaveText(/AUDIT_RESPONSE_2|VESPER_READY/)
    await ask.fill('할 일로 Kernel browser conformance task 추가해줘'); const taskResponse = page.waitForResponse(r => r.url().includes('/api/director/submit')); await ask.press('Enter'); await taskResponse; await expect(page.locator('.ask-transcript')).toContainText('Task에 추가했습니다'); await expect(page.locator('.ask-transcript').getByText('Task에 추가했습니다: Kernel browser conformance task', { exact: true })).toBeVisible()
    expect(network.director).toBeGreaterThanOrEqual(2); expect(network.legacy).toBe(0); const cognition = h.requests.filter(r => r.path.includes('/chat/completions') && JSON.stringify(r.body).includes('안녕 Vesper') || r.path.includes('/chat/completions') && JSON.stringify(r.body).includes('두 번째 Kernel execution test')); expect(cognition).toHaveLength(2); expect(cognition.every(r => r.model === 'vesper-test-model')).toBeTruthy(); expect(cognition.every(r => r.authorization === `Bearer ${credential}`)).toBeTruthy(); expect(JSON.stringify(cognition[0].body)).toContain('안녕 Vesper'); expect(JSON.stringify(cognition[1].body)).toContain('두 번째 Kernel execution test')
    const body = await page.locator('.ask-transcript').innerText(); expect(body).toContain('안녕 Vesper'); expect(body).toContain('두 번째 Kernel execution test'); expect(body).toContain('Kernel browser conformance task'); expect(body).toMatch(/AUDIT_RESPONSE_1|VESPER_READY/); expect(body).toMatch(/AUDIT_RESPONSE_2|VESPER_READY/)
    const evidence = await readRuntimeEvidence(h.dbPath); const messages = evidence.conversation_messages; const conversations = evidence.conversations; expect(conversations).toHaveLength(1); const C1 = conversations[0].conversation_id; const users = messages.filter((m: any) => m.conversation_id === C1 && m.role === 'USER'); const assistants = messages.filter((m: any) => m.conversation_id === C1 && m.role === 'ASSISTANT'); expect(users).toHaveLength(3); expect(assistants).toHaveLength(3)
    const [u1, u2, u3] = users; const [s1, s2, s3] = assistants; const processes = evidence.processes; const p1 = processes.find((p: any) => p.process_id === u1.process_id); const p2 = processes.find((p: any) => p.process_id === u2.process_id); const p3 = processes.find((p: any) => p.process_id === u3.process_id); expect(new Set([p1.process_id, p2.process_id, p3.process_id]).size).toBe(3); expect([p1, p2, p3].every((p: any) => p.status === 'COMPLETED')).toBeTruthy()
    const attempts = evidence.cognitive_attempts; const a1 = attempts.find((a: any) => a.process_id === p1.process_id); const a2 = attempts.find((a: any) => a.process_id === p2.process_id); expect(a1.attempt_id).not.toBe(a2.attempt_id); expect(s1.process_id).toBe(p1.process_id); expect(s2.process_id).toBe(p2.process_id); expect(s1.attempt_id).toBe(a1.attempt_id); expect(s2.attempt_id).toBe(a2.attempt_id); expect(a1.process_id).toBe(p1.process_id); expect(a2.process_id).toBe(p2.process_id)
    const manifests = evidence.context_manifests; expect(manifests.find((m: any) => m.process_id === p1.process_id)).toBeTruthy(); expect(manifests.find((m: any) => m.process_id === p2.process_id)).toBeTruthy(); const results = evidence.process_results; const r1 = results.find((r: any) => r.process_id === p1.process_id); const r2 = results.find((r: any) => r.process_id === p2.process_id); const r3 = results.find((r: any) => r.process_id === p3.process_id); expect(r1.terminal_status).toBe('COMPLETED'); expect(r2.terminal_status).toBe('COMPLETED'); expect(r3.terminal_status).toBe('COMPLETED'); expect(JSON.parse(r3.outputs_json).status).toBe('ACTION_COMMITTED'); expect(s3.process_id).toBe(p3.process_id)
    const wire = h.requests.filter(r => r.path.includes('/chat/completions')); const cognitionWire = wire.filter(r => JSON.stringify(r.body).includes('안녕 Vesper') || JSON.stringify(r.body).includes('두 번째 Kernel execution test')); expect(cognitionWire).toHaveLength(2); expect(JSON.stringify(cognitionWire[0].body)).toContain('안녕 Vesper'); expect(JSON.stringify(cognitionWire[1].body)).toContain('두 번째 Kernel execution test'); expect(cognitionWire.every(r => JSON.stringify(r.body).includes('K0') || JSON.stringify(r.body).toLowerCase().includes('kernel'))).toBeTruthy(); const task = evidence.tasks.find((t: any) => t.title === 'Kernel browser conformance task'); expect(task).toBeTruthy(); expect(JSON.parse(r3.outputs_json).action.task_id).toBe(task.task_id); expect(evidence.tasks.filter((t: any) => t.title === 'Kernel browser conformance task')).toHaveLength(1)

  } finally { await h.close() }
})
