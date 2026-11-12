import React from 'react'

interface KanbanCard {
  id: string
  title: string
  lane: string
  agent: string
  model: string
  status: string
  project: string | null
  tokens_spent: number
  created_at: string
}

interface KanbanBoardProps {
  cards: KanbanCard[]
  columnOrder: string[]
  columnLabels: Record<string, string>
  onCardClick: (card: KanbanCard) => void
  onStatusChange: (cardId: string, newStatus: string) => void
}

const LANE_CONFIG: Record<string, { label: string; color: string; badge: string }> = {
  backlog: { label: 'Backlog', color: '#646B78', badge: 'status-backlog' },
  triaging: { label: 'Triaging', color: '#CCA700', badge: 'status-triaging' },
  running: { label: 'Running', color: '#007ACC', badge: 'status-running' },
  review: { label: 'Review', color: '#007ACC', badge: 'status-review' },
  done: { label: 'Done', color: '#89D185', badge: 'status-done' },
  blocked: { label: 'Blocked', color: 'var(--danger)', badge: 'status-blocked' },
}

export function KanbanBoard({ cards, columnOrder, columnLabels, onCardClick, onStatusChange }: KanbanBoardProps) {
  const cardsByLane = columnOrder.reduce((acc, lane) => {
    acc[lane] = cards.filter(c => c.lane === lane)
    return acc
  }, {} as Record<string, KanbanCard[]>)

  return (
    <div className="flex flex-col gap-3 px-4">
      {columnOrder.map((lane) => {
        const config = LANE_CONFIG[lane] || LANE_CONFIG.backlog
        const laneCards = cardsByLane[lane] || []
        return (
          <div key={lane} className="flex flex-col gap-2">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: config.color }}></div>
                <span className="text-[var(--fg-secondary)] font-medium text-sm uppercase tracking-wider">
                  {config.label}
                </span>
              </div>
              <span className="text-[var(--fg-tertiary)] text-xs bg-[var(--bg-card)] border border-[var(--border-subtle)] px-2 py-0.5 rounded">
                {laneCards.length}
              </span>
            </div>
            <div className="flex flex-col gap-2 min-h-[120px]">
              {laneCards.map((card) => (
                <div
                  key={card.id}
                  onClick={() => onCardClick(card)}
                  className="card-panel cursor-pointer hover:border-[var(--border-active)]/50 transition-colors group relative"
                >
                  <div className="absolute top-2 right-2 w-1 h-2 rounded" style={{ backgroundColor: config.color }}></div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-medium text-[var(--fg-primary)] truncate">{card.title}</span>
                    <span className={`badge ${config.badge}`}>{card.status}</span>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] text-[var(--fg-tertiary)] mb-1.5">
                    <span className="font-mono">{card.agent}</span>
                    <span className="w-px h-2 bg-[var(--border-subtle)] mx-1"></span>
                    <span className="font-mono">{card.model}</span>
                    {card.tokens_spent > 0 && (
                      <span className="ml-auto font-mono">{card.tokens_spent} tok</span>
                    )}
                  </div>
                </div>
              ))}
              {laneCards.length === 0 && (
                <div className="text-[var(--fg-tertiary)] text-xs italic py-2">Empty</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
