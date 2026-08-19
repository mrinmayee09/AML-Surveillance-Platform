import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import ErrorBoundary from './components/ErrorBoundary.jsx'
import { Spinner } from './components/ui.jsx'
import { useAuth } from './context/AuthContext.jsx'
import AppLayout from './layouts/AppLayout.jsx'
import AlertDetailPage from './pages/AlertDetailPage.jsx'
import AlertsPage from './pages/AlertsPage.jsx'
import AuditLogsPage from './pages/AuditLogsPage.jsx'
import CustomerDetailPage from './pages/CustomerDetailPage.jsx'
import CustomersPage from './pages/CustomersPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import DemoPage from './pages/DemoPage.jsx'
import GatewayPage from './pages/GatewayPage.jsx'
import InvestigationDetailPage from './pages/InvestigationDetailPage.jsx'
import InvestigationsPage from './pages/InvestigationsPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import ModelInsightsPage from './pages/ModelInsightsPage.jsx'
import NetworkPage from './pages/NetworkPage.jsx'
import NotFoundPage from './pages/NotFoundPage.jsx'
import ProactiveRiskPage from './pages/ProactiveRiskPage.jsx'
import ReactiveAmlPage from './pages/ReactiveAmlPage.jsx'
import RulesEnginePage from './pages/RulesEnginePage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import TransactionsPage from './pages/TransactionsPage.jsx'

function FullPageLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950">
      <div className="flex flex-col items-center gap-3 text-slateish-400">
        <Spinner size={22} />
        <p className="text-xs">Restoring session…</p>
      </div>
    </div>
  )
}

/** Gate every application route behind an authenticated session. */
function RequireAuth({ children }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullPageLoader />
  if (status !== 'authenticated') return <Navigate to="/login" replace />
  return (
    <AppLayout>
      {/* Keyed by pathname so navigating away clears a previous crash */}
      <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>
    </AppLayout>
  )
}

export default function App() {
  const { status } = useAuth()

  return (
    <Routes>
      <Route
        path="/login"
        element={
          status === 'authenticated' ? <Navigate to="/" replace /> : <LoginPage />
        }
      />

      <Route
        path="/"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route
        path="/transactions"
        element={
          <RequireAuth>
            <TransactionsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/customers"
        element={
          <RequireAuth>
            <CustomersPage />
          </RequireAuth>
        }
      />
      <Route
        path="/customers/:customerRef"
        element={
          <RequireAuth>
            <CustomerDetailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/gateway"
        element={
          <RequireAuth>
            <GatewayPage />
          </RequireAuth>
        }
      />
      <Route
        path="/proactive"
        element={
          <RequireAuth>
            <ProactiveRiskPage />
          </RequireAuth>
        }
      />
      <Route
        path="/reactive"
        element={
          <RequireAuth>
            <ReactiveAmlPage />
          </RequireAuth>
        }
      />
      <Route
        path="/network"
        element={
          <RequireAuth>
            <NetworkPage />
          </RequireAuth>
        }
      />
      <Route
        path="/alerts"
        element={
          <RequireAuth>
            <AlertsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/alerts/:alertRef"
        element={
          <RequireAuth>
            <AlertDetailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/investigations"
        element={
          <RequireAuth>
            <InvestigationsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/investigations/:caseRef"
        element={
          <RequireAuth>
            <InvestigationDetailPage />
          </RequireAuth>
        }
      />
      <Route
        path="/rules"
        element={
          <RequireAuth>
            <RulesEnginePage />
          </RequireAuth>
        }
      />
      <Route
        path="/models"
        element={
          <RequireAuth>
            <ModelInsightsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/audit-logs"
        element={
          <RequireAuth>
            <AuditLogsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth>
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/demo"
        element={
          <RequireAuth>
            <DemoPage />
          </RequireAuth>
        }
      />

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
