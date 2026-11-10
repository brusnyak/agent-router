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

const LANE_COLORS: Record<string, string> = {
  backlog: '#646B78',
  triaging: '#CCA700',
  running: '#007ACC',
  review: '#007ACC',
  done: '#89D185',
  blocked: '#EF4444',
}

export function KanbanBoard({ cards, columnOrder, columnLabels, onCardClick, onStatusChange }: KanbanBoardProps) {
  const cardsByLane = columnOrder.reduce((acc, lane) => {
    acc[lane] = cards.filter(c => c.lane === lane)
    return acc
  }, {} as Record<string, KanbanCard[]>)

  return (
    <div className="flex flex-col gap-3">
      {columnOrder.map((lane) => (
        <div key={lane} className="flex flex-col gap-2">
          <div className="flex items-center justify-between mb-1">
            <span className="text-textSecondary font-medium text-sm uppercase tracking-wider">
              {columnLabels[lane] || lane}
            </span>
            <span className="text-textTertiary text-xs bg-[#303030] px-2 py-0.5 rounded">
              {cardsByLane[lane]?.length || 0}
            </span>
          </div>
          <div className="flex flex-col gap-2 min-h-[100px]">
            {cardsByLane[lane]?.map((card) => (
              <div
                key={card.id}
                onClick={() => onCardClick(card)}
                className="card-panel cursor-pointer hover:border-primary/50 transition-colors group"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-text truncate">{card.title}</span>
                  <span className={`badge ${lane === 'running' ? 'status-running' : lane === 'done' ? 'status-done' : lane === 'blocked' ? 'status-blocked' : lane === 'triaging' ? 'status-triaging' : 'status-review'}`}>
                    {card.status}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-textSecondary mb-1">
                  <span className="font-mono">{card.agent}</span>
                  <span className="w-px h-2 bg-border mx-1"></span>
                  <span className="font-mono">{card.model}</span>
                  {card.tokens_spent > 0 && (
                    <span className="ml-auto font-mono text-textTertiary">{card.tokens_spent} tok</span>
                  )}
                </div>
              </div>
            ))}
            {(!cardsByLane[lane] || cardsByLane[lane].length === 0) && (
              <div className="text-textTertiary text-xs italic py-2">Empty</div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
