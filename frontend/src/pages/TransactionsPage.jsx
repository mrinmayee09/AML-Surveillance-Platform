import { Activity, AlertTriangle, ExternalLink, Filter, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  Chip,
  DataList,
  Drawer,
  EmptyState,
  ErrorState,
  FactorList,
  PageHeader,
  Pagination,
  RiskBadge,
  ScoreMeter,
  SearchInput,
  Select,
  SkeletonTable,
  StatusBadge,
  Table,
  Td,
  Th,
  Tr,
} from '../components/ui.jsx'
import { useApi, useDebounced } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import {
  formatDateTime,
  formatInr,
  formatInrExact,
  formatMultiple,
  formatNumber,
} from '../utils/format.js'

const RISK_OPTIONS = [
  { value: '', label: 'All risk bands' },
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]
const CHANNEL_OPTIONS = [
  { value: '', label: 'All channels' },
  ...['UPI', 'NEFT', 'IMPS', 'RTGS', 'CARD', 'WALLET', 'SWIFT', 'CASH'].map((c) => ({
    value: c,
    label: c,
  })),
]
const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  ...['COMPLETED', 'PENDING', 'HELD', 'BLOCKED', 'REVERSED'].map((s) => ({
    value: s,
    label: s.charAt(0) + s.slice(1).toLowerCase(),
  })),
]
const ALERT_OPTIONS = [
  { value: '', label: 'Alert: any' },
  { value: 'true', label: 'With alert' },
  { value: 'false', label: 'Without alert' },
]

/* ------------------------------------------------------------------ drawer */

function TransactionDrawer({ txnRef, onClose }) {
  const { data, error, loading } = useApi((signal) => api.transaction(txnRef, signal), [txnRef], {
    enabled: Boolean(txnRef),
  })

  return (
    <Drawer
      open={Boolean(txnRef)}
      onClose={onClose}
      title={txnRef ?? ''}
      subtitle={data ? `${data.txn_type} · ${data.channel} · ${formatDateTime(data.occurred_at)}` : 'Loading…'}
      footer={
        data && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-2xs text-slateish-400">
              Scored by the{' '}
              <strong className="text-slateish-200">{data.scored_by}</strong> layer
            </span>
            {data.sender_customer_ref && (
              <Link
                to={`/customers/${data.sender_customer_ref}`}
                className="inline-flex items-center gap-1 text-2xs font-medium text-info hover:underline"
              >
                Open sender profile <ExternalLink size={11} aria-hidden="true" />
              </Link>
            )}
          </div>
        )
      }
    >
      {loading && <SkeletonTable rows={7} cols={2} />}
      {error && <ErrorState error={error} />}
      {data && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge level={data.risk_level} score={data.risk_score} showScore />
            <StatusBadge status={data.status} />
            <Chip tone={data.integrity_status === 'VERIFIED' ? 'low' : 'critical'}>
              integrity: {data.integrity_status}
            </Chip>
            {data.has_alert && (
              <Chip tone="high">
                <AlertTriangle size={9} aria-hidden="true" /> alert raised
              </Chip>
            )}
            {data.is_suspicious_edge && <Chip tone="critical">flagged network edge</Chip>}
          </div>

          <ScoreMeter score={data.risk_score} level={data.risk_level} />

          <Card className="bg-ink-900/60">
            <DataList
              columns={2}
              items={[
                { label: 'Amount', value: formatInrExact(data.amount), mono: true },
                { label: 'Currency', value: data.currency },
                {
                  label: 'Sender',
                  value: (
                    <>
                      {data.sender_name}
                      <span className="block font-mono text-2xs text-slateish-400">
                        {data.sender_ref}
                      </span>
                    </>
                  ),
                },
                {
                  label: 'Receiver',
                  value: (
                    <>
                      {data.receiver_name}
                      <span className="block font-mono text-2xs text-slateish-400">
                        {data.receiver_ref}
                      </span>
                    </>
                  ),
                },
                { label: 'Channel', value: data.channel },
                { label: 'Type', value: data.txn_type },
                {
                  label: 'Location',
                  value: `${data.city}, ${data.country}${data.is_international ? ' (cross-border)' : ''}`,
                },
                { label: 'Decision', value: data.decision },
                { label: 'Order', value: data.order_ref ?? '—', mono: true },
                { label: 'Device', value: data.device_fingerprint ?? '—', mono: true },
                {
                  label: 'Network cluster',
                  value: data.network_ref ? (
                    <Link to={`/network?network=${data.network_ref}`} className="text-info hover:underline">
                      {data.network_ref}
                    </Link>
                  ) : (
                    '—'
                  ),
                },
                { label: 'Narrative', value: data.narrative ?? '—' },
              ]}
            />
          </Card>

          {/* The client-claimed amount, retained purely for forensic comparison */}
          {data.claimed_amount !== null && data.claimed_amount !== undefined && (
            <Card
              className={
                Math.abs(data.claimed_amount - data.amount) > 0.01
                  ? 'border-risk-critical/40 bg-risk-criticalBg'
                  : 'bg-ink-900/60'
              }
            >
              <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                Integrity comparison
              </h3>
              <DataList
                columns={2}
                items={[
                  {
                    label: 'Server-authorised (settled)',
                    value: formatInrExact(data.amount),
                    mono: true,
                  },
                  {
                    label: 'Client-claimed',
                    value: formatInrExact(data.claimed_amount),
                    mono: true,
                  },
                ]}
              />
              <p className="mt-2 text-2xs leading-snug text-slateish-400">
                The settled amount always comes from the server-side order record. The claimed
                value is stored only so a mismatch can be investigated.
              </p>
            </Card>
          )}

          {data.peer_context && Object.keys(data.peer_context).length > 0 && (
            <Card className="bg-ink-900/60">
              <h3 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                Peer context
              </h3>
              <DataList
                columns={2}
                items={[
                  {
                    label: "Sender's average",
                    value: formatInr(data.peer_context.sender_avg_amount),
                    mono: true,
                  },
                  {
                    label: 'vs sender average',
                    value: data.peer_context.ratio_to_sender_avg
                      ? formatMultiple(data.peer_context.ratio_to_sender_avg)
                      : '—',
                    mono: true,
                  },
                  {
                    label: 'Channel average',
                    value: formatInr(data.peer_context.channel_avg_amount),
                    mono: true,
                  },
                  {
                    label: 'vs channel average',
                    value: data.peer_context.ratio_to_channel_avg
                      ? formatMultiple(data.peer_context.ratio_to_channel_avg)
                      : '—',
                    mono: true,
                  },
                  {
                    label: 'Model probability',
                    value:
                      data.peer_context.model_probability !== null &&
                      data.peer_context.model_probability !== undefined
                        ? data.peer_context.model_probability.toFixed(4)
                        : '—',
                    mono: true,
                  },
                  { label: 'Assessment', value: data.peer_context.assessment_ref ?? '—', mono: true },
                ]}
              />
            </Card>
          )}

          {data.triggered_rules?.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                Rules triggered
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {data.triggered_rules.map((code) => (
                  <Chip key={code} tone="medium">
                    {code}
                  </Chip>
                ))}
              </div>
            </div>
          )}

          {data.risk_factors?.length > 0 && (
            <Card className="bg-ink-900/60">
              <FactorList factors={data.risk_factors} total={data.risk_score} />
            </Card>
          )}

          <Advisory>
            A risk score is a prioritisation signal for human review. It does not establish that
            any offence occurred.
          </Advisory>
        </div>
      )}
    </Drawer>
  )
}

/* -------------------------------------------------------------------- page */

export default function TransactionsPage() {
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('search') ?? '')
  const debouncedSearch = useDebounced(search, 350)

  const [riskLevel, setRiskLevel] = useState('')
  const [channel, setChannel] = useState('')
  const [status, setStatus] = useState('')
  const [hasAlert, setHasAlert] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [minAmount, setMinAmount] = useState('')
  const [sortBy, setSortBy] = useState('occurred_at')
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState(null)

  const customerRef = params.get('customer') ?? ''

  // Any filter change resets pagination
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, riskLevel, channel, status, hasAlert, dateFrom, dateTo, minAmount, customerRef])

  const query = useMemo(
    () => ({
      search: debouncedSearch || undefined,
      risk_level: riskLevel || undefined,
      channel: channel || undefined,
      status: status || undefined,
      has_alert: hasAlert || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      min_amount: minAmount || undefined,
      customer_ref: customerRef || undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
      page,
      page_size: 50,
    }),
    [
      debouncedSearch,
      riskLevel,
      channel,
      status,
      hasAlert,
      dateFrom,
      dateTo,
      minAmount,
      customerRef,
      sortBy,
      sortDir,
      page,
    ],
  )

  const { data, error, loading, reload } = useApi(
    (signal) => api.transactions(query, signal),
    [query],
  )

  function toggleSort(field) {
    if (sortBy === field) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortBy(field)
      setSortDir('desc')
    }
  }

  const activeFilters =
    [riskLevel, channel, status, hasAlert, dateFrom, dateTo, minAmount, customerRef].filter(Boolean)
      .length + (debouncedSearch ? 1 : 0)

  function clearFilters() {
    setSearch('')
    setRiskLevel('')
    setChannel('')
    setStatus('')
    setHasAlert('')
    setDateFrom('')
    setDateTo('')
    setMinAmount('')
    if (customerRef) {
      params.delete('customer')
      setParams(params)
    }
  }

  return (
    <>
      <PageHeader
        icon={Activity}
        title="Transactions"
        subtitle="Every settled and held transaction screened by the platform. Click a row for the full assessment."
      >
        {data && (
          <span className="tnum font-mono text-2xs text-slateish-400">
            {formatNumber(data.total)} records
          </span>
        )}
      </PageHeader>

      <Card padded={false} className="overflow-hidden">
        {/* -------------------------------------------------------- filters */}
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-3">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Transaction ref, account or name…"
            className="w-full sm:w-64"
            aria-label="Search transactions"
          />
          <Select
            value={riskLevel}
            onChange={(e) => setRiskLevel(e.target.value)}
            options={RISK_OPTIONS}
            aria-label="Filter by risk band"
          />
          <Select
            value={channel}
            onChange={(e) => setChannel(e.target.value)}
            options={CHANNEL_OPTIONS}
            aria-label="Filter by channel"
          />
          <Select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            options={STATUS_OPTIONS}
            aria-label="Filter by status"
          />
          <Select
            value={hasAlert}
            onChange={(e) => setHasAlert(e.target.value)}
            options={ALERT_OPTIONS}
            aria-label="Filter by alert presence"
          />
          <label className="flex items-center gap-1.5 text-2xs text-slateish-400">
            from
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded border border-ink-600 bg-ink-900 px-1.5 py-1 text-2xs text-slateish-100"
              aria-label="From date"
            />
          </label>
          <label className="flex items-center gap-1.5 text-2xs text-slateish-400">
            to
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="rounded border border-ink-600 bg-ink-900 px-1.5 py-1 text-2xs text-slateish-100"
              aria-label="To date"
            />
          </label>
          <label className="flex items-center gap-1.5 text-2xs text-slateish-400">
            min ₹
            <input
              type="number"
              min="0"
              value={minAmount}
              onChange={(e) => setMinAmount(e.target.value)}
              className="w-24 rounded border border-ink-600 bg-ink-900 px-1.5 py-1 text-2xs text-slateish-100"
              aria-label="Minimum amount"
            />
          </label>

          {activeFilters > 0 && (
            <Button size="xs" variant="ghost" icon={X} onClick={clearFilters}>
              Clear {activeFilters}
            </Button>
          )}
        </div>

        {customerRef && (
          <div className="flex items-center gap-2 border-b border-ink-800 bg-info-soft px-3 py-2">
            <Filter size={12} className="text-info" aria-hidden="true" />
            <span className="text-2xs text-slateish-200">
              Filtered to customer{' '}
              <Link to={`/customers/${customerRef}`} className="font-mono text-info hover:underline">
                {customerRef}
              </Link>
            </span>
          </div>
        )}

        {/* ---------------------------------------------------------- table */}
        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !error && <SkeletonTable rows={10} cols={9} />}
        {!loading && !error && data?.items?.length === 0 && (
          <EmptyState
            icon={Activity}
            title="No transactions match these filters"
            message="Try widening the date range or clearing the risk filter."
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
                  <Th>Transaction</Th>
                  <Th
                    sortable
                    active={sortBy === 'occurred_at'}
                    direction={sortDir}
                    onClick={() => toggleSort('occurred_at')}
                  >
                    Timestamp
                  </Th>
                  <Th>Sender</Th>
                  <Th>Receiver</Th>
                  <Th
                    align="right"
                    sortable
                    active={sortBy === 'amount'}
                    direction={sortDir}
                    onClick={() => toggleSort('amount')}
                  >
                    Amount
                  </Th>
                  <Th>Channel</Th>
                  <Th>Location</Th>
                  <Th
                    align="right"
                    sortable
                    active={sortBy === 'risk_score'}
                    direction={sortDir}
                    onClick={() => toggleSort('risk_score')}
                  >
                    Risk
                  </Th>
                  <Th>Status</Th>
                  <Th align="center">Alert</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((txn) => (
                  <Tr
                    key={txn.txn_ref}
                    onClick={() => setSelected(txn.txn_ref)}
                    selected={selected === txn.txn_ref}
                  >
                    <Td mono className="text-slateish-300">
                      {txn.txn_ref}
                    </Td>
                    <Td mono className="text-slateish-400">
                      {formatDateTime(txn.occurred_at)}
                    </Td>
                    <Td>
                      <span className="block max-w-[150px] truncate">{txn.sender_name}</span>
                      <span className="tnum block font-mono text-2xs text-slateish-400">
                        {txn.sender_ref}
                      </span>
                    </Td>
                    <Td>
                      <span className="block max-w-[150px] truncate">{txn.receiver_name}</span>
                      <span className="tnum block font-mono text-2xs text-slateish-400">
                        {txn.receiver_ref}
                      </span>
                    </Td>
                    <Td align="right" mono className="font-medium text-slateish-100">
                      {formatInr(txn.amount)}
                    </Td>
                    <Td>
                      <Chip tone="neutral">{txn.channel}</Chip>
                    </Td>
                    <Td className="text-slateish-400">
                      {txn.city}
                      {txn.is_international && (
                        <span className="ml-1 text-2xs text-risk-medium">intl</span>
                      )}
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1.5">
                        <span className="tnum font-mono text-slateish-100">
                          {Math.round(txn.risk_score)}
                        </span>
                        <RiskBadge level={txn.risk_level} size="xs" />
                      </div>
                    </Td>
                    <Td>
                      <StatusBadge status={txn.status} />
                    </Td>
                    <Td align="center">
                      {txn.has_alert ? (
                        <AlertTriangle
                          size={13}
                          className="inline text-risk-high"
                          aria-label="Alert raised"
                        />
                      ) : (
                        <span className="text-slateish-400/40" aria-label="No alert">
                          —
                        </span>
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

      <TransactionDrawer txnRef={selected} onClose={() => setSelected(null)} />
    </>
  )
}
