import React, { useState } from 'react'

interface ProjectPickerProps {
  projects: any[]
  selectedProject: string | null
  onSelect: (project: string | null) => void
}

export function ProjectPicker({ projects, selectedProject, onSelect }: ProjectPickerProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="p-3 border-b border-border">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-2 bg-[#212530] rounded hover:bg-[#2A2E3A] transition-colors"
      >
        <span className="text-text text-sm">
          {selectedProject ? `Project: {selectedProject}` : 'Select Project'}
        </span>
        <span className="text-textSecondary text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="mt-1 space-y-1">
          <button
            onClick={() => { onSelect(null); setOpen(false) }}
            className={`w-full text-left px-3 py-2 rounded text-xs transition-colors ${!selectedProject ? 'bg-primary/10 text-primary' : 'text-textSecondary hover:bg-[#303030]'}`}
          >
            Global (Orca workspace)
          </button>
          {projects.map((p) => (
            <button
              key={p.id}
              onClick={() => { onSelect(p.id); setOpen(false) }}
              className={`w-full text-left px-3 py-2 rounded text-xs transition-colors ${selectedProject === p.id ? 'bg-primary/10 text-primary' : 'text-textSecondary hover:bg-[#303030]'}`}
            >
              {p.name || p.id}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
