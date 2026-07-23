import React from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

function App() {
  return (
    <main>
      <p className="eyebrow">LOCAL-FIRST AI OPERATING SYSTEM</p>
      <h1>Vesper</h1>
      <p className="status">Runtime bootstrap is ready.</p>
      <p className="note">Canonical state belongs to the local Kernel, not the browser.</p>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
)

