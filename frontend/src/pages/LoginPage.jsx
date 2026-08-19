import { AlertTriangle, KeyRound, Loader2, Shield } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Advisory, Button, TextInput } from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'

// Demo credentials are seeded by `python -m seed.seed` and printed by it.
const DEMO_ACCOUNTS = [
  { username: 'analyst', password: 'Analyst@2026', role: 'Analyst', can: 'Review alerts, investigate networks, add notes' },
  { username: 'admin', password: 'Admin@2026', role: 'Administrator', can: 'All analyst rights plus rules, users and audit logs' },
]

export default function LoginPage() {
  const { login } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(false)

  async function onSubmit(event) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      const user = await login(username.trim(), password)
      toast.success(`Signed in as ${user.full_name} (${user.role}).`)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err?.message ?? 'Sign-in failed.')
    } finally {
      setPending(false)
    }
  }

  function useDemo(account) {
    setUsername(account.username)
    setPassword(account.password)
    setError(null)
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4 py-10">
      <div className="w-full max-w-4xl">
        <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
          {/* ---------------------------------------------------- sign-in */}
          <div className="rounded-card border border-ink-700 bg-ink-900 p-6 shadow-raised">
            <div className="mb-5 flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded bg-accent/15 ring-1 ring-accent/30">
                <Shield size={18} className="text-accent" aria-hidden="true" />
              </div>
              <div>
                <h1 className="text-base font-semibold tracking-tight text-white">Meridian AML</h1>
                <p className="text-xs text-slateish-400">
                  Financial Surveillance &amp; Transaction Security
                </p>
              </div>
            </div>

            <form onSubmit={onSubmit} className="space-y-3">
              <div>
                <label
                  htmlFor="username"
                  className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400"
                >
                  Username
                </label>
                <TextInput
                  id="username"
                  name="username"
                  autoComplete="username"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="analyst"
                />
              </div>
              <div>
                <label
                  htmlFor="password"
                  className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400"
                >
                  Password
                </label>
                <TextInput
                  id="password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  icon={KeyRound}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                />
              </div>

              {error && (
                <p
                  role="alert"
                  className="flex items-start gap-2 rounded border border-risk-high/40 bg-risk-highBg px-2.5 py-2 text-2xs text-risk-high"
                >
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={pending}
                className="flex w-full items-center justify-center gap-2 rounded border border-info bg-info py-2 text-xs font-semibold text-white transition-colors hover:bg-info/85 disabled:opacity-60"
              >
                {pending && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
                {pending ? 'Signing in…' : 'Sign in'}
              </button>
            </form>

            <Advisory className="mt-5">
              Authentication is enforced server-side with bcrypt password hashing and short-lived
              JWTs. The token is held in <code className="text-slateish-300">sessionStorage</code>{' '}
              only; no secret, model artifact or database credential ever reaches the browser.
            </Advisory>
          </div>

          {/* ------------------------------------------------ demo context */}
          <div className="space-y-4">
            <div className="rounded-card border border-ink-700 bg-ink-850/70 p-5">
              <h2 className="mb-1 text-sm font-semibold text-slateish-100">Demo credentials</h2>
              <p className="mb-3 text-2xs text-slateish-400">
                Seeded accounts. Click one to fill the form.
              </p>
              <ul className="space-y-2">
                {DEMO_ACCOUNTS.map((account) => (
                  <li key={account.username}>
                    <button
                      type="button"
                      onClick={() => useDemo(account)}
                      className="w-full rounded border border-ink-600 bg-ink-800/70 p-2.5 text-left transition-colors hover:border-info/40 hover:bg-ink-750"
                    >
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="font-mono text-xs font-semibold text-slateish-100">
                          {account.username}
                        </span>
                        <span className="text-2xs text-info">{account.role}</span>
                      </div>
                      <p className="mt-0.5 font-mono text-2xs text-slateish-400">
                        {account.password}
                      </p>
                      <p className="mt-1 text-2xs leading-snug text-slateish-400">{account.can}</p>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-card border border-ink-700 bg-ink-850/70 p-5">
              <h2 className="mb-2 text-sm font-semibold text-slateish-100">
                What this platform does
              </h2>
              <ul className="space-y-2 text-2xs leading-relaxed text-slateish-400">
                <li>
                  <strong className="text-slateish-200">Transaction integrity</strong> — was the
                  payment request modified before reaching the provider? The server-side order
                  amount is authoritative.
                </li>
                <li>
                  <strong className="text-slateish-200">Proactive AML</strong> — is this customer
                  becoming risky, before the transaction is authorised?
                </li>
                <li>
                  <strong className="text-slateish-200">Reactive AML + GNN</strong> — do settled
                  transactions form suspicious patterns or laundering networks?
                </li>
              </ul>
              <p className="mt-3 border-t border-ink-700 pt-2.5 text-2xs leading-relaxed text-slateish-400/80">
                Academic prototype running on synthetic data. Risk scores are prioritisation
                signals for human review and are never proof of criminal activity.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
