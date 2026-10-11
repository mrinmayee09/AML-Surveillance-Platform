import { BellRing, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  RiskBadge,
  SearchInput,
  Select,
  SkeletonTable,
  StatusBadge,
  Table,
  Td,
  Th,
  Tr,
} from '../components/ui.jsx'
import { ALERTS_CHANGED_EVENT, useApi, useDebounced } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatNumber, humanise } from '../utils/format.js'

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'NEW', label: 'New' },
  { value: 'UNDER_REVIEW', label: 'Under review' },
  { value: 'ESCALATED', label: 'Escalated' },
  { value: 'CLEARED', label: 'Cleared' },
  { value: 'CONFIRMED_SUSPICIOUS', label: 'Confirmed suspicious' },
]
const SOURCE_OPTIONS = [
  { value: '', label: 'All layers' },
  { value: 'INTEGRITY', label: 'Transaction integrity' },
  { value: 'PROACTIVE', label: 'Proactive (pre-transaction)' },
  { value: 'REACTIVE', label: 'Reactive (post-settlement)' },
  { value: 'NETWORK', label: 'Network (graph + GNN)' },
]
const RISK_OPTIONS = [
  { value: '', label: 'All risk bands' },
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]

export default function AlertsPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [search, setSearch] = useState('')
  const debounced = useDebounced(search, 350)
  const [status, setStatus] = useState(params.get('status') ?? '')
  const [source, setSource] = useState(params.get('source') ?? '')
  const [riskLevel, setRiskLevel] = useState('')
  const [page, setPage] = useState(1)

  useEffect(() => setPage(1), [debounced, status, source, riskLevel])

  const query = useMemo(
    () => ({
      search: debounced || undefined,
      status: status || undefined,
      source: source || undefined,
      risk_level: riskLevel || undefined,
      page,
      page_size: 50,
    }),
    [debounced, status, source, riskLevel, page],
  )

  const { data, error, loading, reload } = useApi((signal) => api.alerts(query, signal), [query], {
    refetchOn: ALERTS_CHANGED_EVENT,
    refetchOnFocus: true,
  })
  const stats = useApi((signal) => api.alertStats(signal), [], {
    refetchOn: ALERTS_CHANGED_EVENT,
    refetchOnFocus: true,
  })

  const activeFilters = [status, source, riskLevel].filter(Boolean).length + (debounced ? 1 : 0)

  function clearFilters() {
    setSearch('')
    setStatus('')
    setSource('')
    setRiskLevel('')
  }

  return (
    <>
      <PageHeader
        icon={BellRing}
        title="Alerts"
        subtitle="Every alert raised by the integrity, proactive, reactive and network layers. Alerts indicate activity requiring investigation."
      >
        {data && (
          <span className="tnum font-mono text-2xs text-slateish-400">
            {formatNumber(data.total)} alerts
          </span>
        )}
      </PageHeader>

      {/* -------------------------------------------------------- status tiles */}
      {stats.data && (
        <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Card>
            <p className="text-2xs uppercase tracking-wide text-slateish-400">Open</p>
            <p className="tnum mt-1 font-mono text-lg font-semibold text-risk-high">
              {formatNumber(stats.data.open_total)}
            </p>
          </Card>
          {Object.entries(stats.data.by_status ?? {}).map(([key, count]) => (
            <button
              key={key}
              type="button"
              onClick={() => setStatus(status === key ? '' : key)}
              className={`rounded-card border p-4 text-left transition-colors ${
                status === key
                  ? 'border-info/50 bg-info-soft'
                  : 'border-ink-700/70 bg-ink-850/80 hover:bg-ink-800'
              }`}
            >
              <p className="text-2xs uppercase tracking-wide text-slateish-400">
                {humanise(key)}
              </p>
              <p className="tnum mt-1 font-mono text-lg font-semibold text-slateish-100">
                {formatNumber(count)}
              </p>
            </button>
          ))}
        </div>
      )}

      <Card padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-3">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Alert ref, title or customer…"
            className="w-full sm:w-64"
            aria-label="Search alerts"
          />
          <Select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            options={STATUS_OPTIONS}
            aria-label="Filter by status"
          />
          <Select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            options={SOURCE_OPTIONS}
            aria-label="Filter by detection layer"
          />
          <Select
            value={riskLevel}
            onChange={(e) => setRiskLevel(e.target.value)}
            options={RISK_OPTIONS}
            aria-label="Filter by risk band"
          />
          {activeFilters > 0 && (
            <Button size="xs" variant="ghost" icon={X} onClick={clearFilters}>
              Clear {activeFilters}
            </Button>
          )}
        </div>

        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !error && <SkeletonTable rows={10} cols={8} />}
        {!loading && !error && data?.items?.length === 0 && (
          <EmptyState
            icon={BellRing}
            title="No alerts match these filters"
            action={
              activeFilters > 0 ? (
                <Button variant="secondary" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : null
            }
          />
        )}

        {!loading && !error && data?.items?.length > 0 && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Alert</Th>
                  <Th>Layer</Th>
                  <Th>Type</Th>
                  <Th>Customer</Th>
                  <Th align="right">Risk</Th>
                  <Th>Created</Th>
                  <Th>Status</Th>
                  <Th>Assigned investigator</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((alert) => (
                  <Tr
                    key={alert.alert_ref}
                    onClick={() => navigate(`/alerts/${alert.alert_ref}`)}
                  >
                    <Td mono className="text-slateish-300">
                      {alert.alert_ref}
                    </Td>
                    <Td>
                      <Chip
                        tone={
                          alert.source === 'NETWORK'
                            ? 'accent'
                            : alert.source === 'INTEGRITY'
                              ? 'critical'
                              : alert.source === 'PROACTIVE'
                                ? 'info'
                                : 'neutral'
                        }
                      >
                        {alert.source}
                      </Chip>
                    </Td>
                    <Td className="max-w-[190px] truncate text-slateish-200">
                      {humanise(alert.alert_type)}
                    </Td>
                    <Td>
                      {alert.customer_ref ? (
                        <>
                          <span className="block max-w-[140px] truncate">
                            {alert.customer_name}
                          </span>
                          <span className="tnum block font-mono text-2xs text-slateish-400">
                            {alert.customer_ref}
                          </span>
                        </>
                      ) : alert.network_ref ? (
                        <span className="tnum font-mono text-2xs text-accent">
                          {alert.network_ref}
                        </span>
                      ) : (
                        <span className="text-slateish-400">—</span>
                      )}
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1.5">
                        <span className="tnum font-mono text-slateish-100">
                          {Math.round(alert.risk_score)}
                        </span>
                        <RiskBadge level={alert.risk_level} size="xs" />
                      </div>
                    </Td>
                    <Td mono className="text-slateish-400">
                      {formatDateTime(alert.raised_at)}
                    </Td>
                    <Td>
                      <StatusBadge status={alert.status} />
                    </Td>
                    <Td className="text-slateish-300">
                      {alert.assignee_name ?? (
                        <span className="text-slateish-400/60">unassigned</span>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={data.page}
              pages={data.pages}
              total={data.total}
              pageSize={data.page_size}
              onChange={setPage}
            />
          </>
        )}
      </Card>

      <Advisory className="mt-3">
        An alert means activity requires investigation under the institution&apos;s AML procedures.
        It is not a determination that an offence occurred, and it must never be communicated to a
        customer as an accusation.
      </Advisory>
    </>
  )
}
