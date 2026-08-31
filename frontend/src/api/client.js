import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const api = axios.create({ baseURL, timeout: 15000 })

// --- Auth token storage (localStorage) -------------------------------------
const TOKEN_KEY = 'voxera-token'

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export const setToken = (token) => {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // localStorage unavailable (private mode etc.) — token lives only in memory this session
  }
}

export const clearToken = () => {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }
}

// Attach the bearer token to every request.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Any 401 means the token is missing/expired/invalid — drop it and bounce to /login.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      clearToken()
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    return Promise.reject(error)
  },
)

// --- Auth endpoint --------------------------------------------------------
export const login = (username, password) =>
  api.post('/api/auth/login', { username, password }).then((r) => r.data)

// --- Real endpoints from backend/app/main.py — field names copied verbatim, not guessed. ---

export const getHealth = () => api.get('/api/health').then((r) => r.data)

export const getDashboardOverview = () => api.get('/api/dashboard/overview').then((r) => r.data)

export const getAttentionQueue = ({ limit = 20, offset = 0, intent, final_mood } = {}) =>
  api
    .get('/api/attention', {
      params: {
        limit,
        offset,
        ...(intent ? { intent } : {}),
        ...(final_mood ? { final_mood } : {}),
      },
    })
    .then((r) => r.data)

export const getIntents = () => api.get('/api/intents').then((r) => r.data)

export const getCall = (callId) => api.get(`/api/calls/${callId}`).then((r) => r.data)

// <audio> can't send an Authorization header, so the audio route also accepts
// the JWT as a ?token= query param (see verify_token_flexible in the backend).
export const getCallAudioUrl = (callId) => {
  const token = getToken()
  const suffix = token ? `?token=${encodeURIComponent(token)}` : ''
  return `${baseURL}/api/calls/${callId}/audio${suffix}`
}

export const getCustomers = () => api.get('/api/customers').then((r) => r.data)

export const getCustomerCalls = (customerId) =>
  api.get(`/api/customers/${customerId}/calls`).then((r) => r.data)

export const getAgents = () => api.get('/api/agents').then((r) => r.data)

export const getTrends = () => api.get('/api/trends').then((r) => r.data)

export const searchCalls = (q) => api.get('/api/search', { params: { q } }).then((r) => r.data)

// --- Manager Action Center ----------------------------------------------------

export const getActionItems = (status) =>
  api.get('/api/actions', { params: status ? { status } : {} }).then((r) => r.data)

export const getActionItem = (id) => api.get(`/api/actions/${id}`).then((r) => r.data)

export const updateActionItem = (id, patch) =>
  api.patch(`/api/actions/${id}`, patch).then((r) => r.data)

// The agentic tool-calling loop runs 2-4 Groq round-trips, so it needs a longer
// timeout than the 15s default the other (single-query) endpoints use.
export const askVoxera = (question) =>
  api.post('/api/ask', { question }, { timeout: 60000 }).then((r) => r.data)
