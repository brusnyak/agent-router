const API_BASE = '/api'

async function request(path: string, options?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`)
  return res.json()
}

export async function chat(message: string, project?: string) {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, project }),
  })
}

export async function listCards(status?: string, lane?: string) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (lane) params.set('lane', lane)
  return request(`/cards?${params}`)
}

export async function getCard(id: string) {
  return request(`/cards/${id}`)
}

export async function updateCard(id: string, data: any) {
  return request(`/cards/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  })
}

export async function addComment(cardId: string, author: string, body: string) {
  return request('/comments', {
    method: 'POST',
    body: JSON.stringify({ card_id: cardId, author, body }),
  })
}

export async function listProjects() {
  return request('/projects')
}

export async function getAnalytics() {
  return request('/analytics')
}

export async function listAgents() {
  return request('/agents')
}
