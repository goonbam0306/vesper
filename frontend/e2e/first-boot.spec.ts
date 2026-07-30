import { expect, test } from '@playwright/test'
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
type Harness = { home: string; secretRoot: string; fake: Server; fakePort: number; backendPort: number; frontendPort: number; requests: Array<{ path: string; model?: string; authorization?: string }>; backend: Child; frontend: Child; frontendUrl: string; restart: () => Promise<void>; close: () => Promise<void> }

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
async function fakeProvider(): Promise<{ server: Server; port: number; requests: Array<{ path: string; model?: string; authorization?: string }> }> {
  const requests: Array<{ path: string; model?: string; authorization?: string }> = []
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const chunks: Buffer[] = []; req.on('data', c => chunks.push(Buffer.from(c))); req.on('end', () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {}
      requests.push({ path: req.url || '', model: body.model, authorization: req.headers.authorization })
      if (req.headers.authorization?.includes('WRONG_CREDENTIAL')) { const text = JSON.stringify({ error: { message: 'authentication failed' } }); res.writeHead(401, { 'content-type': 'application/json' }); res.end(text); return }
      if (body.model === 'missing-model') { const text = JSON.stringify({ error: { message: 'model unavailable' } }); res.writeHead(404, { 'content-type': 'application/json' }); res.end(text); return }
      const payload = req.url?.endsWith('/models') ? { data: [{ id: 'vesper-test-model' }] } : { choices: [{ message: { content: 'VESPER_READY' } }] }
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
  return { home, secretRoot, fake: fake.server, fakePort: fake.port, backendPort: bp, frontendPort: fp, requests: fake.requests, get backend() { return backend }, get frontend() { return frontend }, frontendUrl, restart, close: async () => { await stop(frontend); await stop(backend); await new Promise<void>(r => fake.server.close(() => r())); await rm(home, { recursive: true, force: true }); await rm(secretRoot, { recursive: true, force: true }) } }
}

test('fresh VESPER_HOME completes optional AI First Boot and persists reload', async ({ page }) => {
  const h = await start()
  try {
    await page.goto(h.frontendUrl)
    await expect(page.getByRole('heading', { name: 'Welcome to Vesper' })).toBeVisible()
    await expect(page.getByText('Good work starts here.')).toHaveCount(0)
    await page.getByRole('button', { name: 'Set up Vesper' }).click()
    await page.getByRole('button', { name: 'Set up later' }).click()
    await page.getByLabel('Director display name').fill('Dogfood Director')
    await page.getByRole('button', { name: 'Finish' }).click()
    await expect(page.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Welcome to Vesper' })).toHaveCount(0)
  } finally { await h.close() }
})

test('configured First Boot performs real provider validation and normal runtime inference', async ({ page }) => {
  const h = await start()
  const credential = `VESPER_E2E_SECRET_${crypto.randomUUID()}`
  const consoleLines: string[] = []
  page.on('console', message => consoleLines.push(message.text()))
  try {
    await page.goto(h.frontendUrl)
    await page.getByRole('button', { name: 'Set up Vesper' }).click()
    await page.getByRole('button', { name: 'Local endpoint' }).click()
    await page.getByLabel('Endpoint URL').fill(`http://127.0.0.1:${h.fakePort}/v1`)
    await page.getByLabel('API key (optional)').fill(credential)
    await page.getByLabel('Model ID (optional)').fill('vesper-test-model')
    await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByRole('heading', { name: 'Choose a default model' })).toBeVisible()
    await page.getByLabel('Default model').fill('vesper-test-model')
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByLabel('Director display name').fill('Configured Director')
    await page.getByRole('button', { name: 'Finish' }).click()
    await expect(page.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
    const ask = page.getByLabel('Ask Vesper')
    await ask.fill('browser surface inference')
    await ask.press('Enter')
    await expect(page.getByRole('status')).toHaveText('VESPER_READY')
    expect(h.requests.length).toBe(2)
    await ask.fill('line one')
    await ask.press('Shift+Enter')
    await ask.type('line two')
    await expect(ask).toHaveValue('line one\nline two')
    await page.getByRole('button', { name: 'Send' }).click()
    await expect(page.getByRole('status')).toHaveText('VESPER_READY')
    expect(h.requests.length).toBeGreaterThanOrEqual(2)
    const result = await page.evaluate(async () => {
      const bootstrap = await fetch('/api/bootstrap').then(r => r.json())
      return fetch('/api/model/invoke', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': bootstrap.session }, body: JSON.stringify({ prompt: 'browser normal inference' }) }).then(r => r.json())
    })
    expect(result.output).toBe('VESPER_READY')
    expect(h.requests.length).toBe(4)
    expect(h.requests.every(request => request.model === 'vesper-test-model')).toBeTruthy()
    expect(h.requests.every(request => request.authorization === `Bearer ${credential}`)).toBeTruthy()
    await page.getByRole('button', { name: 'Connections' }).click()
    const connectionsText = await page.locator('body').innerText()
    expect(connectionsText).not.toContain(credential)
    const browserState = await page.evaluate(() => ({ html: document.documentElement.outerHTML, local: JSON.stringify(localStorage), session: JSON.stringify(sessionStorage), url: location.href }))
    expect(JSON.stringify(browserState)).not.toContain(credential)
    expect(consoleLines.join('\\n')).not.toContain(credential)
    const scan = async (dir: string): Promise<number> => { let hits = 0; for (const name of await readdir(dir, { withFileTypes: true })) { const file = path.join(dir, name.name); if (name.isDirectory()) hits += await scan(file); else { try { if ((await readFile(file)).includes(Buffer.from(credential))) hits++ } catch {} } } return hits }
    const fileHits = await scan(h.home)
    const backendHits = h.backend.output().includes(credential) ? 1 : 0
    console.log(`ACTUAL_CREDENTIAL_PLAINTEXT_OCCURRENCES = ${fileHits + backendHits}`)
    expect(fileHits + backendHits).toBe(0)
    expect(h.backend.output()).not.toContain(credential)
  } finally { await h.close() }
})

test('configured First Boot survives backend restart and invokes through reconstructed route', async ({ page }) => {
  const h = await start()
  const credential = `VESPER_E2E_SECRET_${crypto.randomUUID()}`
  try {
    await page.goto(h.frontendUrl)
    await page.getByRole('button', { name: 'Set up Vesper' }).click()
    await page.getByRole('button', { name: 'Local endpoint' }).click()
    await page.getByLabel('Endpoint URL').fill(`http://127.0.0.1:${h.fakePort}/v1`)
    await page.getByLabel('API key (optional)').fill(credential)
    await page.getByLabel('Model ID (optional)').fill('vesper-test-model')
    await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByRole('heading', { name: 'Choose a default model' })).toBeVisible()
    await page.getByLabel('Default model').fill('vesper-test-model')
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByLabel('Director display name').fill('Restart Director')
    await page.getByRole('button', { name: 'Finish' }).click()
    await expect(page.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
    const bootstrap = await page.evaluate(() => fetch('/api/bootstrap').then(r => r.json()))
    const first = await page.evaluate(async (session) => fetch('/api/model/invoke', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': session }, body: JSON.stringify({ prompt: 'before restart' }) }).then(r => r.json()), bootstrap.session)
    expect(first.output).toBe('VESPER_READY')
    await page.close()
    await h.restart()
    const reopened = await page.context().newPage()
    await reopened.goto(h.frontendUrl)
    await expect(reopened.getByRole('heading', { name: 'Good work starts here.' })).toBeVisible()
    await expect(reopened.getByRole('heading', { name: 'Welcome to Vesper' })).toHaveCount(0)
    await reopened.getByRole('button', { name: 'Settings' }).click()
    await expect(reopened.getByLabel('Director display name')).toHaveValue('Restart Director')
    const after = await reopened.evaluate(async () => { const b = await fetch('/api/bootstrap').then(r => r.json()); return fetch('/api/model/invoke', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': b.session }, body: JSON.stringify({ prompt: 'after restart' }) }).then(r => r.json()) })
    expect(after.output).toBe('VESPER_READY')
    expect(h.requests.length).toBe(3)
    await reopened.close()
  } finally { await h.close() }
})

test('wrong credential stays on connection step without secret or stack trace', async ({ page }) => {
  const h = await start()
  try {
    await page.goto(h.frontendUrl); await page.getByRole('button', { name: 'Set up Vesper' }).click(); await page.getByRole('button', { name: 'Local endpoint' }).click()
    await page.getByLabel('Endpoint URL').fill(`http://127.0.0.1:${h.fakePort}/v1`); await page.getByLabel('API key (optional)').fill('WRONG_CREDENTIAL'); await page.getByLabel('Model ID (optional)').fill('vesper-test-model'); await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByRole('heading', { name: 'Connect an AI provider' })).toBeVisible(); const text = await page.locator('.setup-error').innerText(); expect(text.toLowerCase()).toMatch(/auth|401|credential|provider/); expect(text).not.toContain('Traceback'); expect(text).not.toContain('authentication failed')
    await page.getByLabel('API key (optional)').fill('VESPER_E2E_SECRET_GOOD'); await page.getByRole('button', { name: 'Test connection' }).click(); await expect(page.getByRole('heading', { name: 'Choose a default model' })).toBeVisible()
  } finally { await h.close() }
})

test('wrong model stays out of MODEL_READY and can be corrected', async ({ page }) => {
  const h = await start()
  try {
    await page.goto(h.frontendUrl); await page.getByRole('button', { name: 'Set up Vesper' }).click(); await page.getByRole('button', { name: 'Local endpoint' }).click()
    await page.getByLabel('Endpoint URL').fill(`http://127.0.0.1:${h.fakePort}/v1`); await page.getByLabel('API key (optional)').fill('VESPER_E2E_SECRET_GOOD'); await page.getByLabel('Model ID (optional)').fill('missing-model'); await page.getByRole('button', { name: 'Test connection' }).click()
    await expect(page.getByRole('heading', { name: 'Connect an AI provider' })).toBeVisible(); const text = await page.locator('.setup-error').innerText(); expect(text.toLowerCase()).toMatch(/model|404|unavailable|provider/); expect(text).not.toContain('Traceback')
    await page.getByLabel('Model ID (optional)').fill('vesper-test-model'); await page.getByRole('button', { name: 'Test connection' }).click(); await expect(page.getByRole('heading', { name: 'Choose a default model' })).toBeVisible()
  } finally { await h.close() }
})
