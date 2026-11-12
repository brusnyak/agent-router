import React from 'react'
import { X, Play, Bot, Code, Timer, MessageCircle, ChevronLeft } from 'lucide-react'

interface CardDetailProps {
  card: any
  onClose: () => void
  onStatusChange: (newStatus: string) => void
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  triaging: { label: 'Triaging', color: '#CCA700' },
  running: { label: 'Running', color: '#007ACC' },
  review: { label: 'Review', color: '#007ACC' },
  done: { label: 'Done', color: '#89D185' },
  blocked: { label: 'Blocked', color: 'var(--danger)' },
  backlog: { label: 'Backlog', color: '#646B78' },
}

export function CardDetail({ card, onClose, onStatusChange }: CardDetailProps) {
  const config = STATUS_CONFIG[card.status] || STATUS_CONFIG.backlog

  const statuses = Object.entries(STATUS_CONFIG)

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4">
      <div className="bg-[var(--bg-card)] border border-[var(--border-active)] rounded-lg w-full max-w-5xl max-h-[95vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-[var(--border-subtle)] flex items-center justify-between">
          <button onClick={onClose} className="btn-ghost" title="Close">
            <X size={20} />
          </button>
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className={`badge ${config.label.toLowerCase().includes('run') ? 'status-running' : config.label.toLowerCase().includes('done') ? 'status-done' : config.label.toLowerCase().includes('block') ? 'status-blocked' : config.label.toLowerCase().includes('triag') ? 'status-triaging' : 'status-review'}`}>
                {config.label}
              </span>
              <span className="ml-auto font-mono text-[var(--fg-tertiary)] text-xs">{card.tokens_spent} tokens</span>
            </div>
            <h2 className="text-[var(--fg-primary)] text-lg font-medium truncate">{card.title}</h2>
            <div className="flex items-center gap-3 text-[var(--fg-tertiary)] text-xs mt-1">
              <span className="font-mono">{card.agent}</span>
              <span className="w-px h-3 bg-[var(--border-subtle)] mx-1"></span>
              <span className="font-mono">{card.model}</span>
              <span className="w-px h-3 bg-[var(--border-subtle)] mx-1"></span>
              <span>{card.project || 'global'}</span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {statuses.map(([key, cfg]) => (
              <button
                key={key}
                onClick={() => onStatusChange(key)}
                className={`px-2 py-1 rounded text-[10px] font-medium transition-colors ${card.status === key ? `bg-[${cfg.color}]/20 text-[${cfg.color}] border border-[${cfg.color}]/40` : 'text-[var(--fg-tertiary)] hover:bg-[var(--bg-card-hover)]'}`}
              >
                {cfg.label}
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Left: Prompt */}
            <div className="card-panel">
              <h3 className="text-[var(--fg-secondary)] font-medium text-xs mb-2 flex items-center gap-1">
                <Code size={14} /> Prompt Sent
              </h3>
              <div className="bg-[#101216] border border-[var(--border-subtle)] rounded p-3 text-[var(--fg-tertiary)] text-[10px] font-mono overflow-x-auto max-h-64 whitespace-pre-wrap">
                {card.prompt_sent || 'No prompt recorded'}
              </div>
            </div>

            {/* Middle: Output */}
            <div className="card-panel md:col-span-2">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-[var(--fg-secondary)] font-medium text-xs flex items-center gap-1">
                  <Bot size={14} /> Agent Output
                </h3>
              </div>
              <div className="bg-[#101216] border border-[var(--border-subtle)] rounded p-3 text-[var(--fg-primary)] text-[11px] font-mono overflow-y-auto max-h-96 whitespace-pre-wrap break-words">
                {card.output || 'No output recorded'}
              </div>
            </div>

            {/* Right: Delegation flow */}
            <div className="card-panel">
              <h3 className="text-[var(--fg-secondary)] font-medium text-xs mb-2 flex items-center gap-1">
                <Timer size={14} /> Delegation Flow
              </h3>
              <div className="space-y-2">
                {(card.delegation_flow || []).map((step: string, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-[10px]">
                    <span className="w-5 h-5 rounded-full bg-[var(--border-subtle)] flex items-center justify-center text-[var(--fg-tertiary)]">
                      {i + 1}
                    </span>
                    <span className="text-[var(--fg-primary)] truncate">{step}</span>
                    {i < (card.delegation_flow.length - 1) && (
                      <span className="text-[var(--fg-tertiary)]">→</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Reply */}
          <div className="mt-4 card-panel">
            <h3 className="text-[var(--fg-secondary)] font-medium text-xs mb-3 flex items-center gap-1">
              <MessageCircle size={14} /> Reply & Re-route
            </h3>
            <div className="flex gap-2">
              <textarea
                placeholder="Reply to re-route or add a comment..."
                className="flex-1 input-box text-[10px]"
                rows={3}
              />
              <button className="btn-primary px-4">Send</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
