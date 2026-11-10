const API_BASE = '/api'

export async function chat(message: string, project?: string) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, project }),
  })
  if (!res.ok) throw new Error('Chat failed')
  return res.json()
}

export async function listCards(status?: string, lane?: string) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (lane) params.set('lane', lane)
  const res = await fetch(`${API_BASE}/cards?${params}`)
  if (!res.ok) throw new Error('Failed to load cards')
  return res.json()
}

export async function getCard(id: string) {
  const res = await fetch(`${API_BASE}/cards/${id}`)
  if (!res.ok) throw new Error('Failed to load card')
  return res.json()
}

export async function updateCard(id: string, data: any) {
  const res = await fetch(`${API_BASE}/cards/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update card')
  return res.json()
}

export async function addComment(cardId: string, author: string, body: string) {
  const res = await fetch(`${API_BASE}/comments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ card_id: cardId, author, body }),
  })
  if (!res.ok) throw new Error('Failed to add comment')
  return res.json()
}

export async function listProjects() {
  const res = await fetch(`${API_BASE}/projects`)
  if (!res.ok) throw new Error('Failed to load projects')
  return res.json()
}

export async function getAnalytics() {
  const res = await fetch(`${API_BASE}/analytics`)
  if (!res.ok) throw new Error('Failed to load analytics')
  return res.json()
}
