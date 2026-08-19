import { ArrowRight, Lock, ScrollText, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import {
  Advisory,
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  PageHeader,
  Pagination,
  SearchInput,
  Select,
  SkeletonTable,
  Table,
  Td,
  Th,
  Tr,
} from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useApi, useDebounced } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatNumber, humanise } from '../utils/format.js'

const ACTION_TONE = (action) => {
  if (action.includes('BLOCKED') || action.includes('FAILED')) return 'critical'
  if (action.includes('ESCALAT')) return 'high'
  if (action.includes('CREATED') || action.includes('SUCCEEDED')) return 'low'
  if (action.includes('CHANGED') || action.includes('UPDATED')) return 'medium'
  return 'neutral'
}

export default function AuditLogsPage() {
  const { can } = useAuth()
  const [search, setSearch] = useState('')
  const debounced = useDebounced(search, 350)
  const [action, setAction] = useState('')
  const [resourceType, setResourceType] = useState('')
  const [page, setPage] = useState(1)

  const facets = useApi(() => api.auditFacets(), [], { enabled: can('audit:read') })

  useEffect(() => setPage(1), [debounced, action, resourceType])

  const query = useMemo(
    () => ({
      search: debounced || undefined,
      action: action || undefined,
      resource_type: resourceType || undefined,
      page,
      page_size: 60,
    }),
    [debounced, action, resourceType, page],
  )

  const { data, error, loading, reload } = useApi(
    (signal) => api.auditLogs(query, signal),
    [query],
    { enabled: can('audit:read') },
  )

  if (!can('audit:read')) {
    return (
      <>
        <PageHeader icon={ScrollText} title="Audit Logs" />
        <Card>
          <EmptyState
            icon={Lock}
            title="Administrator access required"
            message="Audit logs record who changed what and when. Only the ADMIN role may read them, and the restriction is enforced server-side — not by hiding this page."
          />
        </Card>
      </>
    )
  }

  const activeFilters = [action, resourceType].filter(Boolean).length + (debounced ? 1 : 0)

  return (
    <>
      <PageHeader
        icon={ScrollText}
        title="Audit Logs"
        subtitle="Append-only record of every state change: sign-ins, gateway decisions, alert transitions, case notes and rule edits. Rows are never updated or deleted."
      >
        {data && (
          <span className="tnum font-mono text-2xs text-slateish-400">
            {formatNumber(data.total)} entries
          </span>
        )}
      </PageHeader>

      <Card padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-3">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Actor, resource or detail…"
            className="w-full sm:w-64"
            aria-label="Search audit log"
          />
          <Select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            options={[
              { value: '', label: 'All actions' },
              ...(facets.data?.actions ?? []).map((a) => ({ value: a, label: humanise(a) })),
            ]}
            aria-label="Filter by action"
          />
          <Select
            value={resourceType}
            onChange={(e) => setResourceType(e.target.value)}
            options={[
              { value: '', label: 'All resource types' },
              ...(facets.data?.resource_types ?? []).map((r) => ({
                value: r,
                label: humanise(r),
              })),
            ]}
            aria-label="Filter by resource type"
          />
          {activeFilters > 0 && (
            <Button
              size="xs"
              variant="ghost"
              icon={X}
              onClick={() => {
                setSearch('')
                setAction('')
                setResourceType('')
              }}
            >
              Clear {activeFilters}
            </Button>
          )}
        </div>

        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !error && <SkeletonTable rows={12} cols={7} />}
        {!loading && !error && data?.items?.length === 0 && (
          <EmptyState icon={ScrollText} title="No audit entries match these filters" />
        )}

        {!loading && !error && data?.items?.length > 0 && (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Timestamp</Th>
                  <Th>User</Th>
                  <Th>Action</Th>
                  <Th>Resource</Th>
                  <Th>State change</Th>
                  <Th>Detail</Th>
                  <Th>IP / session</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((entry) => (
                  <Tr key={entry.id}>
                    <Td mono className="text-slateish-400">
                      {formatDateTime(entry.occurred_at)}
                    </Td>
                    <Td>
                      <span className="block font-medium text-slateish-100">{entry.actor}</span>
                      <span className="block text-2xs text-slateish-400">{entry.actor_role}</span>
                    </Td>
                    <Td>
                      <Chip tone={ACTION_TONE(entry.action)}>{humanise(entry.action)}</Chip>
                    </Td>
                    <Td>
                      <span className="block text-2xs text-slateish-400">
                        {entry.resource_type}
                      </span>
                      <span className="tnum block font-mono text-2xs text-slateish-200">
                        {entry.resource_ref}
                      </span>
                    </Td>
                    <Td>
                      {entry.previous_state || entry.new_state ? (
                        <span className="inline-flex items-center gap-1 text-2xs">
                          <span className="text-slateish-400">{entry.previous_state ?? '—'}</span>
                          <ArrowRight size={10} className="text-slateish-400/60" aria-hidden="true" />
                          <span className="font-medium text-slateish-100">
                            {entry.new_state ?? '—'}
                          </span>
                        </span>
                      ) : (
                        <span className="text-slateish-400/50">—</span>
                      )}
                    </Td>
                    <Td className="max-w-[340px] whitespace-normal text-2xs leading-snug text-slateish-400">
                      {entry.detail}
                    </Td>
                    <Td mono className="text-2xs text-slateish-400">
                      {entry.ip_address}
                      {entry.session_id && (
                        <span className="block opacity-60">{entry.session_id.slice(0, 12)}</span>
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
        The actor on every row is taken from the verified session token, never from the request
        body, so a client cannot attribute an action to someone else.
      </Advisory>
    </>
  )
}
