import { spawn } from 'node:child_process'
import path from 'node:path'

const repoDir = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../..')
const python = path.join(repoDir, '.venv', 'bin', 'python')

/** Read only the isolated runtime SQLite database. No production endpoint is used. */
export async function readRuntimeEvidence(dbPath: string): Promise<Record<string, any[]>> {
  const code = `import json, sqlite3, sys
p=sys.argv[1]
c=sqlite3.connect('file:'+p+'?mode=ro', uri=True)
c.row_factory=sqlite3.Row

def read_table(name):
    try:
        return [dict(row) for row in c.execute('select * from '+name).fetchall()]
    except sqlite3.Error as exc:
        return [{'_table_error': str(exc)}]

names = ['conversations', 'conversation_messages', 'processes', 'process_results', 'cognitive_attempts', 'context_manifests', 'event_journal', 'tasks']
print(json.dumps({name: read_table(name) for name in names}, default=str))`

  return await new Promise((resolve, reject) => {
    const child = spawn(python, ['-c', code, dbPath], {
      cwd: repoDir,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', chunk => { stdout += String(chunk) })
    child.stderr.on('data', chunk => { stderr += String(chunk) })
    child.once('error', reject)
    child.once('exit', exitCode => {
      if (exitCode !== 0) reject(new Error(stderr || `evidence helper exited ${exitCode}`))
      else {
        try { resolve(JSON.parse(stdout)) }
        catch (error) { reject(new Error(`invalid evidence JSON: ${String(error)}`)) }
      }
    })
  })
}

export function secretFreeProviderEvidence(requests: Array<{ path: string; model?: string; authorization?: string; body?: any }>) {
  return requests.map(({ path: requestPath, model, authorization, body }) => ({
    path: requestPath,
    model,
    hasAuthorization: Boolean(authorization),
    hasSystem: Array.isArray(body?.messages) && body.messages.some((message: any) => message.role === 'system'),
    hasUser: Array.isArray(body?.messages) && body.messages.some((message: any) => message.role === 'user'),
  }))
}

export function assertNoTableErrors(evidence: Record<string, any[]>) {
  for (const [table, rows] of Object.entries(evidence)) {
    if (rows.some(row => row._table_error)) throw new Error(`Missing or invalid evidence table ${table}: ${rows[0]._table_error}`)
  }
}

export function processIds(evidence: Record<string, any[]>) {
  return evidence.processes.filter(process => process.status === 'COMPLETED').map(process => process.process_id)
}

export function provenanceForProcess(evidence: Record<string, any[]>, processId: string) {
  return {
    messages: evidence.conversation_messages.filter(message => message.process_id === processId),
    attempts: evidence.cognitive_attempts.filter(attempt => attempt.process_id === processId),
    results: evidence.process_results.filter(result => result.process_id === processId),
    manifests: evidence.context_manifests.filter(manifest => manifest.process_id === processId),
  }
}

export function isSecretFreeProviderRequest(request: ReturnType<typeof secretFreeProviderEvidence>[number]) {
  return Boolean(request.model && request.hasAuthorization && request.hasSystem && request.hasUser)
}

export function providerCognitionRequests(requests: ReturnType<typeof secretFreeProviderEvidence>) {
  return requests.filter(request => request.path.includes('/chat/completions') && isSecretFreeProviderRequest(request))
}

export function summarizeRuntimeEvidence(evidence: Record<string, any[]>) {
  return {
    conversations: evidence.conversations.length,
    messages: evidence.conversation_messages.length,
    processes: evidence.processes.length,
    results: evidence.process_results.length,
    attempts: evidence.cognitive_attempts.length,
    manifests: evidence.context_manifests.length,
    events: evidence.event_journal.length,
    tasks: evidence.tasks.length,
  }
}

export type RuntimeEvidence = Awaited<ReturnType<typeof readRuntimeEvidence>>