import {
  ArrowLeft,
  ArrowUpCircle,
  BellRing,
  CheckCircle2,
  Eye,
  FilePlus2,
  Network,
  ShieldAlert,
  User,
  UserPlus,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  DataList,
  EmptyState,
  ErrorState,
  KeyValue,
  Modal,
  PageHeader,
  RiskBadge,
  ScoreMeter,
  Select,
  Skeleton,
  StatusBadge,
  Textarea,
} from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatInr, humanise } from '../utils/format.js'

const TRANSITIONS = [
  { status: 'UNDER_REVIEW', label: 'Take for review', icon: Eye, variant: 'secondary' },
  { status: 'ESCALATED', label: 'Escalate', icon: ArrowUpCircle, variant: 'danger' },
  { status: 'CONFIRMED_SUSPICIOUS', label: 'Confirm suspicious', icon: ShieldAlert, variant: 'danger' },
  { status: 'CLEARED', label: 'Clear alert', icon: CheckCircle2, variant: 'success' },
]

export default function AlertDetailPage() {
  const { alertRef } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const { can } = useAuth()

  const { data, error, loading, reload } = useApi(() => api.alert(alertRef), [alertRef])
  const users = useApi(() => api.listUsers(), [], { enabled: can('users:manage') })

  const [noteModal, setNoteModal] = useState(null) // { status, label }
  const [note, setNote] = useState('')
  const [assignModal, setAssignModal] = useState(false)
  const [assignee, setAssignee] = useState('')

  const transition = useMutation(async (status, text) => {
    await api.updateAlertStatus(alertRef, { status, note: text || undefined })
    toast.success(`Alert moved to ${humanise(status)}.`)
    setNoteModal(null)
    setNote('')
    reload()
  })

  const assign = useMutation(async (username) => {
    await api.assignAlert(alertRef, username)
    toast.success(`Assigned to ${username}.`)
    setAssignModal(false)
    reload()
  })

  const createCase = useMutation(async () => {
    const investigation = await api.createInvestigation({
      title: `Review of ${humanise(data.alert_type)} - ${data.alert_ref}`,
      alert_ref: data.alert_ref,
      customer_ref: data.customer_ref ?? undefined,
      network_ref: data.network_ref ?? undefined,
      priority: data.risk_score >= 70 ? 'HIGH' : 'MEDIUM',
      summary: `Case opened from alert ${data.alert_ref}.`,
    })
    toast.success(`Case ${investigation.case_ref} opened.`)
    navigate(`/investigations/${investigation.case_ref}`)
  })

  if (error) {
    return <ErrorState error={error} onRetry={reload} title="Alert not found" />
  }

  return (
    <>
      <Link
        to="/alerts"
        className="mb-3 inline-flex items-center gap-1.5 text-2xs text-slateish-400 hover:text-slateish-200"
      >
        <ArrowLeft size={12} aria-hidden="true" /> All alerts
      </Link>

      <PageHeader
        icon={BellRing}
        title={loading ? 'Loading alert…' : data.title}
        subtitle={data ? `${data.alert_ref} · raised ${formatDateTime(data.raised_at)}` : ''}
      >
        {data && can('investigations:write') && (
          <Button
            variant="primary"
            icon={FilePlus2}
            loading={createCase.pending}
            onClick={() => createCase.run().catch(() => {})}
            disabled={Boolean(data.investigation_ref)}
            title={
              data.investigation_ref
                ? `Already linked to ${data.investigation_ref}`
                : 'Open an investigation case from this alert'
            }
          >
            {data.investigation_ref ? 'Case exists' : 'Open investigation'}
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
                <RiskBadge level={data.risk_level} score={data.risk_score} showScore />
                <StatusBadge status={data.status} />
                <Chip
                  tone={
                    data.source === 'NETWORK'
                      ? 'accent'
                      : data.source === 'INTEGRITY'
                        ? 'critical'
                        : data.source === 'PROACTIVE'
                          ? 'info'
                          : 'neutral'
                  }
                >
                  {data.source} layer
                </Chip>
                <Chip tone="neutral">severity {data.severity}</Chip>
                {data.rule_code && <Chip tone="medium">{data.rule_code}</Chip>}
              </div>

              <ScoreMeter score={data.risk_score} level={data.risk_level} className="mb-4" />

              <h3 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                Why this alert fired
              </h3>
              <p className="whitespace-pre-line text-xs leading-relaxed text-slateish-200">
                {data.explanation}
              </p>
            </Card>

            {/* Evidence metrics, when the detector supplied them */}
            {data.evidence?.metrics?.length > 0 && (
              <Card>
                <CardHeader
                  title="Measured evidence"
                  subtitle={data.evidence.headline ?? undefined}
                />
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {data.evidence.metrics.map((metric) => (
                    <div
                      key={metric.label}
                      className="rounded border border-ink-700 bg-ink-900/60 p-2.5"
                    >
                      <p className="text-[9.5px] uppercase tracking-wide text-slateish-400">
                        {metric.label}
                      </p>
                      <p className="tnum mt-1 font-mono text-xs font-semibold text-slateish-100">
                        {metric.value}
                      </p>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            {/* Network-layer evidence */}
            {data.evidence?.signals?.length > 0 && (
              <Card>
                <CardHeader
                  icon={Network}
                  title="Network signals"
                  subtitle="Structural characteristics the graph engine and GNN measured."
                  action={
                    data.network_ref && (
                      <Link
                        to={`/network?network=${data.network_ref}`}
                        className="text-2xs font-medium text-info hover:underline"
                      >
                        Open {data.network_ref}
                      </Link>
                    )
                  }
                />
                <ul className="divide-y divide-ink-800">
                  {data.evidence.signals.map((sig) => (
                    <li key={sig.code} className="py-2">
                      <div className="flex items-baseline gap-2">
                        <span className="tnum w-9 shrink-0 text-right font-mono text-2xs font-semibold text-risk-medium">
                          +{sig.contribution}
                        </span>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-slateish-100">{sig.label}</p>
                          <p className="mt-0.5 text-2xs leading-snug text-slateish-400">
                            {sig.detail}
                          </p>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            )}

            {/* Proactive-layer factor breakdown */}
            {data.evidence?.factors?.length > 0 && (
              <Card>
                <CardHeader title="Risk factor breakdown" />
                <ul className="divide-y divide-ink-800">
                  {data.evidence.factors.map((factor) => (
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

            {data.disposition_note && (
              <Card>
                <CardHeader title="Disposition" />
                <p className="text-xs leading-relaxed text-slateish-200">
                  {data.disposition_note}
                </p>
                {data.closed_at && (
                  <p className="mt-1.5 text-2xs text-slateish-400">
                    Closed {formatDateTime(data.closed_at)}
                  </p>
                )}
              </Card>
            )}
          </div>

          {/* -------------------------------------------------- right column */}
          <div className="space-y-3">
            <Card>
              <CardHeader title="Actions" subtitle="Every action writes an audit entry." />
              {can('alerts:update') ? (
                <div className="space-y-1.5">
                  {TRANSITIONS.map((t) => (
                    <Button
                      key={t.status}
                      variant={t.variant}
                      icon={t.icon}
                      className="w-full justify-start"
                      disabled={data.status === t.status || transition.pending}
                      onClick={() => setNoteModal(t)}
                    >
                      {t.label}
                    </Button>
                  ))}
                  {can('users:manage') && (
                    <Button
                      variant="secondary"
                      icon={UserPlus}
                      className="w-full justify-start"
                      onClick={() => setAssignModal(true)}
                    >
                      Assign investigator
                    </Button>
                  )}
                </div>
              ) : (
                <p className="text-2xs text-slateish-400">
                  Your role does not include alert-update permission.
                </p>
              )}
            </Card>

            <Card>
              <CardHeader title="Details" />
              <KeyValue label="Alert ref" value={data.alert_ref} mono />
              <KeyValue label="Type" value={humanise(data.alert_type)} />
              <KeyValue label="Detection layer" value={data.source} />
              <KeyValue label="Severity" value={data.severity} />
              <KeyValue label="Rule" value={data.rule_code ?? '—'} mono />
              <KeyValue label="Raised" value={formatDateTime(data.raised_at)} mono />
              <KeyValue
                label="Assigned"
                value={data.assignee_name ?? 'unassigned'}
              />
              {data.evidence?.layer && (
                <KeyValue label="Pipeline stage" value={data.evidence.layer} />
              )}
            </Card>

            <Card>
              <CardHeader title="Linked records" />
              <div className="space-y-1.5">
                {data.customer_ref && (
                  <Link
                    to={`/customers/${data.customer_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-info/40 hover:bg-ink-800"
                  >
                    <User size={12} className="text-info" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">
                      {data.customer_name}
                      <span className="tnum ml-1 font-mono text-slateish-400">
                        {data.customer_ref}
                      </span>
                    </span>
                  </Link>
                )}
                {data.transaction_ref && (
                  <Link
                    to={`/transactions?search=${data.transaction_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-info/40 hover:bg-ink-800"
                  >
                    <span className="tnum font-mono">{data.transaction_ref}</span>
                  </Link>
                )}
                {data.network_ref && (
                  <Link
                    to={`/network?network=${data.network_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-accent/40 hover:bg-ink-800"
                  >
                    <Network size={12} className="text-accent" aria-hidden="true" />
                    <span className="tnum font-mono">{data.network_ref}</span>
                  </Link>
                )}
                {data.investigation_ref && (
                  <Link
                    to={`/investigations/${data.investigation_ref}`}
                    className="flex items-center gap-2 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2 text-2xs text-slateish-200 hover:border-info/40 hover:bg-ink-800"
                  >
                    <span className="tnum font-mono">{data.investigation_ref}</span>
                  </Link>
                )}
                {!data.customer_ref &&
                  !data.transaction_ref &&
                  !data.network_ref &&
                  !data.investigation_ref && (
                    <p className="text-2xs text-slateish-400">No linked records.</p>
                  )}
              </div>
            </Card>

            <Advisory tone="warning">{data.advisory}</Advisory>
          </div>
        </div>
      )}

      {/* --------------------------------------------------- status modal */}
      <Modal
        open={Boolean(noteModal)}
        onClose={() => {
          setNoteModal(null)
          setNote('')
        }}
        title={noteModal?.label ?? ''}
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setNoteModal(null)
                setNote('')
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={transition.pending}
              onClick={() => transition.run(noteModal.status, note).catch(() => {})}
            >
              Confirm
            </Button>
          </>
        }
      >
        <p className="mb-2 text-2xs text-slateish-400">
          Moving this alert to <strong className="text-slateish-200">{humanise(noteModal?.status ?? '')}</strong>.
          Add a note for the audit trail (optional but recommended).
        </p>
        <Textarea
          rows={4}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Rationale, what you checked, what you concluded…"
        />
        {transition.error && (
          <p className="mt-2 text-2xs text-risk-high">{transition.error.message}</p>
        )}
      </Modal>

      {/* --------------------------------------------------- assign modal */}
      <Modal
        open={assignModal}
        onClose={() => setAssignModal(false)}
        title="Assign investigator"
        footer={
          <>
            <Button variant="ghost" onClick={() => setAssignModal(false)}>
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
