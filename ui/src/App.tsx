import React, { useState, useEffect, useCallback } from 'react'
import { ChatInput } from './components/ChatInput'
import { KanbanBoard } from './components/KanbanBoard'
import { CardDetail } from './components/CardDetail'
import { AnalyticsSidebar } from './components/AnalyticsSidebar'
import { ProjectPicker } from './components/ProjectPicker'
import { listCards, getAnalytics, listProjects } from './lib/api'

const COLUMN_ORDER = ['backlog', 'triaging', 'running', 'review', 'done', 'blocked']

const COLUMN_LABELS: Record<string, string> = {
  backlog: 'Backlog',
  triaging: 'Triaging',
  running: 'Running',
  review: 'Review',
  done: 'Done',
  blocked: 'Blocked',
}

export default function App() {
  const [cards, setCards] = useState<any[]>([])
  const [selectedCard, setSelectedCard] = useState<any | null>(null)
  const [project, setProject] = useState<string | null>(null)
  const [projects, setProjects] = useState<any[]>([])
  const [analytics, setAnalytics] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [cardsRes, analyticsRes, projectsRes] = await Promise.all([
        listCards(),
        getAnalytics(),
        listProjects(),
      ])
      setCards(cardsRes.cards || [])
      setAnalytics(analyticsRes)
      setProjects(projectsRes)
    } catch (e) {
      console.error('Failed to load data', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleCardClick = (card: any) => {
    setSelectedCard(card)
  }

  const handleCardStatusChange = (cardId: string, newStatus: string) => {
    updateCard(cardId, { status: newStatus }).then(() => {
      setCards(cards.map(c => c.id === cardId ? { ...c, status: newStatus } : c))
      loadData()
    })
  }

  const handleNewCard = (card: any) => {
    setCards([card, ...cards])
    setSelectedCard(card)
    loadData()
  }

  return (
    <div className="flex h-screen overflow-hidden bg-neutral">
      {/* Sidebar: Project picker + Kanban */}
      <div className="w-80 border-r border-border flex flex-col bg-sidebar">
        <div className="p-4 border-b border-border">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full bg-primary"></div>
            <span className="font-bold text-text text-lg">Agent Router</span>
          </div>
          <div className="mt-2 text-textTertiary text-xs">
            LangGraph • NIM 3 Supervisor
          </div>
        </div>

        <ProjectPicker
          projects={projects}
          selectedProject={project}
          onSelect={setProject}
        />

        <div className="p-4 border-t border-border flex-1 overflow-y-auto">
          <h2 className="text-text font-medium mb-3">Kanban</h2>
          <KanbanBoard
            cards={cards}
            columnOrder={COLUMN_ORDER}
            columnLabels={COLUMN_LABELS}
            onCardClick={handleCardClick}
            onStatusChange={handleCardStatusChange}
          />
        </div>
      </div>

      {/* Main: Chat + Card Detail */}
      <div className="flex-1 flex flex-col border-l border-border bg-neutral">
        <div className="flex-1 flex flex-col min-w-0">
          <ChatInput
            project={project}
            onSend={async (message: string) => {
              setLoading(true)
              try {
                const res = await fetchChat(message, project)
                if (res.card) {
                  handleNewCard(res.card)
                  setSelectedCard(res.card)
                }
              } catch (e) {
                console.error(e)
              } finally {
                setLoading(false)
              }
            }}
          />
        </div>

        {selectedCard && (
          <CardDetail
            card={selectedCard}
            onClose={() => setSelectedCard(null)}
            onStatusChange={(newStatus: string) => {
              updateCard(selectedCard.id, { status: newStatus }).then(() => loadData())
            }}
          />
        )}
      </div>

      {/* Right: Analytics */}
      <div className="w-72 border-l border-border bg-sidebar flex flex-col">
        <div className="p-4 border-b border-border">
          <h2 className="text-text font-medium mb-3">Analytics</h2>
        </div>
        <AnalyticsSidebar analytics={analytics} />
      </div>
    </div>
  )
}

async function fetchChat(message: string, project?: string) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, project }),
  })
  if (!res.ok) throw new Error('Chat failed')
  return res.json()
}
