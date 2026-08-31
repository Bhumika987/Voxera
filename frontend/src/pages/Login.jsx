import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { login as loginRequest } from '../api/client.js'
import { useAuth } from '../context/AuthContext.jsx'
import { VoxeraLogo } from '../components/VoxeraLogo.jsx'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // Where to land after login: wherever they were headed, or the Attention Queue.
  const redirectTo = location.state?.from?.pathname || '/'

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const { access_token: token } = await loginRequest(username.trim(), password)
      if (!token) throw new Error('No token returned')
      login(token)
      navigate(redirectTo, { replace: true })
    } catch (err) {
      const status = err?.response?.status
      setError(
        status === 401
          ? 'Incorrect username or password.'
          : "Couldn't reach the API. Is the backend running on :8000?",
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-app-gradient flex h-screen w-screen items-center justify-center px-4 text-app-text">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <VoxeraLogo size={44} />
          <span className="text-lg font-semibold tracking-tight">Voxera</span>
        </div>

        <div className="rounded-lg border border-app-border bg-app-panel p-6">
          <h1 className="text-lg font-semibold">Manager sign in</h1>
          <p className="mt-1 text-sm text-app-text-secondary">
            The dashboard is restricted to the call-centre manager.
          </p>

          <form onSubmit={handleSubmit} className="mt-5 space-y-4">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-app-text-secondary">Username</span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                className="w-full rounded-md border border-app-border bg-app-bg px-3 py-2 text-sm text-app-text placeholder:text-app-text-secondary focus:border-app-accent focus:outline-none"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-app-text-secondary">Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                className="w-full rounded-md border border-app-border bg-app-bg px-3 py-2 text-sm text-app-text placeholder:text-app-text-secondary focus:border-app-accent focus:outline-none"
              />
            </label>

            {error && (
              <div className="rounded-md border border-mood-angry/30 bg-mood-angry/10 px-3 py-2 text-xs text-mood-angry">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-app-accent px-3 py-2 text-sm font-medium text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting && <Loader2 size={15} className="animate-spin" />}
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
