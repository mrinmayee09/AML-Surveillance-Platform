/**
 * Reactive AML Monitoring.
 *
 * Post-settlement detection. Each finding is presented as a narrative card with
 * the concrete numbers behind it, because "17 transactions in 14 minutes" is what
 * an investigator can actually act on - not a bare score.
 */
import { ArrowRight, Filter, RefreshCw, Siren } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  PageHeader,
  RiskBadge,
  Select,
  Skeleton,
  StatusBadge,
} from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatRelative, humanise } from '../utils/format.js'

const PATTERN_INFO = {
  UNUSUAL_AMOUNT: {
    label: 'Unusual amount',
    question: 'Is this transaction far outside what this customer normally does?',
  },
  HIGH_VELOCITY: {
    label: 'High velocity',
    question: 'Were many transactions compressed into a very short window?',
  },
  RAPID_FUND_MOVEMENT: {
    label: 'Rapid movement of funds',
    question: 'Did value arrive and leave again almost immediately?',
  },
  MULTIPLE_COUNTERPARTIES: {
    label: 'Multiple counterparties',
    question: 'Did the payee network suddenly expand?',
  },
  BEHAVIOURAL_ANOMALY: {
    label: 'Behavioural anomaly',
    question: "Has the customer's whole transaction profile shifted?",
  },
}

function PatternCard({ card }) {
  const info = PATTERN_INFO[card.pattern_code] ?? {
    label: humanise(card.pattern_code),
    question: '',
  }

  return (
    <Card className="flex flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <Chip tone="accent">{info.label}</Chip>
        <RiskBadge level={card.risk_level} score={card.risk_score} showScore size="xs" />
        <StatusBadge status={card.status} />
        <span className="ml-auto shrink-0 text-2xs text-slateish-400">
          {formatRelative(card.raised_at)}
        </span>
      </div>

      {/* The headline is the finding in the analyst's own terms */}
      <p className="text-sm font-semibold leading-snug text-slateish-100">{card.headline}</p>

      {card.customer_ref && (
        <Link
          to={`/customers/${card.customer_ref}`}
          className="mt-1 inline-flex w-fit items-center gap-1 text-2xs text-info hover:underline"
        >
          {card.customer_name} ({card.customer_ref})
        </Link>
      )}

      {card.metrics?.length > 0 && (
        <div className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 rounded border border-ink-700 bg-ink-900/60 p-2.5 sm:grid-cols-4">
          {card.metrics.map((metric) => (
            <div key={metric.label}>
              <p className="text-[9.5px] uppercase tracking-wide text-slateish-400">
                {metric.label}
              </p>
              <p className="tnum mt-0.5 font-mono text-2xs font-medium text-slateish-100">
                {metric.value}
              </p>
            </div>
          ))}
        </div>
      )}

      <p className="mt-2.5 text-2xs leading-relaxed text-slateish-400">{card.explanation}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-800 pt-2.5">
        {card.transaction_refs?.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[9.5px] uppercase tracking-wide text-slateish-400">
              Evidence
            </span>
            {card.transaction_refs.slice(0, 4).map((ref) => (
              <Link
                key={ref}
                to={`/transactions?search=${ref}`}
                className="tnum rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[9.5px] text-info hover:bg-ink-750"
              >
                {ref}
              </Link>
            ))}
            {card.transaction_refs.length > 4 && (
              <span className="text-[9.5px] text-slateish-400">
                +{card.transaction_refs.length - 4} more
              </span>
            )}
          </div>
        )}
        <Link
          to={`/alerts/${card.alert_ref}`}
          className="ml-auto inline-flex items-center gap-1 text-2xs font-medium text-info hover:underline"
        >
          Open alert {card.alert_ref} <ArrowRight size={11} aria-hidden="true" />
        </Link>
      </div>
    </Card>
  )
}

export default function ReactiveAmlPage() {
  const toast = useToast()
  const { isAdmin } = useAuth()
  const [pattern, setPattern] = useState('')
  const { data, error, loading, reload } = useApi(
    (signal) => api.reactiveOverview({ limit: 60 }, signal),
    [],
  )

  const runSweep = useMutation(async () => {
    const result = await api.runReactiveSweep({ limit: 40 })
    toast.success(
      `Sweep complete: ${result.alerts_created} alert(s) raised across ${result.customers_scanned} customer(s).`,
      { title: 'Reactive monitoring' },
    )
    reload()
    return result
  })

  const patternOptions = useMemo(() => {
    const counts = data?.pattern_counts ?? {}
    return [
      { value: '', label: `All patterns (${Object.values(counts).reduce((a, b) => a + b, 0)})` },
      ...Object.entries(counts).map(([code, count]) => ({
        value: code,
        label: `${PATTERN_INFO[code]?.label ?? humanise(code)} (${count})`,
      })),
    ]
  }, [data])

  const cards = useMemo(() => {
    const all = data?.cards ?? []
    return pattern ? all.filter((c) => c.pattern_code === pattern) : all
  }, [data, pattern])

  return (
    <>
      <PageHeader
        icon={Siren}
        title="Reactive AML Monitoring"
        subtitle="Analyses transactions AFTER they settle, looking for laundering typologies in the customer's recent behaviour. Each finding carries the measurements behind it."
      >
        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={runSweep.pending}
          onClick={() => runSweep.run().catch(() => {})}
        >
          {runSweep.pending ? 'Sweeping…' : 'Run monitoring sweep'}
        </Button>
      </PageHeader>

      {error && <ErrorState error={error} onRetry={reload} />}

      {!error && (
        <div className="space-y-3">
          {/* ----------------------------------------------- detector legend */}
          <Card>
            <CardHeader
              title="What the reactive layer looks for"
              subtitle="Five detectors, each reading its threshold from the Rules Engine."
            />
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
              {Object.entries(PATTERN_INFO).map(([code, info]) => {
                const count = data?.pattern_counts?.[code] ?? 0
                return (
                  <button
                    key={code}
                    type="button"
                    onClick={() => setPattern(pattern === code ? '' : code)}
                    className={`rounded border p-2.5 text-left transition-colors ${
                      pattern === code
                        ? 'border-info/50 bg-info-soft'
                        : 'border-ink-700 bg-ink-900/60 hover:border-ink-600 hover:bg-ink-800'
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-2xs font-semibold text-slateish-100">
                        {info.label}
                      </span>
                      <span className="tnum font-mono text-2xs text-risk-medium">{count}</span>
                    </div>
                    <p className="mt-1 text-[9.5px] leading-snug text-slateish-400">
                      {info.question}
                    </p>
                  </button>
                )
              })}
            </div>
          </Card>

          {/* -------------------------------------------------- summary bar */}
          <div className="flex flex-wrap items-center gap-2">
            {loading ? (
              <Skeleton className="h-8 w-full" />
            ) : (
              <>
                <Chip tone="neutral">
                  window: {data?.window_label ?? '—'}
                </Chip>
                <Chip tone="info">{data?.total_alerts ?? 0} reactive alerts</Chip>
                <Chip tone="high">{data?.open_alerts ?? 0} still open</Chip>
                <span className="ml-auto flex items-center gap-2">
                  <Filter size={12} className="text-slateish-400" aria-hidden="true" />
                  <Select
                    value={pattern}
                    onChange={(e) => setPattern(e.target.value)}
                    options={patternOptions}
                    aria-label="Filter by pattern"
                  />
                </span>
              </>
            )}
          </div>

          {/* ------------------------------------------------------- cards */}
          {loading && (
            <div className="grid gap-3 xl:grid-cols-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Card key={i}>
                  <Skeleton className="h-40" />
                </Card>
              ))}
            </div>
          )}

          {!loading && cards.length === 0 && (
            <Card>
              <EmptyState
                icon={Siren}
                title="No reactive findings"
                message={
                  pattern
                    ? 'No alert matches this pattern. Clear the filter, or run a monitoring sweep.'
                    : 'Run a monitoring sweep to analyse settled transactions for laundering typologies.'
                }
                action={
                  <Button
                    variant="secondary"
                    icon={RefreshCw}
                    loading={runSweep.pending}
                    onClick={() => runSweep.run().catch(() => {})}
                  >
                    Run monitoring sweep
                  </Button>
                }
              />
            </Card>
          )}

          {!loading && cards.length > 0 && (
            <div className="grid gap-3 xl:grid-cols-2">
              {cards.map((card) => (
                <PatternCard key={card.alert_ref} card={card} />
              ))}
            </div>
          )}

          {data && <Advisory tone="warning">{data.advisory}</Advisory>}
        </div>
      )}
    </>
  )
}
