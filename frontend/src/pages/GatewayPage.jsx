/**
 * Pre-Transaction Security Gateway.
 *
 * Demonstrates the platform's central security property: the backend reads the
 * authoritative amount from its own order record and refuses any request whose
 * claimed amount differs. The analyst can tamper with the outgoing value here and
 * watch the server reject it.
 */
import clsx from 'clsx'
import {
  ArrowRight,
  Ban,
  CheckCircle2,
  CreditCard,
  Database,
  FlaskConical,
  Server,
  ShieldCheck,
  ShieldX,
  Store,
  User,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  DataList,
  EmptyState,
  ErrorState,
  FactorList,
  PageHeader,
  PipelineStep,
  ProvenanceNote,
  RiskBadge,
  ScoreMeter,
  Select,
  Skeleton,
  Spinner,
} from '../components/ui.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatInrExact, formatNumber } from '../utils/format.js'

/* ------------------------------------------------------------ flow diagram */

const FLOW = [
  { label: 'Customer', icon: User },
  { label: 'Ecommerce order', icon: Store },
  { label: 'Payment request', icon: CreditCard },
  { label: 'Security gateway', icon: ShieldCheck, emphasis: true },
  { label: 'AML assessment', icon: Zap, emphasis: true },
  { label: 'Decision', icon: Database, emphasis: true },
  { label: 'Payment provider', icon: Server },
]

function FlowDiagram({ activeIndex }) {
  return (
    <ol className="flex flex-wrap items-center gap-1.5" aria-label="Transaction flow">
      {FLOW.map((step, index) => (
        <li key={step.label} className="flex items-center gap-1.5">
          <div
            className={clsx(
              'flex items-center gap-1.5 rounded border px-2 py-1.5 transition-colors',
              step.emphasis
                ? 'border-info/40 bg-info-soft'
                : 'border-ink-700 bg-ink-850',
              activeIndex !== undefined && index <= activeIndex && 'ring-1 ring-accent/40',
            )}
          >
            <step.icon
              size={12}
              className={step.emphasis ? 'text-info' : 'text-slateish-400'}
              aria-hidden="true"
            />
            <span className="whitespace-nowrap text-2xs font-medium text-slateish-200">
              {step.label}
            </span>
          </div>
          {index < FLOW.length - 1 && (
            <ArrowRight size={11} className="shrink-0 text-slateish-400/50" aria-hidden="true" />
          )}
        </li>
      ))}
    </ol>
  )
}

/* -------------------------------------------------------- integrity result */

function IntegrityPanel({ integrity }) {
  const passed = integrity.passed
  return (
    <Card
      className={clsx(
        'border-2',
        passed
          ? 'border-risk-low/50 bg-risk-lowBg'
          : 'border-risk-critical/60 bg-risk-criticalBg',
      )}
    >
      <div className="mb-3 flex items-start gap-2.5">
        {passed ? (
          <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-risk-low" aria-hidden="true" />
        ) : (
          <ShieldX size={20} className="mt-0.5 shrink-0 text-risk-critical" aria-hidden="true" />
        )}
        <div className="min-w-0">
          <h3
            className={clsx(
              'text-sm font-bold uppercase tracking-wide',
              passed ? 'text-risk-low' : 'text-risk-critical',
            )}
          >
            {passed ? 'Integrity verified' : 'Transaction integrity failure'}
          </h3>
          <p className="mt-0.5 text-2xs text-slateish-400">Status: {integrity.status}</p>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <div className="rounded border border-ink-600 bg-ink-900/70 p-2.5">
          <p className="text-2xs uppercase tracking-wide text-slateish-400">
            Server-authorised amount
          </p>
          <p className="tnum mt-1 font-mono text-sm font-semibold text-risk-low">
            {formatInrExact(integrity.authorized_amount)}
          </p>
          <p className="mt-1 text-[9.5px] leading-tight text-slateish-400">
            read from the database — authoritative
          </p>
        </div>
        <div className="rounded border border-ink-600 bg-ink-900/70 p-2.5">
          <p className="text-2xs uppercase tracking-wide text-slateish-400">
            Incoming request amount
          </p>
          <p
            className={clsx(
              'tnum mt-1 font-mono text-sm font-semibold',
              passed ? 'text-slateish-100' : 'text-risk-critical',
            )}
          >
            {formatInrExact(integrity.received_amount)}
          </p>
          <p className="mt-1 text-[9.5px] leading-tight text-slateish-400">
            supplied by the client — untrusted
          </p>
        </div>
        <div className="rounded border border-ink-600 bg-ink-900/70 p-2.5">
          <p className="text-2xs uppercase tracking-wide text-slateish-400">Mismatch</p>
          <p
            className={clsx(
              'tnum mt-1 font-mono text-sm font-semibold',
              integrity.mismatch_amount > 0 ? 'text-risk-critical' : 'text-risk-low',
            )}
          >
            {integrity.mismatch_amount > 0
              ? formatInrExact(integrity.mismatch_amount)
              : 'none'}
          </p>
          <p className="mt-1 text-[9.5px] leading-tight text-slateish-400">
            {integrity.mismatch_pct !== 0 ? `${integrity.mismatch_pct}% deviation` : 'exact match'}
          </p>
        </div>
      </div>

      <p className="mt-3 text-2xs leading-relaxed text-slateish-300">{integrity.message}</p>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-700/60 pt-2.5">
        <Chip tone={integrity.digest_valid ? 'low' : 'critical'}>
          HMAC digest {integrity.digest_valid ? 'valid' : 'INVALID'}
        </Chip>
        <span className="font-mono text-2xs text-slateish-400">
          source of truth: {integrity.source_of_truth}
        </span>
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------------- page */

export default function GatewayPage() {
  const toast = useToast()
  const { data: orders, loading: ordersLoading, error: ordersError, reload } = useApi(
    () => api.orders({ status: 'AWAITING_PAYMENT', limit: 40 }),
    [],
  )

  const [orderRef, setOrderRef] = useState('')
  const [claimedAmount, setClaimedAmount] = useState('')
  const [decision, setDecision] = useState(null)

  const selectedOrder = orders?.find((o) => o.order_ref === orderRef)

  // Default to the first payable order, with an honest (matching) amount
  useEffect(() => {
    if (!orderRef && orders?.length) {
      setOrderRef(orders[0].order_ref)
      setClaimedAmount(String(orders[0].authorized_amount))
    }
  }, [orders, orderRef])

  function onSelectOrder(ref) {
    setOrderRef(ref)
    const order = orders?.find((o) => o.order_ref === ref)
    if (order) setClaimedAmount(String(order.authorized_amount))
    setDecision(null)
  }

  const runGateway = useMutation(async (amount) => {
    const result = await api.gatewayDecision({
      order_ref: orderRef,
      claimed_amount: Number(amount),
      claimed_currency: selectedOrder?.currency ?? 'INR',
      customer_ref: selectedOrder?.customer_ref,
      channel: 'UPI',
      device_fingerprint: 'console-demo-1a2b',
    })
    setDecision(result)
    if (result.decision === 'BLOCK') {
      toast.error(`Payment BLOCKED — ${result.integrity.status}`, { title: 'Gateway decision' })
    } else if (result.decision === 'REVIEW') {
      toast.warning(`Held for review at risk ${result.risk_score}/100.`, {
        title: 'Gateway decision',
      })
    } else {
      toast.success(`${result.decision} at risk ${result.risk_score}/100.`, {
        title: 'Gateway decision',
      })
    }
    reload()
    return result
  })

  const honestAmount = selectedOrder?.authorized_amount ?? 0
  const isTampered =
    selectedOrder && Math.abs(Number(claimedAmount) - honestAmount) > 0.01

  return (
    <>
      <PageHeader
        icon={ShieldCheck}
        title="Pre-Transaction Security Gateway"
        subtitle="Validates that a payment request was not modified in transit, then runs proactive AML assessment before any settlement. The client-supplied amount is never trusted."
      />

      <Card className="mb-4">
        <CardHeader
          title="Transaction flow"
          subtitle="Every payment passes through the gateway before reaching a provider."
        />
        <FlowDiagram activeIndex={decision ? 6 : undefined} />
      </Card>

      <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
        {/* ------------------------------------------------- request builder */}
        <div className="space-y-3">
          <Card>
            <CardHeader
              icon={FlaskConical}
              title="Simulate a payment request"
              subtitle="Pick an order, then submit the honest amount or a tampered one."
            />

            {ordersError && <ErrorState error={ordersError} onRetry={reload} />}
            {ordersLoading && <Skeleton className="h-32" />}

            {orders && orders.length === 0 && (
              <EmptyState
                title="No payable orders"
                message="Every seeded order has been paid. Re-run the seed script to reset."
              />
            )}

            {orders && orders.length > 0 && (
              <div className="space-y-3">
                <div>
                  <label
                    htmlFor="order"
                    className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400"
                  >
                    Order
                  </label>
                  <Select
                    id="order"
                    className="w-full"
                    value={orderRef}
                    onChange={(e) => onSelectOrder(e.target.value)}
                    options={orders.map((o) => ({
                      value: o.order_ref,
                      label: `${o.order_ref} · ${o.merchant_name} · ₹${o.authorized_amount.toLocaleString('en-IN')}`,
                    }))}
                  />
                </div>

                {selectedOrder && (
                  <div className="rounded border border-ink-600 bg-ink-900/70 p-2.5">
                    <DataList
                      columns={1}
                      items={[
                        { label: 'Customer', value: `${selectedOrder.customer_name} (${selectedOrder.customer_ref})` },
                        { label: 'Merchant', value: selectedOrder.merchant_name },
                        { label: 'Description', value: selectedOrder.description || '—' },
                        {
                          label: 'Amount shown to the customer',
                          value: formatInrExact(selectedOrder.authorized_amount),
                          mono: true,
                        },
                      ]}
                    />
                  </div>
                )}

                <div>
                  <label
                    htmlFor="claimed"
                    className="mb-1 block text-2xs font-medium uppercase tracking-wide text-slateish-400"
                  >
                    Amount the client sends
                  </label>
                  <input
                    id="claimed"
                    type="number"
                    min="1"
                    step="0.01"
                    value={claimedAmount}
                    onChange={(e) => setClaimedAmount(e.target.value)}
                    className={clsx(
                      'tnum w-full rounded border bg-ink-900 px-2.5 py-2 font-mono text-sm text-slateish-100 focus:outline-none focus:ring-1',
                      isTampered
                        ? 'border-risk-critical/60 focus:ring-risk-critical/40'
                        : 'border-ink-600 focus:border-info/60 focus:ring-info/40',
                    )}
                  />
                  {isTampered && (
                    <p className="mt-1 text-2xs text-risk-critical">
                      This differs from the server-authorised amount — the gateway will block it.
                    </p>
                  )}
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    size="xs"
                    onClick={() => setClaimedAmount(String(honestAmount))}
                  >
                    Honest: ₹{honestAmount.toLocaleString('en-IN')}
                  </Button>
                  <Button
                    variant="danger"
                    size="xs"
                    onClick={() => setClaimedAmount(String(honestAmount * 10))}
                  >
                    Tamper ×10
                  </Button>
                  <Button
                    variant="danger"
                    size="xs"
                    onClick={() => setClaimedAmount(String(Math.max(1, honestAmount / 10)))}
                  >
                    Tamper ÷10
                  </Button>
                </div>

                <Button
                  variant="primary"
                  className="w-full justify-center"
                  loading={runGateway.pending}
                  onClick={() => runGateway.run(claimedAmount).catch(() => {})}
                  disabled={!orderRef || !claimedAmount}
                >
                  {runGateway.pending ? 'Running pipeline…' : 'Submit to gateway'}
                </Button>

                {runGateway.error && (
                  <p className="text-2xs text-risk-high">{runGateway.error.message}</p>
                )}
              </div>
            )}
          </Card>

          <Advisory>
            The backend reads <code className="text-slateish-300">orders.authorized_amount</code>{' '}
            and compares the client&apos;s claim against it. The claimed value is never used as the
            amount to charge, written as a settled amount, or forwarded onward — so tampering
            cannot change what would be charged, only trigger a block.
          </Advisory>
        </div>

        {/* ------------------------------------------------------- decision */}
        <div className="space-y-3">
          {!decision && !runGateway.pending && (
            <Card>
              <EmptyState
                icon={ShieldCheck}
                title="No request submitted yet"
                message="Choose an order and submit a payment request. Try the honest amount first, then tamper with it to see the integrity gate reject the request."
              />
            </Card>
          )}

          {runGateway.pending && (
            <Card>
              <div className="flex items-center justify-center gap-2 py-12 text-slateish-400">
                <Spinner size={18} />
                <span className="text-xs">Running the nine-step decision pipeline…</span>
              </div>
            </Card>
          )}

          {decision && (
            <>
              <IntegrityPanel integrity={decision.integrity} />

              <Card>
                <CardHeader
                  title="Decision pipeline"
                  subtitle="Ordered steps executed server-side. An integrity failure is a hard gate — AML scoring is skipped entirely."
                  action={
                    <div className="flex items-center gap-2">
                      <span
                        className={clsx(
                          'rounded border px-2 py-0.5 text-2xs font-bold uppercase tracking-wide',
                          decision.decision === 'ALLOW' &&
                            'border-risk-low/50 bg-risk-lowBg text-risk-low',
                          decision.decision === 'MONITOR' &&
                            'border-risk-medium/50 bg-risk-mediumBg text-risk-medium',
                          decision.decision === 'REVIEW' &&
                            'border-risk-high/50 bg-risk-highBg text-risk-high',
                          decision.decision === 'BLOCK' &&
                            'border-risk-critical/50 bg-risk-criticalBg text-risk-critical',
                        )}
                      >
                        {decision.decision}
                      </span>
                      <RiskBadge
                        level={decision.risk_level}
                        score={decision.risk_score}
                        showScore
                      />
                    </div>
                  }
                />
                <ol className="mt-1">
                  {decision.pipeline.map((step, index) => (
                    <PipelineStep
                      key={step.key}
                      step={step}
                      last={index === decision.pipeline.length - 1}
                    />
                  ))}
                </ol>
              </Card>

              <div className="grid gap-3 md:grid-cols-2">
                <Card>
                  <CardHeader title="Outcome" />
                  <DataList
                    columns={1}
                    items={[
                      { label: 'Request ID', value: decision.request_id, mono: true },
                      { label: 'Order', value: decision.order_ref, mono: true },
                      { label: 'Customer', value: decision.customer_ref ?? '—', mono: true },
                      {
                        label: 'Amount forwarded to provider',
                        value:
                          decision.amount_forwarded !== null &&
                          decision.amount_forwarded !== undefined ? (
                            <span className="text-risk-low">
                              {formatInrExact(decision.amount_forwarded)}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-risk-critical">
                              <Ban size={11} aria-hidden="true" /> nothing forwarded
                            </span>
                          ),
                        mono: true,
                      },
                      {
                        label: 'Transaction created',
                        value: decision.transaction_ref ? (
                          <Link
                            to={`/transactions?search=${decision.transaction_ref}`}
                            className="font-mono text-info hover:underline"
                          >
                            {decision.transaction_ref}
                          </Link>
                        ) : (
                          'none'
                        ),
                      },
                      {
                        label: 'Alert raised',
                        value: decision.alert_ref ? (
                          <Link
                            to={`/alerts/${decision.alert_ref}`}
                            className="font-mono text-risk-high hover:underline"
                          >
                            {decision.alert_ref}
                          </Link>
                        ) : (
                          'none'
                        ),
                      },
                    ]}
                  />
                  <p className="mt-2.5 rounded border border-ink-700 bg-ink-900/70 p-2 text-2xs leading-snug text-slateish-400">
                    {decision.payment_provider_note}
                  </p>
                </Card>

                <Card>
                  <CardHeader title="Risk assessment" />
                  {decision.risk_score > 0 && (
                    <ScoreMeter
                      score={decision.risk_score}
                      level={decision.risk_level}
                      className="mb-3"
                    />
                  )}
                  {decision.factors?.length > 0 ? (
                    <FactorList factors={decision.factors} total={decision.risk_score} />
                  ) : (
                    <p className="text-2xs text-slateish-400">
                      No AML factors were computed — the request never reached the scoring stage.
                    </p>
                  )}
                  {decision.triggered_rules?.length > 0 && (
                    <div className="mt-3 border-t border-ink-800 pt-2.5">
                      <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                        Rules triggered
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {decision.triggered_rules.map((code) => (
                          <Chip key={code} tone="medium">
                            {code}
                          </Chip>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              </div>

              <ProvenanceNote provenance={decision.provenance} />
              <Advisory tone="warning">{decision.advisory}</Advisory>
            </>
          )}
        </div>
      </div>
    </>
  )
}
