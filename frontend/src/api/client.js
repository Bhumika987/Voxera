import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const api = axios.create({ baseURL, timeout: 15000 })

// --- Real endpoints from backend/app/main.py — field names copied verbatim, not guessed. ---

export const getHealth = () => api.get('/api/health').then((r) => r.data)

export const getDashboardOverview = () => api.get('/api/dashboard/overview').then((r) => r.data)

export const getAttentionQueue = () => api.get('/api/attention').then((r) => r.data)

export const getCall = (callId) => api.get(`/api/calls/${callId}`).then((r) => r.data)

export const getCallAudioUrl = (callId) => `${baseURL}/api/calls/${callId}/audio`

export const getCustomers = () => api.get('/api/customers').then((r) => r.data)

export const getCustomerCalls = (customerId) =>
  api.get(`/api/customers/${customerId}/calls`).then((r) => r.data)

export const getAgents = () => api.get('/api/agents').then((r) => r.data)

export const getTrends = () => api.get('/api/trends').then((r) => r.data)

export const searchCalls = (q) => api.get('/api/search', { params: { q } }).then((r) => r.data)
