/**
 * Investigation workspace.
 *
 * Everything an analyst needs in one place: the alert, transaction history, the
 * network graph, the explained risk factors, the model output, their own notes,
 * and a merged timeline. Every mutation writes both a case note and an audit row.
 */
import {
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  FileSearch,
  MessageSquarePlus,
  Network,
  ShieldAlert,
  User,
  UserPlus,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  KeyValue,
  Modal,
  PageHeader,
  RiskBadge,
  Select,
  Skeleton,
  StatusBadge,
  Table,
  Td,
  Textarea,
  Th,
  Tr,
} from '../components/ui.jsx'
import NetworkGraph, { GraphLegend } from '../graph/NetworkGraph.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import {
  formatDateTime,
  formatInr,
  formatRelative,
  humanise,
  scoreMeta,
} from '../utils/format.js'

const STATUS_ACTIONS = [
  { status: 'IN_PROGRESS', label: 'Start work', variant: 'secondary' },
  { status: 'PENDING_APPROVAL', label: 'Submit for approval', variant: 'secondary' },
  { status: 'CLOSED_REPORTED', label: 'Close - report to compliance', variant: 'danger' },
  { status: 'CLOSED_CLEARED', label: 'Close - cleared', variant: 'success' },
]

const TIMELINE_TONE = {
  CASE_OPENED: 'info',
  ALERT_RAISED: 'high',
  NOTE: 'neutral',
  STATUS_CHANGE: 'accent',
  ASSIGNMENT: 'neutral',
  ESCALATION: 'critical',
  SYSTEM: 'neutral',
  RISK_ASSESSMENT: 'medium',
  CASE_CLOSED: 'low',
}

export default function InvestigationDetailPage() {
  const { caseRef } = useParams()
  const toast = useToast()
  const { can } = useAuth()

  const { data, error, loading, reload } = useApi(() => api.investigation(caseRef), [caseRef])
  const users = useApi(() => api.listUsers(), [], { enabled: can('users:manage') })

  const [noteOpen, setNoteOpen] = useState(false)
  const [noteBody, setNoteBody] = useState('')
  const [noteType, setNoteType] = useState('NOTE')
  const [statusModal, setStatusModal] = useState(null)
  const [statusNote, setStatusNote] = useState('')
  const [assignOpen, setAssignOpen] = useState(false)
  const [assignee, setAssignee] = useState('')

  const addNote = useMutation(async () => {
    await api.addInvestigationNote(caseRef, { body: noteBody, note_type: noteType })
    toast.success('Note recorded and written to the audit log.')
    setNoteOpen(false)
    setNoteBody('')
    reload()
  })

  const changeStatus = useMutation(async (status, note) => {
    await api.updateInvestigationStatus(caseRef, { status, note: note || undefined })
    toast.success(`Case moved to ${humanise(status)}.`)
    setStatusModal(null)
    setStatusNote('')
    reload()
  })

  const assign = useMutation(async (username) => {
    await api.assignInvestigation(caseRef, username)
    toast.success(`Case assigned to ${username}.`)
    setAssignOpen(false)
    reload()
  })

  if (error) {
    return <ErrorState error={error} onRetry={reload} title="Case not found" />
  }

  const snapshot = data?.network_snapshot

  return (
    <>
      <Link
        to="/investigations"
        className="mb-3 inline-flex items-center gap-1.5 text-2xs text-slateish-400 hover:text-slateish-200"
      >
        <ArrowLeft size={12} aria-hidden="true" /> All investigations
      </Link>

      <PageHeader
        icon={FileSearch}
        title={loading ? 'Loading case…' : data.title}
        subtitle={
          data
            ? `${data.case_ref} · opened ${formatDateTime(data.opened_at)}${data.due_at ? ` · due ${formatDateTime(data.due_at)}` : ''}`
            : ''
        }
      >
        {data && can('investigations:write') && (
          <Button variant="primary" icon={MessageSquarePlus} onClick={() => setNoteOpen(true)}>
            Add note
          </Button>
        )}
      </PageHeader>

      {loading && <Skeleton className="h-64" />}

      {data && (
        <div className="grid gap-3 xl:grid-cols-[1fr_340px]">
          {/* --------------------------------------------------- left column */}
          <div className="space-y-3">
            <Card>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <StatusBadge status={data.status} />
                <Chip
                  tone={
                    data.priority === 'CRITICAL'
                      ? 'critical'
                      : data.priority === 'HIGH'
                        ? 'high'
                        : data.priority === 'MEDIUM'
                          ? 'medium'
                          : 'neutral'
                  }
                >
                  {data.priority} priority
                </Chip>
                <RiskBadge
                  level={scoreMeta(data.risk_score).level}
                  score={data.risk_score}
                  showScore
                />
                {data.outcome && <Chip tone="low">outcome: {data.outcome}</Chip>}
              </div>
              {data.summary && (
                <p className="text-xs leading-relaxed text-slateish-200">{data.summary}</p>
              )}
            </Card>

            {/* --------------------------------------------- network graph */}
            {snapshot && (
              <Card padded={false}>
                <div className="p-4 pb-2">
                  <CardHeader
                    icon={Network}
                    title={`Network ${snapshot.network_ref}`}
                    subtitle={`${snapshot.stats?.pattern} · ${snapshot.stats?.node_count} accounts · ${snapshot.stats?.edge_count} transfers · ${formatInr(snapshot.stats?.total_flow ?? 0)}`}
                    action={
                      <Link
                        to={`/network?network=${snapshot.network_ref}`}
                        className="text-2xs font-medium text-info hover:underline"
                      >
                        Open full view
                      </Link>
                    }
                    className="mb-0"
                  />
                </div>
                <div className="h-[340px] w-full border-y border-ink-800">
                  <NetworkGraph nodes={snapshot.nodes} edges={snapshot.edges} />
                </div>
                <div className="p-3">
                  <GraphLegend />
                </div>
                {snapshot.assessment?.signals?.length > 0 && (
                  <div className="border-t border-ink-800 p-4">
                    <h4 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                      GNN contributing signals
                    </h4>
                    <ul className="space-y-1.5">
                      {snapshot.assessment.signals.slice(0, 6).map((sig) => (
                        <li key={sig.code} className="flex items-baseline gap-2">
                          <span className="tnum w-9 shrink-0 text-right font-mono text-2xs font-semibold text-risk-medium">
                            +{sig.contribution}
                          </span>
                          <div className="min-w-0">
                            <p className="text-2xs font-medium text-slateish-100">{sig.label}</p>
                            <p className="text-[9.5px] leading-snug text-slateish-400">
                              {sig.detail}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 border-t border-ink-800 pt-2 text-[9.5px] leading-relaxed text-slateish-400/80">
                      {snapshot.assessment.disclaimer}
                    </p>
                  </div>
                )}
              </Card>
            )}

            {/* ------------------------------------------------ risk factors */}
            {data.risk_factors?.length > 0 && (
              <Card>
                <CardHeader
                  title="Risk factors"
                  subtitle="From the most recent assessment recorded for this subject."
                />
                <ul className="divide-y divide-ink-800">
                  {data.risk_factors.map((factor) => (
                    <li key={factor.code} className="flex items-baseline gap-2.5 py-2">
                      <span className="tnum w-10 shrink-0 text-right font-mono text-xs font-semibold text-risk-high">
                        +{factor.contribution}
                      </span>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-slateish-100">{factor.label}</p>
                        <p className="mt-0.5 text-2xs leading-snug text-slateish-400">
                          {factor.detail}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {/* ------------------------------------------ transaction history */}
            <Card padded={false}>
              <div className="p-4 pb-2">
                <CardHeader
                  title="Transaction history"
                  subtitle={`${data.linked_transactions?.length ?? 0} recent transactions in scope`}
                  className="mb-0"
                />
              </div>
              {data.linked_transactions?.length ? (
                <Table>
                  <thead>
                    <tr>
                      <Th>Transaction</Th>
                      <Th>When</Th>
                      <Th>Dir</Th>
                      <Th align="right">Amount</Th>
                      <Th>Channel</Th>
                      <Th align="right">Risk</Th>
                      <Th>Status</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.linked_transactions.map((txn) => (
                      <Tr key={txn.txn_ref}>
                        <Td mono className="text-slateish-400">
                          {txn.txn_ref}
                        </Td>
                        <Td mono className="text-slateish-400">
                          {formatDateTime(txn.occurred_at)}
                        </Td>
                        <Td>
                          <Chip tone={txn.direction === 'OUT' ? 'medium' : 'info'}>
                            {txn.direction}
                          </Chip>
                        </Td>
                        <Td align="right" mono className="text-slateish-100">
                          {formatInr(txn.amount)}
                        </Td>
                        <Td>
                          <Chip tone="neutral">{txn.channel}</Chip>
                        </Td>
                        <Td align="right">
                          <RiskBadge
                            level={txn.risk_level}
                            score={txn.risk_score}
                            showScore
                            size="xs"
                          />
                        </Td>
                        <Td>
                          <StatusBadge status={txn.status} />
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <EmptyState title="No transactions in scope" />
              )}
            </Card>

            {/* ------------------------------------------------ alert history */}
            {data.alerts?.length > 0 && (
              <Card padded={false}>
                <div className="p-4 pb-2">
                  <CardHeader
                    title="Alert history"
                    subtitle={`${data.alerts.length} alert(s) for this subject`}
                    className="mb-0"
                  />
                </div>
                <ul className="divide-y divide-ink-800 border-t border-ink-800">
                  {data.alerts.map((alert) => (
                    <li key={alert.alert_ref}>
                      <Link
                        to={`/alerts/${alert.alert_ref}`}
                        className="block px-4 py-2.5 transition-colors hover:bg-ink-800/60"
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <RiskBadge
                            level={alert.risk_level}
                            score={alert.risk_score}
                            showScore
                            size="xs"
                          />
                          <Chip tone="neutral">{alert.source}</Chip>
                          <StatusBadge status={alert.status} />
                          <span className="tnum ml-auto font-mono text-[9.5px] text-slateish-400">
                            {alert.alert_ref} · {formatRelative(alert.raised_at)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-2xs leading-snug text-slateish-200">
                          {alert.title}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          {/* -------------------------------------------------- right column */}
          <div className="space-y-3">
            <Card>
              <CardHeader title="Case actions" subtitle="Each action is audit-logged." />
              {can('investigations:write') ? (
                <div className="space-y-1.5">
                  {STATUS_ACTIONS.map((action) => (
                    <Button
                      key={action.status}
                      variant={action.variant}
                      className="w-full justify-start"
                      disabled={data.status === action.status || changeStatus.pending}
                      onClick={() => setStatusModal(action)}
                    >
                      {action.label}
                    </Button>
                  ))}
                  {can('users:manage') && (
                    <Button
                      variant="secondary"
                      icon={UserPlus}
                      className="w-full justify-start"
                      onClick={() => setAssignOpen(true)}
                    >
                      Assign investigator
                    </Button>
                  )}
                </div>
              ) : (
                <p className="text-2xs text-slateish-400">
                  Your role does not include investigation-write permission.
                </p>
              )}
            </Card>

            <Card>
              <CardHeader title="Case details" />
              <KeyValue label="Case ref" value={data.case_ref} mono />
              <KeyValue label="Status" value={humanise(data.status)} />
              <KeyValue label="Priority" value={data.priority} />
              <KeyValue label="Assignee" value={data.assignee_name ?? 'unassigned'} />
              <KeyValue label="Opened" value={formatDateTime(data.opened_at)} mono />
              {data.due_at && <KeyValue label="Due" value={formatDateTime(data.due_at)} mono />}
              {data.closed_at && (
                <KeyValue label="Closed" value={formatDateTime(data.closed_at)} mono />
              )}
              {data.outcome && <KeyValue label="Outcome" value={data.outcome} />}
              <div className="mt-2 space-y-1.5 border-t border-ink-800 pt-2">
                {data.customer_ref && (
                  <Link
                    to={`/customers/${data.customer_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-info/40"
                  >
                    <User size={12} className="text-info" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">
                      {data.customer_name}{' '}
                      <span className="tnum font-mono text-slateish-400">{data.customer_ref}</span>
                    </span>
                  </Link>
                )}
                {data.alert_ref && (
                  <Link
                    to={`/alerts/${data.alert_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-info/40"
                  >
                    <ShieldAlert size={12} className="text-risk-high" aria-hidden="true" />
                    <span className="tnum font-mono">{data.alert_ref}</span>
                  </Link>
                )}
                {data.network_ref && (
                  <Link
                    to={`/network?network=${data.network_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-accent/40"
                  >
                    <Network size={12} className="text-accent" aria-hidden="true" />
                    <span className="tnum font-mono">{data.network_ref}</span>
                  </Link>
                )}
              </div>
            </Card>

            {/* ----------------------------------------------------- notes */}
            <Card padded={false}>
              <div className="p-4 pb-2">
                <CardHeader
                  icon={ClipboardList}
                  title="Investigator notes"
                  subtitle={`${data.notes?.length ?? 0} note(s)`}
                  className="mb-0"
                />
              </div>
              {data.notes?.length ? (
                <ul className="max-h-80 divide-y divide-ink-800 overflow-y-auto border-t border-ink-800">
                  {data.notes
                    .slice()
                    .reverse()
                    .map((note) => (
                      <li key={note.id} className="px-4 py-2.5">
                        <div className="flex items-center gap-1.5">
                          <Chip tone={TIMELINE_TONE[note.note_type] ?? 'neutral'}>
                            {humanise(note.note_type)}
                          </Chip>
                          <span className="ml-auto text-[9.5px] text-slateish-400">
                            {formatRelative(note.created_at)}
                          </span>
                        </div>
                        <p className="mt-1 whitespace-pre-line text-2xs leading-relaxed text-slateish-200">
                          {note.body}
                        </p>
                        <p className="mt-1 text-[9.5px] text-slateish-400">— {note.author_name}</p>
                      </li>
                    ))}
                </ul>
              ) : (
                <EmptyState title="No notes yet" message="Record your findings as you work." />
              )}
            </Card>

            {/* -------------------------------------------------- timeline */}
            <Card padded={false}>
              <div className="p-4 pb-2">
                <CardHeader title="Case timeline" className="mb-0" />
              </div>
              {data.timeline?.length ? (
                <ol className="max-h-80 overflow-y-auto border-t border-ink-800 p-4">
                  {data.timeline.map((event, index) => (
                    <li key={`${event.at}-${index}`} className="relative flex gap-2.5 pb-3">
                      {index < data.timeline.length - 1 && (
                        <span
                          className="absolute left-[5px] top-3 h-full w-px bg-ink-700"
                          aria-hidden="true"
                        />
                      )}
                      <span
                        className="relative z-10 mt-1 h-2.5 w-2.5 shrink-0 rounded-full border-2 border-ink-900 bg-info"
                        aria-hidden="true"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-baseline gap-1.5">
                          <span className="text-2xs font-medium text-slateish-100">
                            {event.label}
                          </span>
                          <span className="text-[9.5px] text-slateish-400">
                            {formatDateTime(event.at)}
                          </span>
                        </div>
                        {event.detail && (
                          <p className="mt-0.5 line-clamp-3 text-[9.5px] leading-snug text-slateish-400">
                            {event.detail}
                          </p>
                        )}
                        <p className="mt-0.5 text-[9.5px] text-slateish-400/70">{event.actor}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState title="No timeline events" />
              )}
            </Card>

            <Advisory tone="warning">{data.advisory}</Advisory>
          </div>
        </div>
      )}

      {/* ----------------------------------------------------- note modal */}
      <Modal
        open={noteOpen}
        onClose={() => setNoteOpen(false)}
        title="Add investigator note"
        footer={
          <>
            <Button variant="ghost" onClick={() => setNoteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={addNote.pending}
              disabled={!noteBody.trim()}
              onClick={() => addNote.run().catch(() => {})}
            >
              Record note
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
              Note type
            </label>
            <Select
              className="w-full"
              value={noteType}
              onChange={(e) => setNoteType(e.target.value)}
              options={[
                { value: 'NOTE', label: 'Investigator note' },
                { value: 'ESCALATION', label: 'Escalation' },
              ]}
            />
          </div>
          <div>
            <label className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400">
              Note
            </label>
            <Textarea
              rows={6}
              value={noteBody}
              onChange={(e) => setNoteBody(e.target.value)}
              placeholder="What you examined, what you found, what you still need. Avoid asserting conclusions the evidence does not support."
            />
          </div>
          {addNote.error && <p className="text-2xs text-risk-high">{addNote.error.message}</p>}
        </div>
      </Modal>

      {/* --------------------------------------------------- status modal */}
      <Modal
        open={Boolean(statusModal)}
        onClose={() => setStatusModal(null)}
        title={statusModal?.label ?? ''}
        footer={
          <>
            <Button variant="ghost" onClick={() => setStatusModal(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={changeStatus.pending}
              onClick={() => changeStatus.run(statusModal.status, statusNote).catch(() => {})}
            >
              Confirm
            </Button>
          </>
        }
      >
        <p className="mb-2 text-2xs text-slateish-400">
          Moving this case to{' '}
          <strong className="text-slateish-200">{humanise(statusModal?.status ?? '')}</strong>.
          {statusModal?.status?.startsWith('CLOSED') &&
            ' Closing a case also dispositions its linked alert.'}
        </p>
        <Textarea
          rows={4}
          value={statusNote}
          onChange={(e) => setStatusNote(e.target.value)}
          placeholder="Rationale for this transition…"
        />
        {changeStatus.error && (
          <p className="mt-2 text-2xs text-risk-high">{changeStatus.error.message}</p>
        )}
      </Modal>

      {/* --------------------------------------------------- assign modal */}
      <Modal
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        title="Assign investigator"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAssignOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={assign.pending}
              disabled={!assignee}
              onClick={() => assign.run(assignee).catch(() => {})}
            >
              Assign
            </Button>
          </>
        }
      >
        {users.data?.length ? (
          <Select
            className="w-full"
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            options={[
              { value: '', label: 'Select an investigator…' },
              ...users.data.map((u) => ({
                value: u.username,
                label: `${u.full_name} (${u.role})`,
              })),
            ]}
          />
        ) : (
          <p className="text-2xs text-slateish-400">No users available.</p>
        )}
        {assign.error && <p className="mt-2 text-2xs text-risk-high">{assign.error.message}</p>}
      </Modal>
    </>
  )
}
