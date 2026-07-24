import { expect, test } from '@playwright/test'
import { createServer, type Server } from 'node:http'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { spawn, type ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoDir = path.resolve(frontendDir, '..')
const python = path.join(repoDir, '.venv', 'bin', 'python')

type ManagedChild = { process: ChildProcess; output: () => string }

type Harness = {
  backend: ManagedChild
  frontend: ManagedChild
  home: string
  backendUrl: string
  frontendUrl: string
  close: () => Promise<void>
}

async function freePort(): Promise<number> {
  return await new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      server.close(error => error ? reject(error) : resolve((address as { port: number }).port))
    })
  })
}

async function waitFor(url: string): Promise<void> {
  const deadline = Date.now() + 15_000
  let lastError: unknown
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
      lastError = new Error(`${url}: ${response.status}`)
    } catch (error) { lastError = error }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`)
}

function child(command: string, args: string[], cwd: string, env: NodeJS.ProcessEnv): ManagedChild {
  const process = spawn(command, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
  let output = ''
  process.stdout?.on('data', chunk => { output += String(chunk) })
  process.stderr?.on('data', chunk => { output += String(chunk) })
  return { process, output: () => output }
}

async function stop(child: ManagedChild): Promise<void> {
  const process = child.process
  if (process.exitCode !== null || process.killed) return
  process.kill('SIGTERM')
  await Promise.race([
    new Promise<void>(resolve => process.once('exit', () => resolve())),
    new Promise<void>(resolve => setTimeout(resolve, 5_000)),
  ])
  if (process.exitCode === null) process.kill('SIGKILL')
}

async function startHarness(): Promise<Harness> {
  const home = await mkdtemp(path.join(tmpdir(), 'vesper-gate-f-'))
  const backendPort = await freePort()
  const frontendPort = await freePort()
  const backendEnv = { ...process.env, VESPER_HOME: home, PYTHONUNBUFFERED: '1' }
  // The fixture installs an ordinary, selector-specific DENY rule through SyscallEngine.grant.
  // The application still starts through the same Runtime/create_app and Kernel paths as production.
  const backendProgram = [
    'from pathlib import Path',
    'from vesper.api import Runtime, create_app',
    'from vesper.syscalls import Decision',
    'import uvicorn',
    `runtime = Runtime(Path(${JSON.stringify(home)}))`,
    'runtime.start()',
    "runtime.syscalls.grant(operation='test.effect', resource_selector='e2e-denied-target', decision=Decision.DENY, issuer='director', rule_id='e2e-canonical-deny')",
    "runtime.syscalls.grant(operation='test.effect', resource_selector='e2e-anchor-protected-target', decision=Decision.DENY, issuer='director', rule_id='e2e-anchor-authority-deny')",
    'app = create_app(runtime)',
    `uvicorn.run(app, host='127.0.0.1', port=${backendPort})`,
  ].join('\n')
  const backend = child(python, ['-c', backendProgram], repoDir, backendEnv)
  const frontendEnv = { ...backendEnv, VESPER_API_TARGET: `http://127.0.0.1:${backendPort}` }
  const frontend = child('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], frontendDir, frontendEnv)
  const backendUrl = `http://127.0.0.1:${backendPort}`
  const frontendUrl = `http://127.0.0.1:${frontendPort}`
  try {
    await Promise.all([waitFor(`${backendUrl}/health`), waitFor(frontendUrl)])
  } catch (error) {
    const diagnostic = `backend:\n${backend.output()}\nfrontend:\n${frontend.output()}`
    await stop(backend); await stop(frontend); await rm(home, { recursive: true, force: true })
    throw new Error(`${String(error)}\n${diagnostic}`)
  }
  return { backend, frontend, home, backendUrl, frontendUrl, close: async () => { await stop(frontend); await stop(backend); await rm(home, { recursive: true, force: true }) } }
}

async function bootstrap(baseUrl: string): Promise<string> {
  const response = await fetch(`${baseUrl}/api/bootstrap`)
  expect(response.ok).toBeTruthy()
  return (await response.json()).session
}

async function command(baseUrl: string, token: string, url: string, body: unknown): Promise<Response> {
  return fetch(`${baseUrl}${url}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': token, 'X-Client-Request-ID': crypto.randomUUID() }, body: JSON.stringify(body) })
}

async function createPendingApproval(baseUrl: string, token: string): Promise<{ approvalId: string; processId: string }> {
  // Gate C canonical default policy for a registered syscall is ASK; a Process cannot self-grant authority.
  const processResponse = await command(baseUrl, token, '/api/processes', { origin: 'e2e' })
  expect(processResponse.ok).toBeTruthy()
  const processId = (await processResponse.json()).process.process_id
  const response = await command(baseUrl, token, `/api/processes/${processId}/syscalls`, { operation: 'test.effect', target: 'e2e-approval-target', args: { value: 'requires-structured-approval' } })
  expect(response.status).toBe(200)
  const data = await response.json()
  expect(data.status).toBe('WAITING')
  expect(data.approval_id).toBeTruthy()
  return { approvalId: data.approval_id, processId }
}

async function assertDenyDoesNotBecomeApproval(baseUrl: string, token: string, target = 'e2e-denied-target', origin = 'e2e-deny'): Promise<void> {
  // `test.effect` is registered and exposed by the canonical runtime fixture. The specific
  // selector has an ordinary, selector-specific DENY rule, so Kernel/SyscallEngine resolves it to DENY.
  const deniedProcess = await command(baseUrl, token, '/api/processes', { origin })
  expect(deniedProcess.ok).toBeTruthy()
  const processId = (await deniedProcess.json()).process.process_id
  const beforeApprovals = await (await fetch(`${baseUrl}/api/approvals`)).json()
  const beforeEffects = await (await fetch(`${baseUrl}/api/effects`)).json()
  const response = await command(baseUrl, token, `/api/processes/${processId}/syscalls`, {
    operation: 'test.effect', target, args: { value: 'must-not-execute' },
  })
  expect(response.status).toBe(403)
  const data = await response.json()
  expect(data.detail.code).toBe('AUTHORITY_DENIED')
  const afterApprovals = await (await fetch(`${baseUrl}/api/approvals`)).json()
  expect(afterApprovals.approvals).toHaveLength(beforeApprovals.approvals.length)
  const process = await (await fetch(`${baseUrl}/api/processes/${processId}`)).json()
  expect(process.process.status).toBe('CREATED')
  const afterEffects = await (await fetch(`${baseUrl}/api/effects`)).json()
  const effectRows = (afterEffects.effects as Array<{ process_id: string }>).filter(effect => effect.process_id === processId)
  expect(effectRows).toHaveLength(0)
  expect((afterEffects.effects as unknown[]).length).toBe((beforeEffects.effects as unknown[]).length)
}

test.describe('Gate F.1 browser E2E closure', () => {
  let harness: Harness

  test.beforeEach(async () => { harness = await startHarness() })
  test.afterEach(async () => { if (harness) await harness.close() })

  test('full dogfood flow persists across browser close and proves security boundaries', async ({ browser }) => {
    const page = await browser.newPage()
    const calendarPatchBodies: unknown[] = []
    page.on('request', request => {
      if (request.method() === 'PATCH' && /\/api\/calendar\//.test(request.url())) calendarPatchBodies.push(request.postDataJSON())
    })
    await page.goto(harness.frontendUrl)
    await expect(page.getByText('VESPER')).toBeVisible()
    await expect(page).not.toHaveURL(/session|token|bootstrap/i)
    const html = await page.content()
    expect(html).not.toContain('secret://')

    await page.getByRole('button', { name: 'Projects' }).click()
    await page.getByPlaceholder('New project name').fill('Gate F Project')
    await page.getByRole('button', { name: '+ Create' }).click()
    await expect(page.getByText('Project committed')).toBeVisible()
    await expect(page.getByText('Gate F Project')).toBeVisible()

    await page.getByRole('button', { name: 'Tasks' }).click()
    await page.getByPlaceholder('Add a task').fill('Gate F Task')
    await page.getByRole('button', { name: '+ Create' }).click()
    await expect(page.getByText('Task committed')).toBeVisible()
    await expect(page.getByText('Gate F Task')).toBeVisible()

    await page.getByRole('button', { name: 'Calendar' }).click()
    await page.getByPlaceholder('Event title').fill('Gate F Calendar')
    const dates = page.locator('input[type="datetime-local"]')
    await dates.nth(0).fill('2026-07-24T10:00')
    await dates.nth(1).fill('2026-07-24T11:00')
    await page.getByRole('button', { name: '+ Add event' }).click()
    await expect(page.getByText('Calendar item committed')).toBeVisible()
    page.once('dialog', dialog => dialog.accept('2026-07-24T12:00'))
    await page.getByRole('button', { name: 'Move' }).click()
    await expect.poll(() => calendarPatchBodies.length).toBe(1)
    expect(calendarPatchBodies[0]).toEqual({ patch: { starts_at: '2026-07-24T12:00', ends_at: '2026-07-24T13:00' }, expected_revision: 1 })
    await expect(page.getByText('Calendar move committed; refreshed from Kernel')).toBeVisible()
    await expect(page.getByText(/2026-07-24T12:00.*2026-07-24T13:00/)).toBeVisible()

    await page.getByRole('button', { name: 'Ideas' }).click()
    await page.getByPlaceholder('What are you noticing?').fill('Provider down must still persist')
    await page.getByRole('button', { name: 'Capture idea' }).click()
    await expect(page.getByText('Idea persisted')).toBeVisible()
    await expect(page.getByText('Provider down must still persist')).toBeVisible()

    await page.getByRole('button', { name: 'Processes' }).click()
    await expect(page.getByText('No durable processes yet.')).toBeVisible()

    const token = await bootstrap(harness.backendUrl)
    const { approvalId, processId } = await createPendingApproval(harness.backendUrl, token)
    await page.getByRole('button', { name: 'Approvals' }).click()
    await page.getByRole('button', { name: 'Refresh' }).click()
    await expect(page.getByText('test.effect')).toBeVisible()
    await page.getByRole('button', { name: 'Approve' }).click()
    await expect(page.getByText('Approval approve committed')).toBeVisible()
    const approvalResponse = await fetch(`${harness.backendUrl}/api/approvals`)
    expect((await approvalResponse.json()).approvals.find((item: { approval_id: string }) => item.approval_id === approvalId).decision).toBe('APPROVED')
    // A created Process has no RUNNING wait row; submit it through the normal lifecycle before its syscall.
    const processBeforeResume = await (await fetch(`${harness.backendUrl}/api/processes/${processId}`)).json()
    expect(processBeforeResume.process.status).toBe('WAITING')
    const transition = await command(harness.backendUrl, token, `/api/processes/${processId}/transition`, { status: 'RUNNING', expected_revision: processBeforeResume.process.revision })
    expect(transition.status).toBe(200)
    const resumed = await command(harness.backendUrl, token, `/api/processes/${processId}/syscalls`, { operation: 'test.effect', target: 'e2e-approval-target', args: { value: 'requires-structured-approval' }, approval_id: approvalId })
    expect(resumed.status).toBe(200)
    const committed = await resumed.json()
    expect(committed.status).toBe('COMMITTED')
    expect(committed.effect_id).toBeTruthy()
    const committedEffects = await (await fetch(`${harness.backendUrl}/api/effects`)).json()
    expect(committedEffects.effects.filter((effect: { effect_id: string; status: string }) => effect.effect_id === committed.effect_id)).toEqual([expect.objectContaining({ status: 'COMMITTED' })])
    await assertDenyDoesNotBecomeApproval(harness.backendUrl, token)

    await page.getByRole('button', { name: 'Connections' }).click()
    await expect(page.getByText('Credentials are never displayed here.')).toBeVisible()
    expect(await page.content()).not.toContain('credential_ref')

    await page.getByRole('button', { name: 'Settings' }).click()
    await page.getByLabel('Director display name').fill('Dogfood Director')
    await page.getByLabel('Developer diagnostics').check()
    await page.getByRole('button', { name: 'Save settings' }).click()
    await expect(page.getByText('Settings committed')).toBeVisible()

    await page.getByRole('button', { name: 'Calendar' }).click()
    await page.getByRole('button', { name: 'Undo' }).click()
    await expect(page.getByText('Compensating undo committed')).toBeVisible()
    const calendar = await (await fetch(`${harness.backendUrl}/api/calendar`)).json()
    expect(calendar.calendar[0].starts_at).toBe('2026-07-24T10:00')
    expect(calendar.calendar[0].revision).toBe(3)

    const anchorTarget = 'e2e-anchor-protected-target'
    // A: authenticated request with no anchor is DENY, without approval/effect/WAITING.
    await assertDenyDoesNotBecomeApproval(harness.backendUrl, token, anchorTarget, 'anchor-absent')
    // B: the same authenticated session creates an interaction anchor, then receives the same DENY.
    const anchorResponse = await command(harness.backendUrl, token, '/api/anchors', { anchor_type: 'resource', resource_ref: { resource_type: 'project', resource_id: anchorTarget }, selection_refs: [{ resource_type: 'task', resource_id: 'anchor-selection-reference' }], view_scope_ref: 'projects' })
    expect(anchorResponse.ok).toBeTruthy()
    const anchor = (await anchorResponse.json()).anchor
    expect(anchor.authority).toEqual([])
    expect(anchor.resource_ref.resource_id).toBe(anchorTarget)
    expect(anchor.selection_refs).toEqual([{ resource_type: 'task', resource_id: 'anchor-selection-reference' }])
    await assertDenyDoesNotBecomeApproval(harness.backendUrl, token, anchorTarget, 'anchor-present')

    const invalidSession = await fetch(`${harness.backendUrl}/api/projects`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Vesper-Bootstrap': 'invalid' }, body: JSON.stringify({ name: 'blocked' }) })
    expect(invalidSession.status).toBe(401)

    await page.close()
    await expect.poll(async () => (await fetch(`${harness.backendUrl}/health`)).status).toBe(200)

    const reopened = await browser.newPage()
    await reopened.goto(harness.frontendUrl)
    await reopened.getByRole('button', { name: 'Projects' }).click()
    await expect(reopened.getByText('Gate F Project')).toBeVisible()
    await reopened.getByRole('button', { name: 'Tasks' }).click()
    await expect(reopened.getByText('Gate F Task')).toBeVisible()
    await reopened.getByRole('button', { name: 'Calendar' }).click()
    await expect(reopened.getByText(/2026-07-24T10:00.*2026-07-24T11:00/)).toBeVisible()
    await reopened.getByRole('button', { name: 'Ideas' }).click()
    await expect(reopened.getByText('Provider down must still persist')).toBeVisible()
    await reopened.getByRole('button', { name: 'Settings' }).click()
    await expect(reopened.getByLabel('Director display name')).toHaveValue('Dogfood Director')
    await expect(reopened.getByLabel('Developer diagnostics')).toBeChecked()
  })
})
