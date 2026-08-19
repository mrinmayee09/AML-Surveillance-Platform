/**
 * Run AML Demo.
 *
 * Executes the platform's whole narrative as one coherent story rather than a set
 * of disconnected pages. Every step performs real work against the live database
 * via the same services the individual pages call, and each step links to where
 * the investigator can go and verify it.
 */
import clsx from 'clsx'
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  CheckCircle2,
  Minus,
  PlayCircle,
  RotateCcw,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  KeyValue,
  PageHeader,
  Spinner,
} from '../components/ui.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatInr, humanise } from '../utils/format.js'

const LAYER_TONE = {
  CLIENT: 'neutral',
  INTEGRITY: 'critical',
  PROACTIVE: 'info',
  PAYMENT: 'low',
  REACTIVE: 'medium',
  NETWORK: 'accent',
  INVESTIGATION: 'info',
  SETUP: 'neutral',
}

const STATUS_META = {
  PASS: { icon: CheckCircle2, color: '#22a06b', label: 'Pass' },
  WARN: { icon: AlertTriangle, color: '#d99524', label: 'Attention' },
  FAIL: { icon: Ban, color: '#e0533d', label: 'Blocked' },
  SKIPPED: { icon: Minus, color: '#8b9ab5', label: 'Skipped' },
}

function DetailValue({ value }) {
  if (value === null || value === undefined) return <span className="text-slateish-400">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString('en-IN') : value.toFixed(2)
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-slateish-400">none</span>
    if (typeof value[0] === 'object') {
      return (
        <ul className="space-y-0.5">
          {value.slice(0, 5).map((item, i) => (
            <li key={i} className="text-[9.5px] text-slateish-300">
              {Object.entries(item)
                .filter(([, v]) => v !== null && typeof v !== 'object')
                .slice(0, 4)
                .map(([k, v]) => `${humanise(k)}: ${v}`)
                .join(' · ')}
            </li>
          ))}
        </ul>
      )
    }
    return value.slice(0, 6).join(', ')
  }
  if (typeof value === 'object') {
    return (
      <span className="text-[9.5px]">
        {Object.entries(value)
          .filter(([, v]) => v !== null && typeof v !== 'object')
          .slice(0, 5)
          .map(([k, v]) => `${humanise(k)}: ${v}`)
          .join(' · ')}
      </span>
    )
  }
  return String(value)
}

function StepCard({ step }) {
  const meta = STATUS_META[step.status] ?? STATUS_META.SKIPPED
  const Icon = meta.icon
  const detailEntries = Object.entries(step.detail ?? {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== '',
  )

  return (
    <li className="relative flex gap-3 pb-4">
      <span className="absolute left-[13px] top-7 h-full w-px bg-ink-700" aria-hidden="true" />
      <span
        className="relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2"
        style={{ borderColor: `${meta.color}66`, backgroundColor: `${meta.color}1f` }}
      >
        <span className="tnum font-mono text-[10px] font-bold" style={{ color: meta.color }}>
          {step.index}
        </span>
      </span>

      <div className="min-w-0 flex-1 rounded-card border border-ink-700 bg-ink-850/70 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Icon size={13} style={{ color: meta.color }} aria-hidden="true" />
          <h3 className="text-xs font-semibold text-slateish-100">{step.title}</h3>
          <Chip tone={LAYER_TONE[step.layer] ?? 'neutral'}>{step.layer}</Chip>
          <span className="text-2xs font-semibold uppercase" style={{ color: meta.color }}>
            {meta.label}
          </span>
          <span className="tnum ml-auto font-mono text-[9.5px] text-slateish-400/70">
            {step.duration_ms}ms
          </span>
        </div>

        <p className="mt-1.5 text-2xs leading-relaxed text-slateish-300">{step.summary}</p>

        {detailEntries.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-[9.5px] font-semibold uppercase tracking-wide text-slateish-400 hover:text-slateish-200">
              Evidence ({detailEntries.length})
            </summary>
            <div className="mt-1.5 grid gap-x-4 gap-y-1 border-t border-ink-800 pt-1.5 sm:grid-cols-2">
              {detailEntries.map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <p className="text-[9.5px] uppercase tracking-wide text-slateish-400">
                    {humanise(key)}
                  </p>
                  <p className="tnum break-words font-mono text-[10px] text-slateish-200">
                    <DetailValue value={value} />
                  </p>
                </div>
              ))}
            </div>
          </details>
        )}

        {step.route && (
          <Link
            to={step.route}
            className="mt-2 inline-flex items-center gap-1 text-2xs font-medium text-info hover:underline"
          >
            Verify this yourself <ArrowRight size={11} aria-hidden="true" />
          </Link>
        )}
      </div>
    </li>
  )
}

export default function DemoPage() {
  const toast = useToast()
  const scenarios = useApi(() => api.demoScenarios(), [])
  const [scenario, setScenario] = useState('LAYERED_RING')
  const [result, setResult] = useState(null)

  const run = useMutation(async (key) => {
    const payload = await api.runDemo({ scenario: key })
    setResult(payload)
    const outcome = payload.outcome?.status
    if (outcome === 'BLOCKED_AT_INTEGRITY') {
      toast.error('Walkthrough finished: the payment was blocked at the integrity gate.', {
        title: 'Demo complete',
      })
    } else if (outcome === 'COMPLETED') {
      toast.success(
        `Walkthrough finished: case ${payload.outcome.case_ref} opened from alert ${payload.outcome.alert_ref}.`,
        { title: 'Demo complete' },
      )
    } else {
      toast.info('Walkthrough finished.', { title: 'Demo complete' })
    }
    return payload
  })

  const available = scenarios.data?.scenarios ?? []

  return (
    <>
      <PageHeader
        icon={PlayCircle}
        title="Run AML Demo"
        subtitle="Executes the full surveillance narrative end to end against the live database — integrity gate, proactive scoring, settlement, reactive monitoring, graph construction, GNN detection, alert, case file and investigator note."
      >
        {result && (
          <Button
            variant="ghost"
            icon={RotateCcw}
            onClick={() => setResult(null)}
            disabled={run.pending}
          >
            Reset
          </Button>
        )}
      </PageHeader>

      {/* ------------------------------------------------- scenario chooser */}
      <div className="mb-4 grid gap-3 md:grid-cols-2">
        {(available.length
          ? available
          : [
              {
                key: 'LAYERED_RING',
                label: 'Layered movement network',
                description:
                  'A legitimate-looking retail payment clears, then reactive monitoring and the graph engine surface a laundering structure.',
              },
              {
                key: 'TAMPERED_AMOUNT',
                label: 'Payment tampering attempt',
                description:
                  'A client submits an inflated amount. The integrity gateway blocks it using the server-authorised value.',
              },
            ]
        ).map((item) => (
          <Card
            key={item.key}
            className={clsx(
              'cursor-pointer transition-colors',
              scenario === item.key
                ? 'border-info/50 ring-1 ring-info/25'
                : 'hover:border-ink-600',
            )}
            onClick={() => setScenario(item.key)}
          >
            <div className="flex items-start gap-2.5">
              <input
                type="radio"
                checked={scenario === item.key}
                onChange={() => setScenario(item.key)}
                className="mt-0.5 h-3 w-3 accent-info"
                aria-label={item.label}
              />
              <div className="min-w-0">
                <h3 className="text-xs font-semibold text-slateish-100">{item.label}</h3>
                <p className="mt-1 text-2xs leading-snug text-slateish-400">{item.description}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          icon={PlayCircle}
          loading={run.pending}
          onClick={() => run.run(scenario).catch(() => {})}
        >
          {run.pending ? 'Running walkthrough…' : 'Run AML demo'}
        </Button>
        <p className="text-2xs text-slateish-400">
          This performs real writes: it settles or holds a payment, raises alerts, rebuilds the
          graph and opens a case.
        </p>
      </div>

      {run.error && (
        <Card className="mb-4 border-risk-high/40 bg-risk-highBg">
          <p className="text-xs text-risk-high">{run.error.message}</p>
        </Card>
      )}

      {run.pending && (
        <Card>
          <div className="flex flex-col items-center justify-center gap-3 py-14 text-slateish-400">
            <Spinner size={24} />
            <p className="text-xs">
              Running the pipeline: integrity → proactive → settlement → reactive → graph → GNN →
              alert → investigation…
            </p>
          </div>
        </Card>
      )}

      {!result && !run.pending && (
        <Card>
          <EmptyState
            icon={PlayCircle}
            title="No walkthrough run yet"
            message="Pick a scenario and run the demo. Each step will show the evidence it produced and link to the page where you can verify it independently."
          />
        </Card>
      )}

      {result && (
        <div className="space-y-4">
          {/* --------------------------------------------------- outcome bar */}
          <Card>
            <CardHeader
              title="Walkthrough outcome"
              subtitle={`${result.run_ref} · ${result.scenario} · ${formatDateTime(result.started_at)}`}
              action={
                <Chip
                  tone={
                    result.outcome?.status === 'COMPLETED'
                      ? 'low'
                      : result.outcome?.status === 'BLOCKED_AT_INTEGRITY'
                        ? 'critical'
                        : 'medium'
                  }
                >
                  {humanise(result.outcome?.status ?? 'unknown')}
                </Chip>
              }
            />
            <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(result.outcome ?? {})
                .filter(([key]) => key !== 'status')
                .map(([key, value]) => {
                  const isRef = typeof value === 'string' && /^(ALERT|CASE|NET|TXN|ORD)-/.test(value)
                  const route = isRef
                    ? value.startsWith('ALERT-')
                      ? `/alerts/${value}`
                      : value.startsWith('CASE-')
                        ? `/investigations/${value}`
                        : value.startsWith('NET-')
                          ? `/network?network=${value}`
                          : value.startsWith('TXN-')
                            ? `/transactions?search=${value}`
                            : null
                    : null
                  return (
                    <div key={key} className="border-b border-ink-800/70 py-1">
                      <p className="text-2xs text-slateish-400">{humanise(key)}</p>
                      <p className="tnum font-mono text-xs text-slateish-100">
                        {route ? (
                          <Link to={route} className="text-info hover:underline">
                            {value}
                          </Link>
                        ) : typeof value === 'number' ? (
                          value.toLocaleString('en-IN')
                        ) : (
                          String(value)
                        )}
                      </p>
                    </div>
                  )
                })}
            </div>
          </Card>

          {/* ---------------------------------------------------- step list */}
          <Card>
            <CardHeader
              title="Pipeline walkthrough"
              subtitle={`${result.steps.length} steps executed against the live database`}
            />
            <ol className="mt-1">
              {result.steps.map((step) => (
                <StepCard key={`${step.index}-${step.key}`} step={step} />
              ))}
            </ol>
          </Card>

          <Advisory tone="warning">{result.advisory}</Advisory>
        </div>
      )}
    </>
  )
}
