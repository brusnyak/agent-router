import React, { useState } from 'react'

interface ProjectPickerProps {
  projects: any[]
  selectedProject: string | null
  onSelect: (project: string | null) => void
}

export function ProjectPicker({ projects, selectedProject, onSelect }: ProjectPickerProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="p-3 border-b border-[var(--border-subtle)]">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-2 bg-[var(--bg-card)] rounded hover:bg-[var(--border-active)] transition-colors"
      >
        <span className="text-[var(--fg-primary)] text-xs">
          {selectedProject ? `Project: {selectedProject}` : 'Global'}
        </span>
        <span className="text-[var(--fg-tertiary)] text-[10px]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="mt-1 space-y-1">
          <button
            onClick={() => { onSelect(null); setOpen(false) }}
            className={`w-full text-left px-3 py-2 rounded text-[10px] transition-colors ${!selectedProject ? 'bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]' : 'text-[var(--fg-secondary)] hover:bg-[var(--bg-card-hover)]'}`}
          >
            Global (Orca workspace)
          </button>
          {projects.map((p) => (
            <button
              key={p.id}
              onClick={() => { onSelect(p.id); setOpen(false) }}
              className={`w-full text-left px-3 py-2 rounded text-[10px] transition-colors ${selectedProject === p.id ? 'bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]' : 'text-[var(--fg-secondary)] hover:bg-[var(--bg-card-hover)]'}`}
            >
              {p.name || p.id}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
