import React, { useState, useEffect, useCallback } from 'react'
import { ChatInput } from './components/ChatInput'
import { KanbanBoard } from './components/KanbanBoard'
import { CardDetail } from './components/CardDetail'
import { AnalyticsSidebar } from './components/AnalyticsSidebar'
import { ProjectPicker } from './components/ProjectPicker'
import { LeftNav } from './components/LeftNav'
import { StatusBar } from './components/StatusBar'
import { listCards, getAnalytics, listProjects, listAgents, chat } from './lib/api'

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
  const [agents, setAgents] = useState<any[]>([])
  const [analytics, setAnalytics] = useState<any>(null)
  const [activeSection, setActiveSection] = useState<string>('dashboard')
  const [loading, setLoading] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [cardsRes, analyticsRes, projectsRes, agentsRes] = await Promise.all([
        listCards(),
        getAnalytics(),
        listProjects(),
        listAgents(),
      ])
      setCards(cardsRes.cards || [])
      setAnalytics(analyticsRes)
      setProjects(projectsRes)
      setAgents(agentsRes.agents || [])
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

  const handleCardStatusChange = async (cardId: string, newStatus: string) => {
    try {
      await fetch(`/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      setCards(cards.map(c => c.id === cardId ? { ...c, status: newStatus } : c))
      loadData()
    } catch (e) {
      console.error('Failed to update card', e)
    }
  }

  const handleNewCard = (card: any) => {
    setCards([card, ...cards])
    setSelectedCard(card)
    loadData()
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-window)]">
      {/* Left Nav */}
      <LeftNav
        activeSection={activeSection}
        onSectionChange={setActiveSection}
        projects={projects}
        selectedProject={project}
        onProjectChange={setProject}
      />

      {/* Main: Chat + Card Detail */}
      <div className="flex-1 flex flex-col min-w-0 border-l border-[var(--border-subtle)]">
        <div className="flex-1 flex flex-col min-w-0">
          <ChatInput
            project={project}
            onSend={async (message: string) => {
              setLoading(true)
              try {
                const res = await chat(message, project)
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
            sending={loading}
          />
        </div>

        {selectedCard && (
          <CardDetail
            card={selectedCard}
            onClose={() => setSelectedCard(null)}
            onStatusChange={(newStatus: string) => {
              handleCardStatusChange(selectedCard.id, newStatus)
            }}
          />
        )}
      </div>

      {/* Right: Analytics */}
      <div className="w-80 border-l border-[var(--border-subtle)] bg-[var(--bg-sidebar)] flex flex-col">
        <div className="p-4 border-b border-[var(--border-subtle)]">
          <h2 className="text-[var(--fg-primary)] font-medium mb-3">Analytics</h2>
        </div>
        <AnalyticsSidebar analytics={analytics} />
      </div>

      {/* Status Bar */}
      <StatusBar />
    </div>
  )
}
