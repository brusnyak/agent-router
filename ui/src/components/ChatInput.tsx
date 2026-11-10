import React, { useState } from 'react'
import { Send, MoreVertical, Settings } from 'lucide-react'

interface ChatInputProps {
  project: string | null
  onSend: (message: string) => Promise<void>
}

export function ChatInput({ project, onSend }: ChatInputProps) {
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || sending) return
    setSending(true)
    await onSend(input)
    setInput('')
    setSending(false)
  }

  return (
    <div className="border-t border-border bg-[#252526] p-4 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
          <span className="text-textSecondary text-sm">
            {project ? `Project: {project}` : 'No project selected'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button className="p-2 hover:bg-[#303030] rounded text-textSecondary">
            <MoreVertical size={16} />
          </button>
          <button className="p-2 hover:bg-[#303030] rounded text-textSecondary">
            <Settings size={16} />
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Dump your thoughts here — the router will triage and delegate..."
          className="flex-1 bg-[#1E1E1E] border border-border rounded-lg px-4 py-3 text-text focus:outline-none focus:border-primary resize-none"
          rows={3}
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
