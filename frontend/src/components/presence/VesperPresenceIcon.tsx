import type { SVGProps } from 'react'
import { presenceLabel, type VesperPresenceSize, type VesperPresenceState } from './presence-state'

export interface VesperPresenceIconProps {
  state: VesperPresenceState
  size?: VesperPresenceSize
  label?: string
  decorative?: boolean
  className?: string
  testId?: string
}

export function VesperPresenceIcon({ state, size = 24, label, decorative = false, className = '', testId }: VesperPresenceIconProps) {
  const semantics: SVGProps<SVGSVGElement> = decorative
    ? { 'aria-hidden': true }
    : { role: 'img', 'aria-label': presenceLabel(state, label) }
  return <svg
    {...semantics}
    data-testid={testId}
    data-presence-state={state}
    className={`vesper-presence-icon size-${size} is-${state} ${className}`.trim()}
    width={size}
    height={size}
    viewBox="0 0 64 64"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path data-segment="A" d="M10 16 L24 26" />
    <path data-segment="B" d="M54 15 L40 26" />
    <path data-segment="C" d="M11 49 L25 39" />
    <path data-segment="D" d="M53 50 L39 39" />
    <path data-actor="top-trace" className="presence-trace top-trace" d="M27 20 L37 20" />
    <path data-actor="bottom-trace" className="presence-trace bottom-trace" d="M27 44 L37 44" />
    <circle data-actor="core-bloom" className="presence-core" cx="32" cy="32" r="3" />
    <g className="presence-input-packets">{[0, 1, 2].map(index => <circle data-actor="input-packet" key={index} cx={13 + index * 5} cy={32} r="1.5" />)}</g>
    <g className="presence-output-packets">{[0, 1, 2].map(index => <circle data-actor="output-packet" key={index} cx={51 - index * 5} cy={32} r="1.5" />)}</g>
    <circle data-actor="jam-point" className="presence-jam" cx="32" cy="32" r="2.5" />
    <path data-actor="jam-seal" className="presence-seal" d="M26 26 L38 38 M38 26 L26 38" />
  </svg>
}