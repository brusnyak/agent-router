import React, { useState } from 'react'
import { Send, MoreVertical } from 'lucide-react'

interface ChatInputProps {
  project: string | null
  onSend: (message: string) => Promise<void>
  sending: boolean
}

export function ChatInput({ project, onSend, sending }: ChatInputProps) {
  const [input, setInput] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || sending) return
    await onSend(input)
    setInput('')
  }

  return (
    <div className="border-t border-[var(--border-subtle)] bg-[#1A1D26] p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-[var(--accent-primary)] animate-pulse"></div>
          <span className="text-[var(--fg-secondary)] text-xs">
            {project ? `Project: {project}` : 'Global context'}
          </span>
        </div>
        <button className="btn-ghost" title="More options">
          <MoreVertical size={16} />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Dump your thoughts here — the router will triage and delegate..."
          className="flex-1 bg-[#101216] border border-[var(--border-subtle)] rounded-lg px-4 py-3 text-[var(--fg-primary)] focus:outline-none focus:border-[var(--accent-primary)] resize-none font-mono text-xs"
          rows={4}
          disabled={sending}
        />
        <button
          type="submit"
          disabled={!input.trim() || sending}
          className="btn-primary disabled:opacity-50 flex items-center gap-2"
        >
          <Send size={18} />
          {sending ? 'Routing...' : 'Send'}
        </button>
      </form>
    </div>
  )
}
