import React from 'react'

interface AnalyticsSidebarProps {
  analytics: any
}

export function AnalyticsSidebar({ analytics }: AnalyticsSidebarProps) {
  if (!analytics) {
    return (
      <div className="p-4 text-textSecondary text-sm">
        Loading analytics...
      </div>
    )
  }

  return (
    <div className="p-4 overflow-y-auto">
      <div className="mb-4">
        <div className="text-text text-sm font-medium mb-2">Total Cards</div>
        <div className="text-2xl font-mono text-text">{analytics.total_cards}</div>
      </div>

      <div className="mb-4">
        <div className="text-text text-sm font-medium mb-2">Tokens Spent</div>
        <div className="text-2xl font-mono text-text">{analytics.total_tokens.toLocaleString()}</div>
      </div>

      <div className="mb-4">
        <div className="text-text text-sm font-medium mb-2">Cards by Status</div>
        <div className="space-y-2">
          {Object.entries(analytics.cards_by_status || {}).map(([status, count]) => (
            <div key={status} className="flex items-center justify-between text-xs">
              <span className="text-textSecondary capitalize">{status}</span>
              <span className="font-mono text-text">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mb-4">
        <div className="text-text text-sm font-medium mb-2">Cards by Agent</div>
        <div className="space-y-2">
          {Object.entries(analytics.cards_by_agent || {}).map(([agent, count]) => (
            <div key={agent} className="flex items-center justify-between text-xs">
              <span className="text-textSecondary font-mono">{agent}</span>
              <span className="font-mono text-text">{count}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="text-text text-sm font-medium mb-2">Tokens by Agent</div>
        <div className="space-y-2">
          {Object.entries(analytics.tokens_by_agent || {}).map(([agent, tokens]) => (
            <div key={agent} className="flex items-center justify-between text-xs">
              <span className="text-textSecondary font-mono">{agent}</span>
              <span className="font-mono text-text">{tokens.toLocaleString()}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
