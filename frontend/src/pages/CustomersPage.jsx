import { ShieldAlert, Users, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

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
  Table,
  Td,
  Th,
  Tr,
  TrendIndicator,
} from '../components/ui.jsx'
import { useApi, useDebounced } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatMultiple, formatNumber } from '../utils/format.js'

const RISK_OPTIONS = [
  { value: '', label: 'All risk bands' },
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]
const TREND_OPTIONS = [
  { value: '', label: 'Any trend' },
  { value: 'INCREASING', label: 'Increasing' },
  { value: 'STABLE', label: 'Stable' },
  { value: 'DECREASING', label: 'Decreasing' },
]
const MONITOR_OPTIONS = [
  { value: '', label: 'All customers' },
  { value: 'true', label: 'Under monitoring' },
  { value: 'false', label: 'Not monitored' },
]

export default function CustomersPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const debounced = useDebounced(search, 350)
  const [riskLevel, setRiskLevel] = useState('')
  const [trend, setTrend] = useState('')
  const [monitored, setMonitored] = useState('')
  const [pepOnly, setPepOnly] = useState(false)
  const [sortBy, setSortBy] = useState('current_risk_score')
  const [sortDir, setSortDir] = useState('desc')
  const [page, setPage] = useState(1)

  useEffect(() => setPage(1), [debounced, riskLevel, trend, monitored, pepOnly])

  const query = useMemo(
    () => ({
      search: debounced || undefined,
      risk_level: riskLevel || undefined,
      trend: trend || undefined,
      monitored: monitored || undefined,
      pep_only: pepOnly || undefined,
      sort_by: sortBy,
      sort_dir: sortDir,
      page,
      page_size: 50,
    }),
    [debounced, riskLevel, trend, monitored, pepOnly, sortBy, sortDir, page],
  )

  const { data, error, loading, reload } = useApi(
    (signal) => api.customers(query, signal),
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
    [riskLevel, trend, monitored].filter(Boolean).length + (pepOnly ? 1 : 0) + (debounced ? 1 : 0)

  function clearFilters() {
    setSearch('')
    setRiskLevel('')
    setTrend('')
    setMonitored('')
    setPepOnly(false)
  }

  return (
    <>
      <PageHeader
        icon={Users}
        title="Customers"
        subtitle="Behavioural risk profile for every monitored customer. Scores are recomputed from each customer's own transaction history."
      >
        {data && (
          <span className="tnum font-mono text-2xs text-slateish-400">
            {formatNumber(data.total)} customers
          </span>
        )}
      </PageHeader>

      <Card padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-3">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, reference or city…"
            className="w-full sm:w-60"
            aria-label="Search customers"
          />
          <Select
            value={riskLevel}
            onChange={(e) => setRiskLevel(e.target.value)}
            options={RISK_OPTIONS}
            aria-label="Filter by risk band"
          />
          <Select
            value={trend}
            onChange={(e) => setTrend(e.target.value)}
            options={TREND_OPTIONS}
            aria-label="Filter by trend"
          />
          <Select
            value={monitored}
            onChange={(e) => setMonitored(e.target.value)}
            options={MONITOR_OPTIONS}
            aria-label="Filter by monitoring status"
          />
          <label className="flex items-center gap-1.5 text-2xs text-slateish-300">
            <input
              type="checkbox"
              checked={pepOnly}
              onChange={(e) => setPepOnly(e.target.checked)}
              className="h-3 w-3 rounded border-ink-600 bg-ink-900 accent-info"
            />
            PEP only
          </label>
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
            icon={Users}
            title="No customers match these filters"
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
                  <Th>Customer</Th>
                  <Th
                    sortable
                    active={sortBy === 'name'}
                    direction={sortDir}
                    onClick={() => toggleSort('name')}
                  >
                    Name
                  </Th>
                  <Th>Location</Th>
                  <Th
                    align="right"
                    sortable
                    active={sortBy === 'account_age_years'}
                    direction={sortDir}
                    onClick={() => toggleSort('account_age_years')}
                  >
                    Relationship
                  </Th>
                  <Th>KYC</Th>
                  <Th
                    align="right"
                    sortable
                    active={sortBy === 'current_risk_score'}
                    direction={sortDir}
                    onClick={() => toggleSort('current_risk_score')}
                  >
                    Risk score
                  </Th>
                  <Th>Trend</Th>
                  <Th align="right">Prior alerts</Th>
                  <Th align="center">Monitoring</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((customer) => (
                  <Tr
                    key={customer.customer_ref}
                    onClick={() => navigate(`/customers/${customer.customer_ref}`)}
                  >
                    <Td mono className="text-slateish-300">
                      {customer.customer_ref}
                    </Td>
                    <Td className="font-medium text-slateish-100">
                      <span className="flex items-center gap-1.5">
                        {customer.name}
                        {customer.pep_flag && (
                          <Chip tone="medium" title="Politically exposed person">
                            PEP
                          </Chip>
                        )}
                      </span>
                    </Td>
                    <Td className="text-slateish-400">
                      {customer.city}, {customer.country}
                    </Td>
                    <Td align="right" mono className="text-slateish-300">
                      {customer.account_age_years.toFixed(1)} yr
                    </Td>
                    <Td>
                      <Chip tone={customer.kyc_level === 'FULL' ? 'low' : 'medium'}>
                        {customer.kyc_level}
                      </Chip>
                    </Td>
                    <Td align="right">
                      <div className="flex items-center justify-end gap-1.5">
                        <span className="tnum font-mono font-medium text-slateish-100">
                          {Math.round(customer.current_risk_score)}
                        </span>
                        <RiskBadge level={customer.current_risk_level} size="xs" />
                      </div>
                    </Td>
                    <Td>
                      <TrendIndicator trend={customer.risk_trend} />
                    </Td>
                    <Td align="right" mono className="text-slateish-300">
                      {customer.previous_alert_count}
                    </Td>
                    <Td align="center">
                      {customer.under_monitoring ? (
                        <ShieldAlert
                          size={13}
                          className="inline text-risk-medium"
                          aria-label="Under enhanced monitoring"
                        />
                      ) : (
                        <span className="text-slateish-400/40" aria-label="Not monitored">
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

      <Advisory className="mt-3">
        A customer&apos;s risk band reflects behavioural signals measured against their own
        history. It indicates review priority under the institution&apos;s AML procedures and is
        never a statement that the customer has committed an offence.
      </Advisory>
    </>
  )
}
