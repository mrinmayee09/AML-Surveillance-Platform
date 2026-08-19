import { FilePlus2, FileSearch, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  Modal,
  PageHeader,
  Pagination,
  RiskBadge,
  SearchInput,
  Select,
  SkeletonTable,
  StatusBadge,
  Table,
  Td,
  Textarea,
  Th,
  Tr,
} from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useDebounced, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatNumber, humanise, scoreMeta } from '../utils/format.js'

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'OPEN', label: 'Open' },
  { value: 'IN_PROGRESS', label: 'In progress' },
  { value: 'PENDING_APPROVAL', label: 'Pending approval' },
  { value: 'CLOSED_CLEARED', label: 'Closed - cleared' },
  { value: 'CLOSED_REPORTED', label: 'Closed - reported' },
]
const PRIORITY_OPTIONS = [
  { value: '', label: 'Any priority' },
  { value: 'CRITICAL', label: 'Critical' },
  { value: 'HIGH', label: 'High' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'LOW', label: 'Low' },
]

export default function InvestigationsPage() {
  const navigate = useNavigate()
  const toast = useToast()
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()

  const [search, setSearch] = useState('')
  const debounced = useDebounced(search, 350)
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const [page, setPage] = useState(1)

  // Arriving from the network page with ?network=NET-000x opens the create modal
  const networkParam = params.get('network')
  const [createOpen, setCreateOpen] = useState(Boolean(networkParam))
  const [form, setForm] = useState({
    title: networkParam ? `Network investigation - ${networkParam}` : '',
    network_ref: networkParam ?? '',
    customer_ref: '',
    priority: 'MEDIUM',
    summary: '',
  })

  useEffect(() => setPage(1), [debounced, status, priority])

  const query = useMemo(
    () => ({
      search: debounced || undefined,
      status: status || undefined,
      priority: priority || undefined,
      page,
      page_size: 50,
    }),
    [debounced, status, priority, page],
  )

  const { data, error, loading, reload } = useApi(
    (signal) => api.investigations(query, signal),
    [query],
  )

  const create = useMutation(async () => {
    const investigation = await api.createInvestigation({
      title: form.title,
      network_ref: form.network_ref || undefined,
      customer_ref: form.customer_ref || undefined,
      priority: form.priority,
      summary: form.summary || undefined,
    })
    toast.success(`Case ${investigation.case_ref} opened.`)
    setCreateOpen(false)
    if (networkParam) {
      params.delete('network')
      setParams(params)
    }
    navigate(`/investigations/${investigation.case_ref}`)
  })

  const activeFilters = [status, priority].filter(Boolean).length + (debounced ? 1 : 0)

  return (
    <>
      <PageHeader
        icon={FileSearch}
        title="Investigations"
        subtitle="Case files aggregating alerts, transaction history, network structure and the model output behind them. Conclusions are recorded by human analysts."
      >
        {data && (
          <span className="tnum font-mono text-2xs text-slateish-400">
            {formatNumber(data.total)} cases
          </span>
        )}
        {can('investigations:write') && (
          <Button variant="primary" icon={FilePlus2} onClick={() => setCreateOpen(true)}>
            Open case
          </Button>
        )}
      </PageHeader>

      <Card padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-3">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Case ref, title or customer…"
            className="w-full sm:w-64"
            aria-label="Search investigations"
          />
          <Select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            options={STATUS_OPTIONS}
            aria-label="Filter by status"
          />
          <Select
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            options={PRIORITY_OPTIONS}
            aria-label="Filter by priority"
          />
          {activeFilters > 0 && (
            <Button
              size="xs"
              variant="ghost"
              icon={X}
              onClick={() => {
                setSearch('')
                setStatus('')
                setPriority('')
              }}
            >
              Clear {activeFilters}
            </Button>
          )}
        </div>

        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !error && <SkeletonTable rows={9} cols={8} />}
        {!loading && !error && data?.items?.length === 0 && (
          <EmptyState
            icon={FileSearch}
            title="No investigations"
            message="Open a case from an alert, or create one directly."
          />
        )}

        {!loading && !error && data?.items?.length > 0 && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Case</Th>
                  <Th>Title</Th>
                  <Th>Subject</Th>
                  <Th align="right">Risk</Th>
                  <Th>Priority</Th>
                  <Th>Status</Th>
                  <Th>Assignee</Th>
                  <Th align="right">Notes</Th>
                  <Th>Opened</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <Tr key={row.case_ref} onClick={() => navigate(`/investigations/${row.case_ref}`)}>
                    <Td mono className="text-slateish-300">
                      {row.case_ref}
                    </Td>
                    <Td className="max-w-[260px] truncate text-slateish-100">{row.title}</Td>
                    <Td>
                      {row.customer_ref ? (
                        <>
                          <span className="block max-w-[130px] truncate">{row.customer_name}</span>
                          <span className="tnum block font-mono text-2xs text-slateish-400">
                            {row.customer_ref}
                          </span>
                        </>
                      ) : row.network_ref ? (
                        <span className="tnum font-mono text-2xs text-accent">
                          {row.network_ref}
                        </span>
                      ) : (
                        <span className="text-slateish-400">—</span>
                      )}
                    </Td>
                    <Td align="right">
                      <RiskBadge
                        level={scoreMeta(row.risk_score).level}
                        score={row.risk_score}
                        showScore
                        size="xs"
                      />
                    </Td>
                    <Td>
                      <Chip
                        tone={
                          row.priority === 'CRITICAL'
                            ? 'critical'
                            : row.priority === 'HIGH'
                              ? 'high'
                              : row.priority === 'MEDIUM'
                                ? 'medium'
                                : 'neutral'
                        }
                      >
                        {row.priority}
                      </Chip>
                    </Td>
                    <Td>
                      <StatusBadge status={row.status} />
                    </Td>
                    <Td className="text-slateish-300">
                      {row.assignee_name ?? (
                        <span className="text-slateish-400/60">unassigned</span>
                      )}
                    </Td>
                    <Td align="right" mono className="text-slateish-400">
                      {row.note_count}
                    </Td>
                    <Td mono className="text-slateish-400">
                      {formatDateTime(row.opened_at)}
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
        A case file collects model- and rule-generated indicators. Any conclusion must be reached
        by a human investigator on the evidence and recorded as an explicit outcome.
      </Advisory>

      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Open investigation case"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={create.pending}
              disabled={form.title.trim().length < 4}
              onClick={() => create.run().catch(() => {})}
            >
              Open case
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
              Case title
            </label>
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="w-full rounded border border-ink-600 bg-ink-900 px-2.5 py-1.5 text-xs text-slateish-100 focus:border-info/60 focus:outline-none"
              placeholder="What is being investigated?"
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
                Customer ref
              </label>
              <input
                value={form.customer_ref}
                onChange={(e) => setForm({ ...form, customer_ref: e.target.value.toUpperCase() })}
                className="tnum w-full rounded border border-ink-600 bg-ink-900 px-2.5 py-1.5 font-mono text-xs text-slateish-100 focus:border-info/60 focus:outline-none"
                placeholder="CUST-1023"
              />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
                Network ref
              </label>
              <input
                value={form.network_ref}
                onChange={(e) => setForm({ ...form, network_ref: e.target.value.toUpperCase() })}
                className="tnum w-full rounded border border-ink-600 bg-ink-900 px-2.5 py-1.5 font-mono text-xs text-slateish-100 focus:border-info/60 focus:outline-none"
                placeholder="NET-0001"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
              Priority
            </label>
            <Select
              className="w-full"
              value={form.priority}
              onChange={(e) => setForm({ ...form, priority: e.target.value })}
              options={PRIORITY_OPTIONS.filter((o) => o.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
              Summary
            </label>
            <Textarea
              rows={3}
              value={form.summary}
              onChange={(e) => setForm({ ...form, summary: e.target.value })}
              placeholder="Scope, what prompted the case, what needs establishing…"
            />
          </div>
          {create.error && <p className="text-2xs text-risk-high">{create.error.message}</p>}
        </div>
      </Modal>
    </>
  )
}
