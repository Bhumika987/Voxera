import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Filter, LogOut, Moon, Sun } from 'lucide-react'
import GlobalSearch from './GlobalSearch.jsx'
import { useTheme } from '../context/ThemeContext.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { initials } from '../utils/format.js'
import { getAvatarColor } from '../utils/avatarColor.js'

/** Close `open` on outside-click or Escape. `ref` wraps the trigger + panel. */
function useDismiss(open, setOpen, ref) {
  useEffect(() => {
    if (!open) return
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClickOutside)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onClickOutside)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, setOpen, ref])
}

/** Prop-driven filter dropdown shown in the top bar. Only rendered when a page
 * passes a `filter` prop; `options` is [{ value, label, count? }], `value` is the
 * currently-applied value (or null), and `onApply(nextValue | null)` fires when
 * the user clicks OK or Clear. */
function FilterMenu({ label = 'Filter', options = [], value = null, onApply }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const ref = useRef(null)
  useDismiss(open, setOpen, ref)

  // Open the menu with the draft reset to whatever's currently applied.
  const toggle = () => {
    setDraft(value ?? '')
    setOpen((o) => !o)
  }

  const apply = () => {
    onApply?.(draft || null)
    setOpen(false)
  }
  const clear = () => {
    setDraft('')
    onApply?.(null)
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        title={label}
        onClick={toggle}
        className={`relative flex h-8 w-8 items-center justify-center rounded-md border transition ${
          value
            ? 'border-app-accent bg-app-accent/10 text-app-accent'
            : 'border-app-border text-app-text-secondary hover:border-app-accent hover:text-app-text'
        }`}
      >
        <Filter size={15} />
        {value && (
          <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-app-accent" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-72 rounded-lg border border-app-border bg-app-panel p-3 shadow-xl">
          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-app-text-secondary">
            {label}
          </label>
          <select
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="w-full rounded-md border border-app-border bg-app-bg px-2 py-1.5 text-sm text-app-text focus:border-app-accent focus:outline-none"
          >
            <option value="">All intents</option>
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
                {o.count != null ? ` (${o.count})` : ''}
              </option>
            ))}
          </select>
          <div className="mt-3 flex items-center justify-between">
            <button
              type="button"
              onClick={clear}
              className="text-xs text-app-text-secondary hover:text-app-text"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={apply}
              className="rounded-md bg-app-accent px-3 py-1 text-xs font-medium text-white transition hover:opacity-90"
            >
              OK
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** Light/dark toggle — icon shows the mode you'd switch TO. */
function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="flex h-8 w-8 items-center justify-center rounded-md border border-app-border text-app-text-secondary transition hover:border-app-accent hover:text-app-text"
    >
      {dark ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  )
}

/** Manager profile chip → dropdown with the account and a Log out action. */
function ProfileMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const navigate = useNavigate()
  const { username, logout } = useAuth()
  useDismiss(open, setOpen, ref)

  const name = username || 'Manager'

  const handleLogout = () => {
    setOpen(false)
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-md border border-app-border py-1 pl-1 pr-1.5 text-app-text-secondary transition hover:border-app-accent hover:text-app-text"
      >
        <span
          style={{ background: getAvatarColor(name) }}
          className="flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold text-white"
        >
          {initials(name)}
        </span>
        <span className="hidden max-w-[10rem] truncate text-sm capitalize sm:block">{name}</span>
        <ChevronDown size={14} className="shrink-0" />
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-52 overflow-hidden rounded-lg border border-app-border bg-app-panel shadow-xl">
          <div className="border-b border-app-border px-3 py-2.5">
            <div className="truncate text-sm font-medium capitalize text-app-text">{name}</div>
            <div className="text-xs text-app-text-secondary">Call-centre manager</div>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-sm text-app-text-secondary transition hover:bg-app-panel-raised hover:text-app-text"
          >
            <LogOut size={15} /> Log out
          </button>
        </div>
      )}
    </div>
  )
}

/** Shared header on every page: a left slot for a page title / breadcrumb, the
 * global search bar, an optional filter dropdown, the theme toggle, and the
 * manager profile menu. Pass `title` + `subtitle` for the standard heading, or
 * `children` for a custom left slot (e.g. a back button on the detail pages). */
export default function TopBar({ title, subtitle, children, filter }) {
  return (
    <header className="flex min-h-16 shrink-0 items-center justify-between gap-6 border-b border-app-border bg-app-panel px-6 py-2">
      <div className="min-w-0 flex-1">
        {title ? (
          <>
            <h1 className="truncate text-xl font-semibold text-app-text">{title}</h1>
            {subtitle && <p className="truncate text-sm text-app-text-secondary">{subtitle}</p>}
          </>
        ) : (
          children
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <GlobalSearch />
        {filter && <FilterMenu {...filter} />}
        <div className="mx-1 h-6 w-px bg-app-border" />
        <ThemeToggle />
        <ProfileMenu />
      </div>
    </header>
  )
}
