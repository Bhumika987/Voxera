import { NavLink } from 'react-router-dom'
import { Radar, Users, BarChart3, Sun, Moon } from 'lucide-react'
import { useTheme } from '../context/ThemeContext.jsx'

const NAV_ITEMS = [
  { to: '/', label: 'Attention Queue', icon: Radar, end: true },
  { to: '/customers', label: 'Customers', icon: Users },
  { to: '/agents', label: 'Agents & Trends', icon: BarChart3 },
]

export default function Sidebar() {
  const { theme, toggleTheme } = useTheme()

  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-app-border bg-app-panel">
      <div className="flex items-center gap-2 px-5 py-5">
        <Radar size={20} className="text-app-accent" />
        <span className="text-base font-semibold tracking-tight text-app-text">Voxera</span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition ${
                isActive
                  ? 'bg-app-accent/12 font-medium text-app-accent'
                  : 'text-app-text-secondary hover:bg-app-panel-raised hover:text-app-text'
              }`
            }
          >
            <Icon size={17} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-app-border p-3">
        <button
          type="button"
          onClick={toggleTheme}
          className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-app-text-secondary transition hover:bg-app-panel-raised hover:text-app-text"
        >
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
      </div>
    </aside>
  )
}
