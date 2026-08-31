import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { clearToken, getToken, setToken } from '../api/client.js'

const AuthContext = createContext(null)

/** Decode a JWT payload without verifying the signature (that's the server's job). */
function readPayload(token) {
  try {
    return JSON.parse(atob(token.split('.')[1]))
  } catch {
    return null
  }
}

function readExp(token) {
  const p = readPayload(token)
  return p && typeof p.exp === 'number' ? p.exp : null
}

/** The signed-in manager's username (JWT `sub`), for display in the header. */
function readUsername(token) {
  const p = readPayload(token)
  return p && typeof p.sub === 'string' ? p.sub : null
}

function isValid(token) {
  if (!token) return false
  const exp = readExp(token)
  // No exp claim -> treat as invalid; otherwise must be in the future.
  return exp != null && exp * 1000 > Date.now()
}

export function AuthProvider({ children }) {
  const [token, setTokenState] = useState(() => {
    const existing = getToken()
    if (existing && !isValid(existing)) {
      clearToken()
      return null
    }
    return existing
  })

  const login = useCallback((newToken) => {
    setToken(newToken)
    setTokenState(newToken)
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setTokenState(null)
  }, [])

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: isValid(token),
      username: token ? readUsername(token) : null,
      login,
      logout,
    }),
    [token, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
