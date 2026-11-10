import React from 'react'
import { X, ChevronLeft, MessageCircle, Play, Bot, Code, Timer } from 'lucide-react'

interface CardDetailProps {
  card: any
  onClose: () => void
  onStatusChange: (newStatus: string) => void
}

const STATUS_COLORS: Record<string, string> = {
  triaging: '#CCA700',
  running: '#007ACC',
  review: '#007ACC',
  done: '#89D185',
  blocked: '#EF4444',
}

export function CardDetail({ card, onClose, onStatusChange }: CardDetailProps) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#1A1D26] border border-[#363C4D] rounded-lg w-full max-w-4xl max-h-[90vh] flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-[#242833] flex items-center justify-between">
          <button onClick={onClose} className="p-2 hover:bg-[#212530] rounded text-textSecondary">
            <X size={20} />
          </button>
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className={`badge ${card.status === 'running' ? 'status-running' : card.status === 'done' ? 'status-done' : card.status === 'blocked' ? 'status-blocked' : card.status === 'triaging' ? 'status-triaging' : 'status-review'}`}>
                {card.status}
              </span>
              <span className="text-xs font-mono text-textTertiary ml-auto">{card.tokens_spent} tokens</span>
            </div>
            <h2 className="text-text text-lg font-medium truncate">{card.title}</h2>
            <div className="flex items-center gap-2 text-textTertiary text-xs mt-1">
              <span className="font-mono">{card.agent}</span>
              <span className="w-px h-3 bg-[#242833] mx-1"></span>
              <span className="font-mono">{card.model}</span>
              <span className="w-px h-3 bg-[#242833] mx-1"></span>
              <span>{card.project || 'global'}</span>
            </div>
          </div>
          <button onClick={() => onStatusChange(card.status === 'done' ? 'backlog' : 'done')} className="p-2 hover:bg-[#212530] rounded text-textSecondary">
            <Play size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Left: Prompt sent */}
            <div className="card-panel">
              <h3 className="text-textSecondary font-medium text-sm mb-2 flex items-center gap-1">
                <Code size={16} /> Prompt Sent
              </h3>
              <div className="bg-[#101216] border border-[#242833] rounded p-3 text-xs font-mono text-textTertiary overflow-x-auto max-h-64">
                {card.prompt_sent || 'No prompt recorded'}
              </div>
            </div>

            {/* Middle: Output */}
            <div className="card-panel md:col-span-2">
              <h3 className="text-textSecondary font-medium text-sm mb-2 flex items-center gap-1">
                <Bot size={16} /> Agent Output
              </h3>
              <div className="bg-[#101216] border border-[#242833] rounded p-3 text-xs font-mono text-text overflow-y-auto max-h-96 whitespace-pre-wrap">
                {card.output || 'No output recorded'}
              </div>
            </div>

            {/* Right: Delegation flow */}
            <div className="card-panel">
              <h3 className="text-textSecondary font-medium text-sm mb-2 flex items-center gap-1">
                <Timer size={16} /> Delegation Flow
              </h3>
              <div className="space-y-2">
                {(card.delegation_flow || []).map((step: string, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="w-6 h-6 rounded-full bg-[#242833] flex items-center justify-center text-textSecondary">
                      {i + 1}
                    </span>
                    <span className="text-text truncate">{step}</span>
                    {i < (card.delegation_flow.length - 1) && (
                      <span className="text-textTertiary">→</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Comments / Reply */}
          <div className="mt-4 card-panel">
            <h3 className="text-textSecondary font-medium text-sm mb-3 flex items-center gap-1">
              <MessageCircle size={16} /> Reply & Re-route
            </h3>
            <div className="flex gap-2">
              <textarea
                placeholder="Reply to re-route or add a comment..."
                className="flex-1 input-box text-xs"
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
