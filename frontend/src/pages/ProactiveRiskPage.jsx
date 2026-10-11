/**
 * Proactive Risk Intelligence.
 *
 * The question this page answers: "is this customer becoming risky?" - measured
 * BEFORE a transaction is authorised, from behavioural drift against the
 * customer's own baseline.
 */
import { Activity, ArrowRight, Gauge, TrendingUp, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { PortfolioTrendChart, RiskTrajectoryChart } from '../charts/index.jsx'
import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  FactorList,
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
import { formatInr, formatMultiple, formatNumber } from '../utils/format.js'

const BAND_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']

export default function ProactiveRiskPage() {
  const overview = useApi((signal) => api.proactiveOverview({ limit: 30 }, signal), [])
  const [selected, setSelected] = useState(null)

  // Default the trajectory panel to the highest-risk customer on the watchlist
  useEffect(() => {
    if (!selected && overview.data?.watchlist?.length) {
      setSelected(overview.data.watchlist[0].customer_ref)
    }
  }, [overview.data, selected])

  const detail = useApi((signal) => api.customerRisk(selected, signal), [selected], {
    enabled: Boolean(selected),
  })

  const data = overview.data

  return (
    <>
      <PageHeader
        icon={Gauge}
        title="Proactive Risk Intelligence"
        subtitle="Monitors customer behaviour before transactions occur. A rising trajectory indicates emerging risk that warrants enhanced due diligence - not a conclusion about the customer."
      />

      {overview.error && <ErrorState error={overview.error} onRetry={overview.reload} />}

      {!overview.error && (
        <div className="space-y-3">
          {/* --------------------------------------------------- summary row */}
          <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
            {overview.loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <Card key={i}>
                  <Skeleton className="h-14" />
                </Card>
              ))
            ) : (
              <>
                <Card>
                  <p className="text-2xs uppercase tracking-wide text-slateish-400">
                    Under monitoring
                  </p>
                  <p className="tnum mt-1.5 font-mono text-xl font-semibold text-white">
                    {formatNumber(data.total_monitored)}
                  </p>
                  <p className="mt-1 text-2xs text-slateish-400/80">
                    customers on enhanced monitoring
                  </p>
                </Card>
                <Card>
                  <p className="text-2xs uppercase tracking-wide text-slateish-400">
                    Escalating trajectory
                  </p>
                  <p className="tnum mt-1.5 font-mono text-xl font-semibold text-risk-high">
                    {formatNumber(data.escalating_count)}
                  </p>
                  <p className="mt-1 text-2xs text-slateish-400/80">risk trending upward</p>
                </Card>
                <Card>
                  <p className="text-2xs uppercase tracking-wide text-slateish-400">
                    Portfolio average risk
                  </p>
                  <p className="tnum mt-1.5 font-mono text-xl font-semibold text-white">
                    {data.avg_risk_score}
                    <span className="text-sm text-slateish-400">/100</span>
                  </p>
                  <p className="mt-1 text-2xs text-slateish-400/80">across all customers</p>
                </Card>
                <Card>
                  <p className="mb-1.5 text-2xs uppercase tracking-wide text-slateish-400">
                    Risk band distribution
                  </p>
                  <div className="space-y-1">
                    {BAND_ORDER.map((band) => (
                      <div key={band} className="flex items-center gap-2">
                        <RiskBadge level={band} size="xs" />
                        <span className="tnum ml-auto font-mono text-2xs text-slateish-200">
                          {formatNumber(data.band_counts?.[band] ?? 0)}
                        </span>
                      </div>
                    ))}
                  </div>
                </Card>
              </>
            )}
          </div>

          <Card>
            <CardHeader
              icon={TrendingUp}
              title="Portfolio risk trend"
              subtitle="Weekly average of every proactive assessment recorded across the customer base."
            />
            {overview.loading ? (
              <Skeleton className="h-[180px]" />
            ) : data.portfolio_trend?.length > 1 ? (
              <PortfolioTrendChart points={data.portfolio_trend} />
            ) : (
              <EmptyState title="Not enough assessment history to plot a portfolio trend" />
            )}
          </Card>

          <div className="grid gap-3 xl:grid-cols-[1fr_400px]">
            {/* ------------------------------------------------ watchlist */}
            <Card padded={false} className="overflow-hidden">
              <div className="p-4 pb-2">
                <CardHeader
                  icon={Users}
                  title="Proactive watchlist"
                  subtitle="Ranked by current behavioural risk. Select a customer to see their trajectory."
                  className="mb-0"
                />
              </div>
              {overview.loading ? (
                <div className="p-4">
                  <Skeleton className="h-64" />
                </div>
              ) : data.watchlist?.length ? (
                <Table>
                  <thead>
                    <tr>
                      <Th>Customer</Th>
                      <Th>Name</Th>
                      <Th align="right">Risk</Th>
                      <Th>Trend</Th>
                      <Th align="right">Δ recent</Th>
                      <Th>Strongest contributor</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.watchlist.map((row) => (
                      <Tr
                        key={row.customer_ref}
                        onClick={() => setSelected(row.customer_ref)}
                        selected={selected === row.customer_ref}
                      >
                        <Td mono className="text-slateish-300">
                          {row.customer_ref}
                        </Td>
                        <Td className="max-w-[150px] truncate font-medium text-slateish-100">
                          <span className="flex items-center gap-1.5">
                            {row.name}
                            {row.monitored && (
                              <Chip tone="high" title="Under enhanced monitoring">
                                mon
                              </Chip>
                            )}
                          </span>
                        </Td>
                        <Td align="right">
                          <div className="flex items-center justify-end gap-1.5">
                            <span className="tnum font-mono font-medium text-slateish-100">
                              {Math.round(row.risk_score)}
                            </span>
                            <RiskBadge level={row.risk_level} size="xs" />
                          </div>
                        </Td>
                        <Td>
                          <TrendIndicator trend={row.trend} />
                        </Td>
                        <Td align="right" mono>
                          <span
                            className={
                              row.delta_30d > 0
                                ? 'text-risk-high'
                                : row.delta_30d < 0
                                  ? 'text-risk-low'
                                  : 'text-slateish-400'
                            }
                          >
                            {row.delta_30d > 0 ? '+' : ''}
                            {row.delta_30d}
                          </span>
                        </Td>
                        <Td className="max-w-[210px] truncate text-slateish-400">
                          {row.top_factor}
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <EmptyState title="No customers to display" />
              )}
            </Card>

            {/* ------------------------------------------- selected customer */}
            <div className="space-y-3">
              {!selected && (
                <Card>
                  <EmptyState
                    icon={Gauge}
                    title="Select a customer"
                    message="Pick a customer from the watchlist to see their risk trajectory and the factors driving it."
                  />
                </Card>
              )}

              {selected && (
                <>
                  <Card>
                    <CardHeader
                      title={detail.data ? detail.data.name : selected}
                      subtitle={`${selected} · risk trajectory`}
                      action={
                        <Link
                          to={`/customers/${selected}`}
                          className="inline-flex items-center gap-1 text-2xs font-medium text-info hover:underline"
                        >
                          Full profile <ArrowRight size={11} aria-hidden="true" />
                        </Link>
                      }
                    />
                    {detail.loading && <Skeleton className="h-[200px]" />}
                    {detail.error && <ErrorState error={detail.error} onRetry={detail.reload} />}
                    {detail.data && (
                      <>
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                          <RiskBadge
                            level={detail.data.risk_level}
                            score={detail.data.risk_score}
                            showScore
                          />
                          <TrendIndicator trend={detail.data.trend} />
                          <Chip tone="neutral">action: {detail.data.decision}</Chip>
                        </div>
                        <ScoreMeter
                          score={detail.data.risk_score}
                          level={detail.data.risk_level}
                          className="mb-3"
                        />
                        {detail.data.trajectory?.length > 1 ? (
                          <RiskTrajectoryChart trajectory={detail.data.trajectory} height={180} />
                        ) : (
                          <EmptyState
                            title="Not enough history"
                            message="At least two assessments are needed for a trajectory."
                          />
                        )}
                      </>
                    )}
                  </Card>

                  {detail.data && (
                    <>
                      <Card>
                        <CardHeader
                          title="Why this score"
                          subtitle="Contributions sum to the score shown above."
                        />
                        <FactorList
                          factors={detail.data.factors}
                          total={detail.data.risk_score}
                          title=""
                        />
                      </Card>

                      <Card>
                        <CardHeader title="Behavioural snapshot" />
                        <div className="space-y-1">
                          {[
                            ['Average transaction', formatInr(detail.data.behaviour.avg_transaction_amount)],
                            ['Baseline average', formatInr(detail.data.behaviour.baseline_avg_amount)],
                            [
                              'Deviation',
                              formatMultiple(detail.data.behaviour.amount_deviation_ratio),
                            ],
                            [
                              'Transactions / month',
                              formatNumber(detail.data.behaviour.transactions_per_month, 1),
                            ],
                            [
                              'Unique counterparties',
                              formatNumber(detail.data.behaviour.unique_counterparties),
                            ],
                            [
                              'New counterparties (30d)',
                              formatNumber(detail.data.behaviour.new_counterparties_30d),
                            ],
                            ['Velocity', detail.data.behaviour.velocity_label],
                            ['Prior alerts', formatNumber(detail.data.behaviour.previous_alerts)],
                          ].map(([label, value]) => (
                            <div
                              key={label}
                              className="flex items-baseline justify-between gap-3 border-b border-ink-800/70 py-1"
                            >
                              <span className="text-2xs text-slateish-400">{label}</span>
                              <span className="tnum font-mono text-xs text-slateish-100">
                                {value}
                              </span>
                            </div>
                          ))}
                        </div>
                      </Card>

                      <ProvenanceNote provenance={detail.data.provenance} />
                    </>
                  )}
                </>
              )}
            </div>
          </div>

          {data && <Advisory tone="warning">{data.advisory}</Advisory>}
        </div>
      )}
    </>
  )
}
