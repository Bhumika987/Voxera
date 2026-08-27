import { Route, Routes } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import AttentionQueue from './pages/AttentionQueue.jsx'
import CallDetail from './pages/CallDetail.jsx'
import CustomerList from './pages/CustomerList.jsx'
import CustomerDetail from './pages/CustomerDetail.jsx'
import AgentsTrends from './pages/AgentsTrends.jsx'

export default function App() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-app-bg text-app-text">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Routes>
          <Route path="/" element={<AttentionQueue />} />
          <Route path="/calls/:callId" element={<CallDetail />} />
          <Route path="/customers" element={<CustomerList />} />
          <Route path="/customers/:customerId" element={<CustomerDetail />} />
          <Route path="/agents" element={<AgentsTrends />} />
        </Routes>
      </div>
    </div>
  )
}
