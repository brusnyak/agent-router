import React from 'react'
import { LayoutDashboard, List, Settings, BarChart3, Terminal, GitBranch } from 'lucide-react'

interface LeftNavProps {
  activeSection: string
  onSectionChange: (section: string) => void
  projects: any[]
  selectedProject: string | null
  onProjectChange: (project: string | null) => void
}

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'kanban', label: 'Kanban', icon: List },
  { id: 'agents', label: 'Agents', icon: Terminal },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export function LeftNav({ activeSection, onSectionChange, projects, selectedProject, onProjectChange }: LeftNavProps) {
  return (
    <div className="flex flex-col h-full border-r border-[var(--border-subtle)] bg-[var(--bg-sidebar)]">
      {/* Header */}
      <div className="p-4 border-b border-[var(--border-subtle)]">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-[var(--accent-primary)]"></div>
          <span className="font-bold text-[var(--fg-primary)] text-sm tracking-tight">Agent Router</span>
        </div>
        <div className="mt-2 text-[var(--fg-tertiary)] text-xs">LangGraph · NIM 3</div>
      </div>

      {/* Projects */}
      <div className="p-3 border-b border-[var(--border-subtle)]">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[var(--fg-tertiary)] text-xs uppercase tracking-wider font-semibold">Projects</span>
        </div>
        <div className="space-y-1">
          <button
            onClick={() => { onProjectChange(null); onSectionChange('dashboard') }}
            className={`w-full text-left px-3 py-2 rounded-md text-xs transition-colors ${!selectedProject ? 'bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]' : 'text-[var(--fg-secondary)] hover:bg-[var(--bg-card-hover)]'}`}
          >
            Global (Orca workspace)
          </button>
          {projects.map((p) => (
            <button
              key={p.id}
              onClick={() => { onProjectChange(p.id); onSectionChange('dashboard') }}
              className={`w-full text-left px-3 py-2 rounded-md text-xs transition-colors ${selectedProject === p.id ? 'bg-[var(--accent-primary)]/10 text-[var(--accent-primary)]' : 'text-[var(--fg-secondary)] hover:bg-[var(--bg-card-hover)]'}`}
            >
              {p.name || p.id}
            </button>
          ))}
        </div>
      </div>

      {/* Nav items */}
      <div className="p-3 flex-1 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            onClick={() => onSectionChange(item.id)}
            className={`nav-item ${activeSection === item.id ? 'active' : ''}`}
          >
            <item.icon size={16} />
            <span className="text-xs">{item.label}</span>
          </button>
        ))}
      </div>

      {/* Bottom: status indicator */}
      <div className="p-3 border-t border-[var(--border-subtle)]">
        <div className="flex items-center gap-2 text-[var(--fg-tertiary)] text-[10px]">
          <div className="w-2 h-2 rounded-full bg-[var(--accent-tertiary)] animate-pulse"></div>
          <span>System online</span>
        </div>
      </div>
    </div>
  )
}
