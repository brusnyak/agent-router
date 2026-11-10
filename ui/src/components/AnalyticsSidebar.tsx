import React from 'react'

interface AnalyticsSidebarProps {
  analytics: any
}

export function AnalyticsSidebar({ analytics }: AnalyticsSidebarProps) {
  if (!analytics) {
    return (
      <div className="p-4 text-[var(--fg-tertiary)] text-xs">
        Loading analytics…
      </div>
    )
  }

  return (
    <div className="p-4 overflow-y-auto">
      <div className="mb-4">
        <div className="text-[var(--fg-secondary)] text-[10px] font-medium mb-1 uppercase tracking-wider">Total Cards</div>
        <div className="text-xl font-mono text-[var(--fg-primary)]">{analytics.total_cards}</div>
      </div>

      <div className="mb-4">
        <div className="text-[var(--fg-secondary)] text-[10px] font-medium mb-1 uppercase tracking-wider">Tokens Spent</div>
        <div className="text-xl font-mono text-[var(--fg-primary)]">{analytics.total_tokens.toLocaleString()}</div>
      </div>

      <div className="mb-4">
        <div className="text-[var(--fg-secondary)] text-[10px] font-medium mb-1 uppercase tracking-wider">Cards by Status</div>
        <div className="space-y-2">
          {Object.entries(analytics.cards_by_status || {}).map(([status, count]) => (
            <div key={status} className="flex items-center justify-between text-[10px]">
              <span className="text-[var(--fg-tertiary)] capitalize">{status}</span>
              <span className="font-mono text-[var(--fg-primary)]">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <div className="text-[var(--fg-secondary)] text-[10px] font-medium mb-1 uppercase tracking-wider">Cards by Agent</div>
        <div className="space-y-2">
          {Object.entries(analytics.cards_by_agent || {}).map(([agent, count]) => (
            <div key={agent} className="flex items-center justify-between text-[10px]">
              <span className="text-[var(--fg-tertiary)] font-mono">{agent}</span>
              <span className="font-mono text-[var(--fg-primary)]">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="text-[var(--fg-secondary)] text-[10px] font-medium mb-1 uppercase tracking-wider">Tokens by Agent</div>
        <div className="space-y-2">
          {Object.entries(analytics.tokens_by_agent || {}).map(([agent, tokens]) => (
            <div key={agent} className="flex items-center justify-between text-[10px]">
              <span className="text-[var(--fg-tertiary)] font-mono">{agent}</span>
              <span className="font-mono text-[var(--fg-primary)]">{tokens.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
