import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import AttentionQueue from './pages/AttentionQueue.jsx'
import ActionCenter from './pages/ActionCenter.jsx'
import CallDetail from './pages/CallDetail.jsx'
import CustomerList from './pages/CustomerList.jsx'
import CustomerDetail from './pages/CustomerDetail.jsx'
import AgentsTrends from './pages/AgentsTrends.jsx'
import Login from './pages/Login.jsx'
import AskWidget from './components/AskWidget.jsx'
import { useAuth } from './context/AuthContext.jsx'

function AppShell() {
  return (
    <div className="bg-app-gradient flex h-screen w-screen overflow-hidden text-app-text">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Routes>
          <Route path="/" element={<AttentionQueue />} />
          <Route path="/actions" element={<ActionCenter />} />
          <Route path="/calls/:callId" element={<CallDetail />} />
          <Route path="/customers" element={<CustomerList />} />
          <Route path="/customers/:customerId" element={<CustomerDetail />} />
          <Route path="/agents" element={<AgentsTrends />} />
        </Routes>
      </div>
      <AskWidget />
    </div>
  )
}

function RequireAuth({ children }) {
  const { isAuthenticated } = useAuth()
  const location = useLocation()
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return children
}

export default function App() {
  const { isAuthenticated } = useAuth()

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/" replace /> : <Login />}
      />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      />
    </Routes>
  )
}
