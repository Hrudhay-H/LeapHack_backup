import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { PhoneSim } from './components/PhoneSim'
import { LangProvider } from './lang'
import Admin from './pages/Admin'
import FarmerDashboard from './pages/FarmerDashboard'
import FarmerLogin from './pages/FarmerLogin'
import Landing from './pages/Landing'
import Simulate from './pages/Simulate'
import OperatorPortal from './pages/OperatorPortal'

export default function App() {
  return (
    <BrowserRouter>
      <LangProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/farmer" element={<FarmerLogin />} />
          <Route path="/farmer/dashboard" element={<FarmerDashboard />} />
          <Route path="/operator" element={<OperatorPortal />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/admin/simulate" element={<Simulate />} />
        </Routes>
      </LangProvider>
      <PhoneSim />
    </BrowserRouter>
  )
}
