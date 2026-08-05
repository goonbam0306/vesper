import React from 'react'

export function CalmAuroraEdge({ active, preview = false }: { active: boolean; preview?: boolean }) {
  return <div
    aria-hidden="true"
    className={`calm-aurora-edge ${active ? 'is-active' : 'is-inactive'}`}
    data-testid="aurora-layer"
    data-aurora-mode={preview ? 'presentation' : 'inactive'}
    data-aurora-opacity="50"
    data-aurora-active={String(active)}
  />
}
