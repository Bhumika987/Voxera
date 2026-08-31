import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Sparkles, Send, ArrowRight, Wrench, Loader2, AlertTriangle, X } from 'lucide-react'
import { askVoxera } from '../api/client.js'

const SUGGESTIONS = [
  'Which issue category has the highest unresolved rate?',
  'Which agents handled the most unresolved calls?',
  'Calls where the customer started calm but ended up frustrated?',
  'How do the four call days compare on resolution rate?',
]

// Groq's answers sometimes contain a narrow / non-breaking space (U+202F, U+00A0)
// around "%". Normalise to a plain space so spacing renders consistently.
const NBSP_RE = new RegExp('[\\u202f\\u00a0]', 'g')
const clean = (s) => (s || '').replace(NBSP_RE, ' ')

const OPEN_KEY = 'voxera-ask-open'
// Voxa mascot — frontend/public/voxa.svg (cropped to the circular badge).
// Falls back to the Sparkles icon if it fails to load.
const BOT_IMG = '/voxa.svg'

/** Circular Voxa avatar — mascot image if it loads, Sparkles icon otherwise. */
function BotAvatar({ size = 32, className = '' }) {
  const [broken, setBroken] = useState(false)
  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-app-accent text-white ${className}`}
      style={{ width: size, height: size }}
    >
      {broken ? (
        <Sparkles size={Math.round(size * 0.55)} />
      ) : (
        <img
          src={BOT_IMG}
          alt="Voxa"
          className="h-full w-full scale-[1.08] object-cover"
          onError={() => setBroken(true)}
        />
      )}
    </span>
  )
}

function ToolChip({ call }) {
  const arg = call.arguments || {}
  const detail =
    arg.group_by ||
    arg.query ||
    arg.call_id ||
    (arg.filters ? Object.keys(arg.filters).join(', ') : '')
  return (
    <span className="inline-flex items-center gap-1 rounded border border-app-border bg-app-bg px-1 py-0.5 text-[11px] text-app-text-secondary">
      <Wrench size={10} />
      <span className="font-mono-data">{call.tool}</span>
      {detail && <span className="opacity-70">· {String(detail).slice(0, 28)}</span>}
    </span>
  )
}

function AnswerBubble({ turn, onNavigate }) {
  return (
    <div className="rounded-lg rounded-tl-sm border border-app-border bg-app-panel-raised p-3">
      {turn.error ? (
        <div className="flex items-start gap-2 text-sm text-app-text-secondary">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-mood-angry" />
          <span>{turn.error}</span>
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-app-text">{clean(turn.answer)}</p>
      )}

      {turn.evidence_call_ids?.length > 0 && (
        <div className="mt-2.5">
          <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-app-text-secondary">
            Supporting calls
          </div>
          <div className="flex flex-wrap gap-1">
            {turn.evidence_call_ids.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onNavigate(id)}
                className="group inline-flex items-center gap-1 rounded border border-app-border bg-app-bg px-1.5 py-0.5 font-mono-data text-[11px] text-app-text-secondary transition hover:border-app-accent hover:text-app-accent"
              >
                {id.slice(0, 8)}
                <ArrowRight size={10} className="opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            ))}
          </div>
        </div>
      )}

      {turn.tool_calls?.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-app-text-secondary">Ran</span>
          {turn.tool_calls.map((c, i) => (
            <ToolChip key={i} call={c} />
          ))}
        </div>
      )}
    </div>
  )
}

export default function AskWidget() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(OPEN_KEY) === '1'
    } catch {
      return false
    }
  })
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState([]) // { question } | { answer, evidence_call_ids, tool_calls } | { error }
  const [pending, setPending] = useState(false)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    try {
      localStorage.setItem(OPEN_KEY, open ? '1' : '0')
    } catch {
      // ignore
    }
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, pending, open])

  const submit = async (question) => {
    const q = (question || '').trim()
    if (!q || pending) return
    setInput('')
    setTurns((t) => [...t, { question: q }])
    setPending(true)
    try {
      const data = await askVoxera(q)
      setTurns((t) => [...t, { ...data }])
    } catch (err) {
      const status = err?.response?.status
      const msg =
        status === 503
          ? "Voxa's AI service is unavailable — check GROQ_API_KEY in backend/.env."
          : err?.code === 'ECONNABORTED'
            ? 'That took too long to answer. Try something more specific.'
            : "Couldn't reach the API. Is the backend running on :8000?"
      setTurns((t) => [...t, { error: msg }])
    } finally {
      setPending(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit(input)
    }
  }

  const goToCall = (id) => {
    navigate(`/calls/${id}`)
  }

  return (
    <>
      {/* Panel */}
      {open && (
        <div className="fixed bottom-24 left-5 z-50 flex h-[560px] max-h-[calc(100vh-8rem)] w-[380px] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-xl border border-app-border bg-app-panel shadow-2xl">
          <div className="flex items-center gap-2.5 border-b border-app-border bg-app-accent/10 px-4 py-3">
            <BotAvatar size={32} />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-app-text">Ask Voxa</div>
              <div className="text-xs text-app-text-secondary">Lost track? Let&apos;s find your way back.</div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close"
              className="flex h-7 w-7 items-center justify-center rounded-md text-app-text-secondary transition hover:bg-app-panel-raised hover:text-app-text"
            >
              <X size={16} />
            </button>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
            <div className="flex gap-2">
              <BotAvatar size={26} className="mt-0.5" />
              <div className="rounded-lg rounded-tl-sm border border-app-border bg-app-panel-raised p-3 text-sm text-app-text">
                Hey, I&apos;m Voxa 👋 Lost track of what&apos;s going on in your calls? Ask me
                anything — I&apos;ll dig up the numbers and the calls behind them.
              </div>
            </div>

            {turns.length === 0 && !pending && (
              <div className="flex flex-col items-start gap-1.5 pl-9">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => submit(s)}
                    className="rounded-full border border-app-border bg-app-bg px-3 py-1.5 text-left text-xs text-app-text-secondary transition hover:border-app-accent hover:text-app-text"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {turns.map((turn, i) =>
              turn.question ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-lg rounded-tr-sm bg-app-accent/12 px-3 py-2 text-sm text-app-text">
                    {turn.question}
                  </div>
                </div>
              ) : (
                <AnswerBubble key={i} turn={turn} onNavigate={goToCall} />
              ),
            )}

            {pending && (
              <div className="flex items-center gap-2 rounded-lg rounded-tl-sm border border-app-border bg-app-panel-raised p-3 text-sm text-app-text-secondary">
                <Loader2 size={14} className="animate-spin" />
                Querying the call data…
              </div>
            )}
          </div>

          <div className="border-t border-app-border p-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
                rows={1}
                placeholder="Ask a question…"
                className="max-h-24 flex-1 resize-none rounded-md border border-app-border bg-app-bg px-3 py-2 text-sm text-app-text placeholder:text-app-text-secondary focus:border-app-accent focus:outline-none"
              />
              <button
                type="button"
                onClick={() => submit(input)}
                disabled={pending || !input.trim()}
                aria-label="Send"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-app-accent text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Send size={15} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Launcher */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? 'Close Ask Voxa' : 'Open Ask Voxa'}
        className="fixed bottom-5 left-5 z-50 flex h-14 w-14 items-center justify-center overflow-hidden rounded-full bg-app-accent text-white shadow-xl transition hover:scale-105 hover:opacity-95 active:scale-95"
      >
        {open ? <X size={22} /> : <BotAvatar size={56} />}
      </button>
    </>
  )
}
