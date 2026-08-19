import {
  Activity,
  ArrowLeft,
  Banknote,
  BellRing,
  Gauge,
  Network,
  User,
  Users,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { RiskTrajectoryChart } from '../charts/index.jsx'
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
  KeyValue,
  PageHeader,
  ProvenanceNote,
  RiskBadge,
  ScoreMeter,
  Skeleton,
  Table,
  Td,
  Th,
  Tr,
  TrendIndicator,
} from '../components/ui.jsx'
import { useApi } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import {
  formatDate,
  formatInr,
  formatMultiple,
  formatNumber,
  formatPercent,
} from '../utils/format.js'

function BehaviourStats({ behaviour }) {
  if (!behaviour) return null
  const cells = [
    { label: 'Average transaction', value: formatInr(behaviour.avg_transaction_amount) },
    { label: 'Median transaction', value: formatInr(behaviour.median_transaction_amount) },
    { label: 'Largest transaction', value: formatInr(behaviour.max_transaction_amount) },
    { label: 'Transactions / month', value: formatNumber(behaviour.transactions_per_month, 1) },
    { label: 'Total transactions', value: formatNumber(behaviour.total_transactions) },
    { label: 'Unique counterparties', value: formatNumber(behaviour.unique_counterparties) },
    { label: 'New counterparties (30d)', value: formatNumber(behaviour.new_counterparties_30d) },
    { label: 'Cross-border share', value: `${behaviour.international_share}%` },
    {
      label: 'Transaction velocity',
      value: behaviour.velocity_label,
      tone:
        behaviour.velocity_label === 'HIGH'
          ? '#e0533d'
          : behaviour.velocity_label === 'MEDIUM'
            ? '#d99524'
            : '#22a06b',
      hint: `peak ${behaviour.velocity_max_per_hour} per hour`,
    },
    { label: 'Prior alerts', value: formatNumber(behaviour.previous_alerts) },
    { label: 'Total outflow', value: formatInr(behaviour.total_outflow) },
    { label: 'Total inflow', value: formatInr(behaviour.total_inflow) },
    { label: 'Baseline average', value: formatInr(behaviour.baseline_avg_amount) },
    {
      label: 'Deviation from baseline',
      value: formatMultiple(behaviour.amount_deviation_ratio),
      tone: behaviour.amount_deviation_ratio >= 3 ? '#e0533d' : undefined,
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-0 sm:grid-cols-3">
      {cells.map((cell) => (
        <div key={cell.label} className="border-b border-ink-800/70 py-1.5">
          <p className="text-2xs text-slateish-400">{cell.label}</p>
          <p
            className="tnum mt-0.5 font-mono text-xs font-medium text-slateish-100"
            style={cell.tone ? { color: cell.tone } : undefined}
          >
            {cell.value}
          </p>
          {cell.hint && <p className="text-[9.5px] text-slateish-400/70">{cell.hint}</p>}
        </div>
      ))}
    </div>
  )
}

export default function CustomerDetailPage() {
  const { customerRef } = useParams()

  const profile = useApi(() => api.customer(customerRef), [customerRef])
  const risk = useApi(() => api.customerRisk(customerRef), [customerRef])
  const alerts = useApi(
    (signal) => api.alerts({ customer_ref: customerRef, page_size: 12 }, signal),
    [customerRef],
  )
  const txns = useApi(
    (signal) => api.transactions({ customer_ref: customerRef, page_size: 12 }, signal),
    [customerRef],
  )

  const customer = profile.data
  const riskData = risk.data

  if (profile.error) {
    return <ErrorState error={profile.error} onRetry={profile.reload} title="Customer not found" />
  }

  return (
    <>
      <Link
        to="/customers"
        className="mb-3 inline-flex items-center gap-1.5 text-2xs text-slateish-400 hover:text-slateish-200"
      >
        <ArrowLeft size={12} aria-hidden="true" /> All customers
      </Link>

      <PageHeader
        icon={User}
        title={customer ? `${customer.name}` : 'Customer profile'}
        subtitle={
          customer
            ? `${customer.customer_ref} · ${customer.city}, ${customer.country} · onboarded ${formatDate(customer.onboarded_on)}`
            : 'Loading…'
        }
      >
        {customer && (
          <>
            <Link
              to={`/transactions?customer=${customer.customer_ref}`}
              className="inline-flex items-center gap-1.5 rounded border border-ink-600 bg-ink-800 px-2.5 py-1.5 text-xs font-medium text-slateish-200 hover:bg-ink-750"
            >
              <Activity size={13} aria-hidden="true" /> Transactions
            </Link>
            {customer.accounts?.[0] && (
              <Link
                to={`/network?account=${customer.accounts[0].account_ref}`}
                className="inline-flex items-center gap-1.5 rounded border border-ink-600 bg-ink-800 px-2.5 py-1.5 text-xs font-medium text-slateish-200 hover:bg-ink-750"
              >
                <Network size={13} aria-hidden="true" /> View in graph
              </Link>
            )}
          </>
        )}
      </PageHeader>

      <div className="grid gap-3 xl:grid-cols-[1fr_360px]">
        {/* ------------------------------------------------------ left column */}
        <div className="space-y-3">
          <Card>
            <CardHeader
              icon={Gauge}
              title="Current risk assessment"
              subtitle="Recomputed live from this customer's own transaction history."
            />
            {risk.loading && <Skeleton className="h-24" />}
            {risk.error && <ErrorState error={risk.error} onRetry={risk.reload} />}
            {riskData && (
              <>
                <div className="mb-3 flex flex-wrap items-center gap-3">
                  <div className="flex items-baseline gap-2">
                    <span className="tnum font-mono text-3xl font-bold leading-none text-white">
                      {Math.round(riskData.risk_score)}
                    </span>
                    <span className="text-sm text-slateish-400">/100</span>
                  </div>
                  <RiskBadge level={riskData.risk_level} />
                  <TrendIndicator trend={riskData.trend} />
                  <Chip
                    tone={
                      riskData.decision === 'ALLOW'
                        ? 'low'
                        : riskData.decision === 'MONITOR'
                          ? 'medium'
                          : riskData.decision === 'REVIEW'
                            ? 'high'
                            : 'critical'
                    }
                  >
                    action: {riskData.decision}
                  </Chip>
                  {riskData.model_probability !== null && (
                    <span className="tnum font-mono text-2xs text-slateish-400">
                      model p = {riskData.model_probability.toFixed(4)}
                    </span>
                  )}
                </div>
                <ScoreMeter
                  score={riskData.risk_score}
                  level={riskData.risk_level}
                  className="mb-4"
                />
                <FactorList factors={riskData.factors} total={riskData.risk_score} />
                {riskData.triggered_rules?.length > 0 && (
                  <div className="mt-3 border-t border-ink-800 pt-2.5">
                    <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                      Rules triggered
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {riskData.triggered_rules.map((code) => (
                        <Chip key={code} tone="medium">
                          {code}
                        </Chip>
                      ))}
                    </div>
                  </div>
                )}
                <ProvenanceNote provenance={riskData.provenance} className="mt-3" />
              </>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Risk trajectory"
              subtitle="Weekly average of every recorded assessment. The proactive layer exists to surface a rising line before it becomes a network case."
            />
            {risk.loading && <Skeleton className="h-[200px]" />}
            {riskData?.trajectory?.length > 1 ? (
              <RiskTrajectoryChart trajectory={riskData.trajectory} />
            ) : (
              riskData && (
                <EmptyState
                  title="Not enough history"
                  message="At least two recorded assessments are needed to plot a trajectory."
                />
              )
            )}
          </Card>

          <Card>
            <CardHeader
              icon={Banknote}
              title="Behavioural statistics"
              subtitle="Aggregates computed server-side over the customer's transaction history."
            />
            {profile.loading ? <Skeleton className="h-40" /> : <BehaviourStats behaviour={customer?.behaviour} />}
          </Card>

          <Card padded={false}>
            <div className="p-4 pb-2">
              <CardHeader
                icon={Activity}
                title="Recent transactions"
                action={
                  <Link
                    to={`/transactions?customer=${customerRef}`}
                    className="text-2xs font-medium text-info hover:underline"
                  >
                    View all
                  </Link>
                }
                className="mb-0"
              />
            </div>
            {txns.loading ? (
              <div className="p-4">
                <Skeleton className="h-32" />
              </div>
            ) : txns.data?.items?.length ? (
              <Table>
                <thead>
                  <tr>
                    <Th>Transaction</Th>
                    <Th>Counterparty</Th>
                    <Th align="right">Amount</Th>
                    <Th>Channel</Th>
                    <Th align="right">Risk</Th>
                  </tr>
                </thead>
                <tbody>
                  {txns.data.items.map((txn) => (
                    <Tr key={txn.txn_ref}>
                      <Td mono className="text-slateish-400">
                        {txn.txn_ref}
                      </Td>
                      <Td className="max-w-[180px] truncate">{txn.receiver_name}</Td>
                      <Td align="right" mono className="text-slateish-100">
                        {formatInr(txn.amount)}
                      </Td>
                      <Td>
                        <Chip tone="neutral">{txn.channel}</Chip>
                      </Td>
                      <Td align="right">
                        <RiskBadge level={txn.risk_level} score={txn.risk_score} showScore size="xs" />
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <EmptyState title="No transactions on file" />
            )}
          </Card>
        </div>

        {/* ----------------------------------------------------- right column */}
        <div className="space-y-3">
          <Card>
            <CardHeader title="KYC &amp; relationship" />
            {profile.loading ? (
              <Skeleton className="h-40" />
            ) : (
              customer && (
                <>
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    <Chip tone={customer.kyc_level === 'FULL' ? 'low' : 'medium'}>
                      KYC {customer.kyc_level}
                    </Chip>
                    {customer.pep_flag && <Chip tone="medium">Politically exposed</Chip>}
                    {customer.under_monitoring && <Chip tone="high">Enhanced monitoring</Chip>}
                  </div>
                  <KeyValue label="Reference" value={customer.customer_ref} mono />
                  <KeyValue label="Entity type" value={customer.entity_type} />
                  <KeyValue label="Email" value={customer.email ?? '—'} />
                  <KeyValue label="Phone" value={customer.phone ?? '—'} mono />
                  <KeyValue label="Occupation" value={customer.occupation ?? '—'} />
                  <KeyValue label="Onboarded" value={formatDate(customer.onboarded_on)} />
                  <KeyValue
                    label="Relationship age"
                    value={`${customer.account_age_years.toFixed(1)} years`}
                    mono
                  />
                  <KeyValue
                    label="Higher-risk exposure"
                    value={formatPercent(customer.risk_country_exposure * 100)}
                    mono
                  />
                  <KeyValue
                    label="Prior alerts"
                    value={formatNumber(customer.previous_alert_count)}
                    mono
                  />
                </>
              )
            )}
          </Card>

          <Card>
            <CardHeader icon={Users} title="Accounts" />
            {profile.loading ? (
              <Skeleton className="h-24" />
            ) : customer?.accounts?.length ? (
              <ul className="space-y-2">
                {customer.accounts.map((account) => (
                  <li key={account.account_ref} className="rounded border border-ink-700 bg-ink-900/60 p-2.5">
                    <div className="flex items-center gap-1.5">
                      <Link
                        to={`/network?account=${account.account_ref}`}
                        className="tnum font-mono text-2xs font-semibold text-info hover:underline"
                      >
                        {account.account_ref}
                      </Link>
                      <RiskBadge level={account.risk_level} score={account.risk_score} showScore size="xs" />
                      {account.is_dormant && <Chip tone="medium">dormant</Chip>}
                    </div>
                    <p className="mt-0.5 truncate text-2xs text-slateish-300">
                      {account.display_name}
                    </p>
                    <p className="tnum mt-1 font-mono text-[9.5px] text-slateish-400">
                      {account.institution} · in {formatInr(account.total_in)} / out{' '}
                      {formatInr(account.total_out)} · {account.degree_in + account.degree_out}{' '}
                      connections
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No accounts" />
            )}
          </Card>

          <Card padded={false}>
            <div className="p-4 pb-2">
              <CardHeader icon={BellRing} title="Alert history" className="mb-0" />
            </div>
            {alerts.loading ? (
              <div className="p-4">
                <Skeleton className="h-24" />
              </div>
            ) : alerts.data?.items?.length ? (
              <ul className="divide-y divide-ink-800 border-t border-ink-800">
                {alerts.data.items.map((alert) => (
                  <li key={alert.alert_ref}>
                    <Link
                      to={`/alerts/${alert.alert_ref}`}
                      className="block px-4 py-2.5 transition-colors hover:bg-ink-800/60"
                    >
                      <div className="flex items-center gap-1.5">
                        <RiskBadge level={alert.risk_level} score={alert.risk_score} showScore size="xs" />
                        <Chip tone="neutral">{alert.source}</Chip>
                        <span className="tnum ml-auto font-mono text-[9.5px] text-slateish-400">
                          {alert.alert_ref}
                        </span>
                      </div>
                      <p className="mt-1 line-clamp-2 text-2xs leading-snug text-slateish-300">
                        {alert.title}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No alerts on file" message="This customer has no AML alerts." />
            )}
          </Card>

          {riskData && <Advisory tone="warning">{riskData.advisory}</Advisory>}
        </div>
      </div>
    </>
  )
}
