import clsx from 'clsx'
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BellRing,
  Boxes,
  Gauge,
  LayoutDashboard,
  Minus,
  Network,
  ShieldCheck,
  Siren,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  AlertsTrendChart,
  ChannelChart,
  GeoRiskList,
  RiskDistributionChart,
  RiskTrendChart,
  SuspiciousShareChart,
  VolumeChart,
} from '../charts/index.jsx'
import {
  Advisory,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  PageHeader,
  RiskBadge,
  SegmentedControl,
  Skeleton,
} from '../components/ui.jsx'
import { useApi } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatInr, formatNumber, formatRelative } from '../utils/format.js'

const WINDOWS = [
  { value: '24H', label: '24H' },
  { value: '7D', label: '7D' },
  { value: '30D', label: '30D' },
  { value: '90D', label: '90D' },
]

const LAYER_ICONS = {
  INTEGRITY: ShieldCheck,
  PROACTIVE: Gauge,
  REACTIVE: Siren,
  NETWORK: Network,
}

const LAYER_ROUTES = {
  INTEGRITY: '/gateway',
  PROACTIVE: '/proactive',
  REACTIVE: '/reactive',
  NETWORK: '/network',
}

function KpiCard({ kpi }) {
  const DirIcon =
    kpi.direction === 'up' ? ArrowUpRight : kpi.direction === 'down' ? ArrowDownRight : Minus
  const tone =
    kpi.sentiment === 'bad'
      ? 'text-risk-high'
      : kpi.sentiment === 'good'
        ? 'text-risk-low'
        : 'text-slateish-400'

  return (
    <Card className="min-w-0" title={kpi.hint}>
      <p className="truncate text-2xs uppercase tracking-wide text-slateish-400">{kpi.label}</p>
      <p className="tnum mt-1.5 font-mono text-xl font-semibold leading-none text-white">
        {kpi.display}
      </p>
      <div className="mt-2 flex items-center gap-1.5">
        {kpi.delta_pct !== null && kpi.delta_pct !== undefined ? (
          <span className={clsx('inline-flex items-center gap-0.5 text-2xs font-medium', tone)}>
            <DirIcon size={11} aria-hidden="true" />
            {kpi.delta_pct > 0 ? '+' : ''}
            {kpi.delta_pct}%
          </span>
        ) : (
          <span className="text-2xs text-slateish-400/70">no prior window</span>
        )}
        <span className="truncate text-2xs text-slateish-400/70">vs previous period</span>
      </div>
    </Card>
  )
}

function PipelineStrip({ stages }) {
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
      {(stages ?? []).map((stage, index) => {
        const Icon = LAYER_ICONS[stage.layer] ?? Boxes
        const route = LAYER_ROUTES[stage.layer]
        return (
          <Link
            key={stage.stage}
            to={route ?? '#'}
            className="group relative rounded-card border border-ink-700 bg-ink-850/70 p-3 transition-colors hover:border-info/40 hover:bg-ink-800"
          >
            <div className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded bg-info-soft">
                <Icon size={13} className="text-info" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-2xs font-semibold text-slateish-400">
                    {index + 1}
                  </span>
                  <span className="truncate text-xs font-medium text-slateish-100">
                    {stage.stage}
                  </span>
                </div>
                <p className="tnum mt-1 font-mono text-2xs text-slateish-300">
                  {formatNumber(stage.throughput)} screened ·{' '}
                  <span className="text-risk-medium">{formatNumber(stage.flagged)} flagged</span>
                </p>
                <p className="mt-1 line-clamp-2 text-2xs leading-snug text-slateish-400">
                  {stage.detail}
                </p>
                <div className="mt-1.5">
                  {stage.trained === true && <Chip tone="low">trained model</Chip>}
                  {stage.trained === false && <Chip tone="medium">untrained fallback</Chip>}
                  {stage.trained === null && <Chip tone="neutral">deterministic</Chip>}
                </div>
              </div>
              <ArrowRight
                size={12}
                className="mt-1 shrink-0 text-slateish-400/50 transition-colors group-hover:text-info"
                aria-hidden="true"
              />
            </div>
          </Link>
        )
      })}
    </div>
  )
}

export default function DashboardPage() {
  const [window, setWindow] = useState('7D')
  const { data, error, loading, reload } = useApi(
    (signal) => api.dashboard(window, signal),
    [window],
  )

  return (
    <>
      <PageHeader
        icon={LayoutDashboard}
        title="AML Surveillance Overview"
        subtitle="Consolidated view across transaction integrity, proactive risk detection, reactive monitoring and graph-based network intelligence."
      >
        <SegmentedControl value={window} onChange={setWindow} options={WINDOWS} />
      </PageHeader>

      {error && <ErrorState error={error} onRetry={reload} />}

      {!error && (
        <div className="space-y-4">
          {/* ------------------------------------------------------- KPIs */}
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-7">
            {loading
              ? Array.from({ length: 7 }).map((_, i) => (
                  <Card key={i}>
                    <Skeleton className="h-2.5 w-20" />
                    <Skeleton className="mt-2.5 h-6 w-24" />
                    <Skeleton className="mt-2.5 h-2.5 w-16" />
                  </Card>
                ))
              : data?.kpis?.map((kpi) => <KpiCard key={kpi.key} kpi={kpi} />)}
          </div>

          {/* --------------------------------------------- pipeline health */}
          <section>
            <h2 className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
              Surveillance pipeline
            </h2>
            {loading ? (
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Card key={i}>
                    <Skeleton className="h-14 w-full" />
                  </Card>
                ))}
              </div>
            ) : (
              <PipelineStrip stages={data?.pipeline_health} />
            )}
          </section>

          {/* ------------------------------------------------- risk charts */}
          <div className="grid gap-3 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader
                title="Risk trend over time"
                subtitle="Transactions by assigned risk band across the selected window."
              />
              {loading ? (
                <Skeleton className="h-[230px] w-full" />
              ) : data?.series?.length ? (
                <RiskTrendChart series={data.series} />
              ) : (
                <EmptyState
                  title="No transactions in this window"
                  message="Widen the time range, or run the seed script to populate the demo database."
                />
              )}
            </Card>

            <Card>
              <CardHeader
                title="Risk distribution"
                subtitle="Band thresholds are configurable in Settings."
              />
              {loading ? (
                <Skeleton className="h-[190px] w-full" />
              ) : (
                <>
                  <RiskDistributionChart data={data?.risk_distribution} />
                  <ul className="mt-3 space-y-1.5 border-t border-ink-800 pt-2.5">
                    {data?.risk_distribution?.map((band) => (
                      <li key={band.key} className="flex items-center justify-between gap-2">
                        <RiskBadge level={band.key} />
                        <span className="min-w-0 flex-1 truncate text-2xs text-slateish-400">
                          {band.action}
                        </span>
                        <span className="tnum shrink-0 font-mono text-2xs text-slateish-200">
                          {formatNumber(band.count)} ({band.share}%)
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>
          </div>

          <div className="grid gap-3 xl:grid-cols-3">
            <Card>
              <CardHeader title="Transaction volume" subtitle="Total value screened." />
              {loading ? <Skeleton className="h-[170px]" /> : <VolumeChart series={data?.series} />}
            </Card>
            <Card>
              <CardHeader
                title="Suspicious share"
                subtitle="High + Critical as a percentage of all transactions."
              />
              {loading ? (
                <Skeleton className="h-[170px]" />
              ) : (
                <SuspiciousShareChart series={data?.series} />
              )}
            </Card>
            <Card>
              <CardHeader title="Alerts raised" subtitle="Across all four detection layers." />
              {loading ? (
                <Skeleton className="h-[170px]" />
              ) : (
                <AlertsTrendChart series={data?.series} />
              )}
            </Card>
          </div>

          {/* ------------------------------------- geo / channel / queues */}
          <div className="grid gap-3 xl:grid-cols-3">
            <Card>
              <CardHeader
                title="Geographic risk distribution"
                subtitle="Average risk score by originating location."
              />
              {loading ? (
                <Skeleton className="h-40" />
              ) : data?.geo_risk?.length ? (
                <GeoRiskList data={data.geo_risk} />
              ) : (
                <EmptyState title="No geographic data" />
              )}
            </Card>

            <Card>
              <CardHeader title="Channel breakdown" subtitle="Where the volume flows." />
              {loading ? <Skeleton className="h-[190px]" /> : <ChannelChart data={data?.channel_breakdown} />}
            </Card>

            <Card padded={false}>
              <div className="p-4">
                <CardHeader
                  icon={BellRing}
                  title="Highest-risk open alerts"
                  subtitle="Requiring analyst review."
                  action={
                    <Link to="/alerts" className="text-2xs font-medium text-info hover:underline">
                      All alerts
                    </Link>
                  }
                  className="mb-0"
                />
              </div>
              {loading ? (
                <div className="px-4 pb-4">
                  <Skeleton className="h-40" />
                </div>
              ) : data?.top_alerts?.length ? (
                <ul className="divide-y divide-ink-800 border-t border-ink-800">
                  {data.top_alerts.map((alert) => (
                    <li key={alert.alert_ref}>
                      <Link
                        to={`/alerts/${alert.alert_ref}`}
                        className="block px-4 py-2.5 transition-colors hover:bg-ink-800/60"
                      >
                        <div className="flex items-center gap-2">
                          <RiskBadge level={alert.risk_level} score={alert.risk_score} showScore />
                          <span className="tnum truncate font-mono text-2xs text-slateish-400">
                            {alert.alert_ref}
                          </span>
                          <span className="ml-auto shrink-0 text-2xs text-slateish-400">
                            {formatRelative(alert.raised_at)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-2 text-2xs leading-snug text-slateish-200">
                          {alert.title}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState title="No open alerts" message="The alert queue is clear." />
              )}
            </Card>
          </div>

          {/* ------------------------------------------ suspicious networks */}
          <Card padded={false}>
            <div className="p-4">
              <CardHeader
                icon={Network}
                title="Suspicious financial networks"
                subtitle="Clusters flagged by the graph engine and scored by the GNN. Model-generated indicators requiring investigation."
                action={
                  <Link to="/network" className="text-2xs font-medium text-info hover:underline">
                    Open network view
                  </Link>
                }
                className="mb-0"
              />
            </div>
            {loading ? (
              <div className="px-4 pb-4">
                <Skeleton className="h-24" />
              </div>
            ) : data?.suspicious_networks?.length ? (
              <div className="grid gap-2 border-t border-ink-800 p-3 md:grid-cols-2 xl:grid-cols-3">
                {data.suspicious_networks.map((net) => (
                  <Link
                    key={net.network_ref}
                    to={`/network?network=${net.network_ref}`}
                    className="rounded border border-ink-700 bg-ink-800/50 p-3 transition-colors hover:border-risk-high/40 hover:bg-ink-800"
                  >
                    <div className="flex items-center gap-2">
                      <span className="tnum font-mono text-2xs font-semibold text-slateish-100">
                        {net.network_ref}
                      </span>
                      <Chip tone="accent">{net.pattern}</Chip>
                      <RiskBadge
                        level={net.risk_level}
                        score={net.risk_score}
                        showScore
                        size="xs"
                      />
                    </div>
                    <p className="tnum mt-1.5 font-mono text-2xs text-slateish-400">
                      {net.node_count} accounts · {net.edge_count} transfers ·{' '}
                      {formatInr(net.total_flow)}
                    </p>
                    <p className="mt-1 line-clamp-2 text-2xs leading-snug text-slateish-400">
                      {net.summary}
                    </p>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={Network}
                title="No suspicious networks detected"
                message="Run the network analysis sweep from the GNN Network page."
              />
            )}
          </Card>

          {data && (
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Advisory className="flex-1">{data.advisory}</Advisory>
              <span className="tnum shrink-0 font-mono text-2xs text-slateish-400/70">
                generated {formatDateTime(data.generated_at)}
              </span>
            </div>
          )}
        </div>
      )}
    </>
  )
}
