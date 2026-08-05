export type VesperPresenceState = 'idle' | 'thinking' | 'retrieving' | 'writing' | 'waiting' | 'blocked'
export type VesperPresenceSize = 16 | 24 | 32 | 48

const labels: Record<VesperPresenceState, string> = {
  idle: 'Vesper idle',
  thinking: 'Vesper thinking',
  retrieving: 'Vesper retrieving context',
  writing: 'Vesper composing output',
  waiting: 'Vesper waiting',
  blocked: 'Vesper blocked',
}

export const presenceLabel = (state: VesperPresenceState, label?: string) => label || labels[state]

export const askPresenceState = (state: 'idle' | 'sending' | 'response' | 'failure'): VesperPresenceState => {
  if (state === 'sending') return 'thinking'
  if (state === 'failure') return 'blocked'
  return 'idle'
}

export const processPresenceState = (status: string): VesperPresenceState => {
  if (status === 'RUNNING') return 'thinking'
  if (status === 'WAITING' || status === 'PAUSED') return 'waiting'
  if (status === 'FAILED') return 'blocked'
  return 'idle'
}