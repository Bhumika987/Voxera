import { NavLink } from 'react-router-dom'
import { Radar, Users, BarChart3, ListChecks } from 'lucide-react'
import { VoxeraLogo } from './VoxeraLogo.jsx'

const NAV_ITEMS = [
  { to: '/', label: 'Attention Queue', icon: Radar, end: true },
  { to: '/actions', label: 'Action Center', icon: ListChecks },
  { to: '/customers', label: 'Customers', icon: Users },
  { to: '/agents', label: 'Agents & Trends', icon: BarChart3 },
]

export default function Sidebar() {
  return (
    <aside className="flex h-full w-56 shrink-0 flex-col border-r border-app-border bg-app-panel">
      <div className="flex flex-col items-center gap-3 px-5 py-6">
        <VoxeraLogo size={176} />
        <span className="text-lg font-semibold uppercase tracking-wide text-app-text">Voxera</span>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-md px-3 py-2 text-base transition ${
                isActive
                  ? 'bg-app-accent/12 font-medium text-app-accent'
                  : 'text-app-text-secondary hover:bg-app-panel-raised hover:text-app-text'
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
