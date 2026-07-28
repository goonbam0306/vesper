import { expect, test } from '@playwright/test'
import { startHarness, bootstrap, command } from './support/vesper-harness'

test.describe('Dogfood Product Closure 4.1 focused UX contract', () => {
  let harness: Awaited<ReturnType<typeof startHarness>>

  test.beforeEach(async () => { harness = await startHarness() })
  test.afterEach(async () => { await harness.close() })

  test('Home hierarchy exposes operational surfaces and inline task count', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    await expect(page.getByRole('heading', { name: 'Tasks' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Today / Calendar' })).toBeVisible()
    await expect(page.getByText(/\d+ open/).first()).toBeVisible()
    await expect(page.getByText('Open Tasks', { exact: true })).toHaveCount(0)
    await expect(page.getByLabel('Ask Vesper')).toBeVisible()
    await expect(page.locator('.hero h1')).toBeVisible()
  })

  test('Calendar form opens with real state defaults and preserves duration when Start changes', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    await page.getByRole('button', { name: 'Calendar' }).click()
    const date = page.getByLabel('Date')
    const start = page.getByLabel('Start time')
    const end = page.getByLabel('End time')
    await expect(date).not.toHaveValue('')
    await expect(start).not.toHaveValue('')
    await expect(end).not.toHaveValue('')
    const before = { start: await start.inputValue(), end: await end.inputValue() }
    const duration = (value: string) => { const [h, m] = value.split(':').map(Number); return h * 60 + m }
    expect(duration(before.end) - duration(before.start)).toBe(60)
    await page.getByPlaceholder('Event title').fill('Closure default event')
    await start.fill('16:30')
    expect(duration(await end.inputValue()) - duration(await start.inputValue())).toBe(60)
    await page.getByRole('button', { name: '+ Add event' }).click()
    await expect(page.getByText('Calendar item committed')).toBeVisible()
    await expect(page.getByText(/2026|20\d\d-/).last()).toBeVisible()
  })

  test('Calendar preserves manually edited End when Start changes', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    await page.getByRole('button', { name: 'Calendar' }).click()
    const start = page.getByLabel('Start time')
    const end = page.getByLabel('End time')
    const startValue = await start.inputValue()
    const [hours, minutes] = startValue.split(':').map(Number)
    const editedStart = `${String((hours + 2) % 24).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
    const editedEnd = `${String((hours + 3) % 24).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
    await end.fill(editedEnd)
    await start.fill(editedStart)
    expect(await end.inputValue()).toBe(editedEnd)
    const [endHours, endMinutes] = (await end.inputValue()).split(':').map(Number)
    expect(endHours * 60 + endMinutes).not.toBe(hours * 60 + minutes)
  })

  test('Calendar default values submit and persist without editing time fields', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    await page.getByRole('button', { name: 'Calendar' }).click()
    const date = page.getByLabel('Date')
    const start = page.getByLabel('Start time')
    const end = page.getByLabel('End time')
    const submitted = { date: await date.inputValue(), start: await start.inputValue(), end: await end.inputValue() }
    await page.getByPlaceholder('Event title').fill('Closure default calendar')
    await page.getByRole('button', { name: '+ Add event' }).click()
    await expect(page.getByText('Calendar item committed')).toBeVisible()
    const calendar = await (await fetch(`${harness.backendUrl}/api/calendar`)).json()
    const item = calendar.calendar.find((entry: { title: string }) => entry.title === 'Closure default calendar')
    expect(item).toBeTruthy()
    expect(item.starts_at).toBe(`${submitted.date}T${submitted.start}`)
    expect(item.ends_at).toBe(`${submitted.date}T${submitted.end}`)
    await expect(page.getByText(/Closure default calendar/)).toBeVisible()
  })

  test('Ask Vesper transcript remains bounded and vertically scrollable over ten turns', async ({ page }) => {
    const messages: Array<{ message_id: string; role: string; content: string }> = []
    await page.route('**/api/model/invoke', async route => {
      const body = route.request().postDataJSON() as { prompt: string; conversation_id?: string }
      const conversationId = body.conversation_id || 'e2e-conversation'
      const user = { message_id: `user-${messages.length}`, role: 'USER', content: body.prompt }
      const assistant = { message_id: `assistant-${messages.length}`, role: 'ASSISTANT', content: `response ${body.prompt}` }
      messages.push(user, assistant)
      await route.fulfill({ json: { conversation_id: conversationId, user_message: user, assistant_message: assistant } })
    })
    await page.route('**/api/conversations/*', async route => { await route.fulfill({ json: { messages } }) })
    await page.goto(harness.frontendUrl)
    const ask = page.getByLabel('Ask Vesper')
    for (let index = 0; index < 11; index += 1) {
      await ask.fill(`turn ${index}`)
      await page.getByRole('button', { name: 'Send' }).click()
      await expect(page.locator('.ask-turn').filter({ hasText: `turn ${index}` }).first()).toBeAttached()
    }
    const transcript = page.locator('.ask-transcript')
    const metrics = await transcript.evaluate(element => ({
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
    }))
    expect(metrics.scrollHeight).toBeGreaterThan(metrics.clientHeight)
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth)
    await transcript.evaluate(element => { element.scrollTop = 0 })
    await expect(page.locator('.ask-turn').filter({ hasText: 'turn 0' }).first()).toBeAttached()
    await expect(ask).toBeVisible()
  })

  test('Create Task action commits, projects, reloads, and exposes the same task id', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    const ask = page.getByLabel('Ask Vesper')
    await ask.fill('할 일로 Vesper 업그레이드 하기 추가해줘')
    await ask.press('Enter')
    await expect(page.getByText('Task에 추가했습니다: Vesper 업그레이드 하기')).toBeVisible()
    await page.getByRole('button', { name: 'Tasks' }).click()
    await page.getByRole('button', { name: 'Refresh' }).click()
    await expect(page.getByText('Vesper 업그레이드 하기', { exact: true })).toBeVisible()
    const token = await bootstrap(harness.backendUrl)
    const tasksResponse = await fetch(`${harness.backendUrl}/api/tasks`)
    expect(tasksResponse.ok).toBeTruthy()
    const tasks = (await tasksResponse.json()).tasks
    const task = tasks.find((item: { title: string }) => item.title === 'Vesper 업그레이드 하기')
    expect(task).toEqual(expect.objectContaining({ title: 'Vesper 업그레이드 하기', task_id: expect.any(String) }))
    await page.reload()
    await page.getByRole('button', { name: 'Tasks' }).click()
    await expect(page.getByText('Vesper 업그레이드 하기', { exact: true })).toBeVisible()
    expect(token).toEqual(expect.any(String))
  })

  test('Create Task failure never presents false completion and exposes FAILED receipt', async ({ page }) => {
    const failedMessages = [{ message_id: 'failed-user', role: 'USER', content: '할 일로 강제 실패 작업 추가해줘' }, { message_id: 'failed-assistant', role: 'ASSISTANT', content: 'Task에 추가하지 못했습니다. 실제 저장에 실패했습니다.' }]
    const failureReceipt = { entity_type: 'task', supported_chat_action: 'CREATE_TASK', commit_status: 'FAILED', error_code: 'E2E_FORCED_FAILURE' }
    await page.route('**/api/conversations/*', async route => { await route.fulfill({ json: { messages: failedMessages } }) })
    await page.route('**/api/model/invoke', async route => {
      const body = route.request().postDataJSON() as { conversation_id?: string }
      const user = { message_id: 'failed-user', role: 'USER', content: '할 일로 강제 실패 작업 추가해줘' }
      const assistant = { message_id: 'failed-assistant', role: 'ASSISTANT', content: 'Task에 추가하지 못했습니다. 실제 저장에 실패했습니다.' }
      await route.fulfill({ json: { output: assistant.content, status: 'ACTION_FAILED', conversation_id: body.conversation_id || 'failed-conversation', user_message: user, assistant_message: assistant, action: failureReceipt } })
    })
    await page.goto(harness.frontendUrl)
    await page.getByLabel('Ask Vesper').fill('할 일로 강제 실패 작업 추가해줘')
    await page.getByLabel('Ask Vesper').press('Enter')
    await expect(page.getByText('Task에 추가하지 못했습니다. 실제 저장에 실패했습니다.')).toBeVisible()
    await expect(page.getByText(/Task에 추가했습니다/)).toHaveCount(0)
    await page.getByRole('button', { name: 'Tasks' }).click()
    await expect(page.getByText('강제 실패 작업', { exact: true })).toHaveCount(0)
  })

  test('Project click enters detail with canonical task and calendar projections', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    const token = await bootstrap(harness.backendUrl)
    const projectResponse = await command(harness.backendUrl, token, '/api/projects', { name: 'Closure Project', objective: 'Closure objective' })
    expect(projectResponse.ok).toBeTruthy()
    const project = (await projectResponse.json()).project
    const taskResponse = await command(harness.backendUrl, token, '/api/tasks', { title: 'Related closure task', project_id: project.project_id })
    expect(taskResponse.ok).toBeTruthy()
    await page.reload()
    await page.getByRole('button', { name: 'Projects' }).click()
    await page.getByRole('button', { name: /Closure Project/ }).click()
    await expect(page.getByRole('heading', { name: 'Projects' })).toBeVisible()
    await expect(page.getByText('Closure Project')).toBeVisible()
    await expect(page.getByText('Closure objective')).toBeVisible()
    await expect(page.getByText('Related closure task')).toBeVisible()
    await expect(page.getByText('Calendar / Milestones')).toBeVisible()
  })

  test('Observability and Memory surfaces expose inspectable local state', async ({ page }) => {
    await page.goto(harness.frontendUrl)
    await page.getByRole('button', { name: 'Observability' }).click()
    await expect(page.getByRole('heading', { name: 'Observability' })).toBeVisible()
    await expect(page.getByText('Runtime counters')).toBeVisible()
    await expect(page.getByText('Verification')).toBeVisible()
    await page.getByRole('button', { name: 'Memory' }).click()
    await expect(page.getByRole('heading', { name: 'Memory' })).toBeVisible()
    await expect(page.getByText('Inspectable latest memory state.')).toBeVisible()
    await expect(page.getByText('No memories recorded.')).toBeVisible()
    const memoryCards = (await page.locator('.resource-card').allInnerTexts()).join(' ').toLowerCase()
    expect(memoryCards).not.toContain('credential')
    expect(memoryCards).not.toContain('secret')
  })
})
