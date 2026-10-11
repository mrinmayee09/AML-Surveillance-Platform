/**
 * Financial Network Intelligence.
 *
 * Left rail lists detected clusters; the canvas renders the selected cluster (or
 * an ad-hoc neighbourhood); the right panel explains the GNN's assessment with
 * the measured quantities behind each signal.
 */
import clsx from 'clsx'
import {
  BrainCircuit,
  Crosshair,
  ExternalLink,
  Filter,
  Focus,
  Layers,
  Network as NetworkIcon,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

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
  PageHeader,
  ProvenanceNote,
  RiskBadge,
  ScoreMeter,
  Select,
  Skeleton,
  Spinner,
} from '../components/ui.jsx'
import NetworkGraph, { GraphLegend } from '../graph/NetworkGraph.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import {
  ALERTS_CHANGED_EVENT,
  notifyAlertsChanged,
  useApi,
  useMutation,
} from '../hooks/useApi.js'
import { api } from '../services/api.js'
import {
  entityLabel,
  formatDateTime,
  formatInr,
  formatNumber,
  humanise,
  patternLabel,
} from '../utils/format.js'

const RISK_FILTERS = [
  { value: '0', label: 'All node scores' },
  { value: '35', label: 'Score ≥ 35 (Medium+)' },
  { value: '60', label: 'Score ≥ 60 (High+)' },
  { value: '85', label: 'Score ≥ 85 (Critical)' },
]
const AMOUNT_FILTERS = [
  { value: '0', label: 'Any amount' },
  { value: '100000', label: '≥ ₹1 L' },
  { value: '1000000', label: '≥ ₹10 L' },
  { value: '5000000', label: '≥ ₹50 L' },
]
const HOP_OPTIONS = [
  { value: '1', label: '1 hop' },
  { value: '2', label: '2 hops' },
  { value: '3', label: '3 hops' },
]

/* --------------------------------------------------------- cluster sidebar */

function ClusterList({ networks, selected, onSelect, loading }) {
  if (loading) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
    )
  }
  if (!networks?.length) {
    return (
      <EmptyState
        icon={NetworkIcon}
        title="No clusters detected"
        message="Run the detection sweep to build the graph and score it."
      />
    )
  }
  return (
    <ul className="divide-y divide-ink-800">
      {networks.map((net) => (
        <li key={net.network_ref}>
          <button
            type="button"
            onClick={() => onSelect(net.network_ref)}
            className={clsx(
              'w-full px-3 py-2.5 text-left transition-colors',
              selected === net.network_ref
                ? 'bg-info-soft ring-1 ring-inset ring-info/30'
                : 'hover:bg-ink-800/60',
            )}
          >
            <div className="flex items-center gap-1.5">
              <span className="tnum font-mono text-2xs font-semibold text-slateish-100">
                {net.network_ref}
              </span>
              {net.is_suspicious && (
                <Chip tone="high" className="ml-auto">
                  flagged
                </Chip>
              )}
            </div>
            <div className="mt-1 flex items-center gap-1.5">
              <Chip tone="accent">{patternLabel(net.pattern)}</Chip>
              <RiskBadge level={net.risk_level} score={net.risk_score} showScore size="xs" />
            </div>
            <p className="tnum mt-1 font-mono text-[9.5px] text-slateish-400">
              {net.node_count} accounts · {net.edge_count} transfers · {formatInr(net.total_flow)}
            </p>
          </button>
        </li>
      ))}
    </ul>
  )
}

/* ------------------------------------------------- GraphSAGE verdict panel */

function formatAmount(amount, currency) {
  return currency === 'INR' ? formatInr(amount) : `${currency} ${formatNumber(amount, 2)}`
}

/** The trained GraphSAGE model's score for one account, and the transfers behind it. */
function GraphSageVerdict({ accountRef }) {
  const { data, error, loading } = useApi(
    (signal) => api.gnnAccount(accountRef, signal),
    [accountRef],
    { enabled: Boolean(accountRef), refetchOn: ALERTS_CHANGED_EVENT },
  )

  return (
    <div className="rounded border border-ink-700 bg-ink-900/60 p-2.5">
      <h4 className="mb-1.5 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
        <BrainCircuit size={12} aria-hidden="true" /> GraphSAGE model (trained on IBM AMLworld)
      </h4>
      {loading && <Skeleton className="h-16" />}
      {error && (
        <p className="text-2xs text-slateish-400">
          {error.status === 404
            ? 'Not scored yet. Use "Run GNN scoring" once the model has been trained.'
            : error.message}
        </p>
      )}
      {data && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="tnum font-mono text-xs font-semibold text-slateish-100">
              {(data.score * 100).toFixed(1)}%
            </span>
            <span className="text-2xs text-slateish-400">
              threshold {(data.threshold * 100).toFixed(1)}%
            </span>
            <Chip tone={data.flagged ? 'high' : 'low'}>
              {data.flagged ? 'flagged' : 'below threshold'}
            </Chip>
          </div>
          <p className="text-[9.5px] text-slateish-400">
            7-day neighbourhood of {data.window_nodes} accounts and {data.window_edges} transfers
          </p>
          {data.top_transfers.length > 0 ? (
            <div>
              <p className="mb-1 text-2xs font-medium text-slateish-300">
                Score rests mainly on these transfers
              </p>
              <ul className="space-y-1">
                {data.top_transfers.map((t) => (
                  <li key={t.txn_ref} className="rounded bg-ink-950/60 px-2 py-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <Link
                        to={`/transactions?search=${encodeURIComponent(t.txn_ref)}`}
                        className="tnum font-mono text-[10px] font-semibold text-info hover:underline"
                      >
                        #{t.rank} {t.txn_ref}
                      </Link>
                      <span className="tnum font-mono text-[10px] text-risk-medium">
                        -{(t.score_drop * 100).toFixed(1)} pts
                      </span>
                    </div>
                    <p className="tnum font-mono text-[9.5px] text-slateish-400">
                      {t.sender} → {t.receiver} · {formatAmount(t.amount, t.currency)} ·{' '}
                      {formatDateTime(t.occurred_at)}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-2xs text-slateish-400">No single transfer drives this score.</p>
          )}
          <p className="text-[9px] leading-snug text-slateish-500">{data.note}</p>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------- node inspect panel */

function NodePanel({ accountRef, hops, onClose, onFocus, focused }) {
  const { data, error, loading } = useApi(
    (signal) => api.inspectNode(accountRef, { hops: Number(hops) }, signal),
    [accountRef, hops],
    { enabled: Boolean(accountRef) },
  )

  if (!accountRef) return null

  return (
    <Card padded={false} className="overflow-hidden">
      <div className="flex items-start justify-between gap-2 border-b border-ink-800 p-3">
        <div className="min-w-0">
          <p className="tnum font-mono text-xs font-semibold text-slateish-100">{accountRef}</p>
          <p className="text-2xs text-slateish-400">Selected account</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            size="xs"
            variant={focused ? 'primary' : 'ghost'}
            icon={Focus}
            onClick={onFocus}
            title="Highlight only this account's direct neighbours"
          >
            {focused ? 'Focused' : 'Neighbours'}
          </Button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="rounded p-1 text-slateish-400 hover:bg-ink-800 hover:text-slateish-100"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      <div className="max-h-[520px] overflow-y-auto p-3">
        {loading && <Skeleton className="h-40" />}
        {error && <ErrorState error={error} />}
        {data?.node && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip tone="neutral">{entityLabel(data.node.entity_type)}</Chip>
              <RiskBadge
                level={data.node.risk_level}
                score={data.node.gnn_node_score}
                showScore
              />
              {data.node.is_suspicious && <Chip tone="high">model-flagged</Chip>}
            </div>

            <ScoreMeter
              score={data.node.gnn_node_score}
              level={data.node.risk_level}
              label="Structural graph score"
            />

            <GraphSageVerdict accountRef={accountRef} />

            <div className="rounded border border-ink-700 bg-ink-900/60 p-2.5">
              <KeyValue label="Display name" value={data.node.label} />
              <KeyValue label="Institution" value={data.node.institution} />
              <KeyValue
                label="Location"
                value={`${data.node.city}, ${data.node.country}`}
              />
              <KeyValue label="Inbound" value={formatInr(data.node.total_in)} mono />
              <KeyValue label="Outbound" value={formatInr(data.node.total_out)} mono />
              <KeyValue label="Throughput" value={formatInr(data.node.volume)} mono />
              <KeyValue
                label="Connections"
                value={`${data.node.connections} (${data.node.degree_in} in / ${data.node.degree_out} out)`}
                mono
              />
              {data.node.customer_ref && (
                <div className="mt-1.5 border-t border-ink-800 pt-1.5">
                  <Link
                    to={`/customers/${data.node.customer_ref}`}
                    className="inline-flex items-center gap-1 text-2xs font-medium text-info hover:underline"
                  >
                    Open customer {data.node.customer_ref}
                    <ExternalLink size={10} aria-hidden="true" />
                  </Link>
                </div>
              )}
            </div>

            {data.gnn_signals?.length > 0 && (
              <div>
                <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                  Neighbourhood signals
                </h4>
                <ul className="space-y-1.5">
                  {data.gnn_signals.slice(0, 6).map((sig) => (
                    <li key={sig.code} className="rounded bg-ink-900/60 px-2 py-1.5">
                      <div className="flex items-baseline gap-2">
                        <span className="tnum font-mono text-2xs font-semibold text-risk-medium">
                          +{sig.contribution}
                        </span>
                        <span className="text-2xs font-medium text-slateish-200">{sig.label}</span>
                      </div>
                      <p className="mt-0.5 text-[9.5px] leading-snug text-slateish-400">
                        {sig.detail}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {data.networks?.length > 0 && (
              <div>
                <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                  Cluster membership
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {data.networks.map((net) => (
                    <Chip key={net.network_ref} tone={net.is_suspicious ? 'high' : 'neutral'}>
                      {net.network_ref} · {net.pattern}
                    </Chip>
                  ))}
                </div>
              </div>
            )}

            {data.recent_transactions?.length > 0 && (
              <div>
                <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                  Recent transactions
                </h4>
                <ul className="space-y-1">
                  {data.recent_transactions.slice(0, 8).map((txn) => (
                    <li
                      key={txn.txn_ref}
                      className="flex items-center gap-2 rounded bg-ink-900/60 px-2 py-1 text-2xs"
                    >
                      <Chip tone={txn.direction === 'OUT' ? 'medium' : 'info'}>
                        {txn.direction}
                      </Chip>
                      <span className="tnum font-mono text-slateish-100">
                        {formatInr(txn.amount)}
                      </span>
                      <span className="ml-auto shrink-0 text-slateish-400">{txn.channel}</span>
                      <RiskBadge level={txn.risk_level} size="xs" />
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <p className="border-t border-ink-800 pt-2 text-[9.5px] leading-relaxed text-slateish-400/80">
              {data.disclaimer}
            </p>
          </div>
        )}
      </div>
    </Card>
  )
}

/* --------------------------------------------------------- assessment panel */

function AssessmentPanel({ assessment, network }) {
  if (!assessment) return null
  return (
    <Card>
      <CardHeader
        icon={Sparkles}
        title="GNN risk assessment"
        subtitle="Contributing signals, each backed by a measured graph quantity."
      />
      <ScoreMeter
        score={assessment.network_risk}
        level={assessment.risk_level}
        label="Network risk"
        className="mb-3"
      />

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <Chip tone="accent">{patternLabel(assessment.pattern)}</Chip>
        {network && (
          <>
            <Chip tone="neutral">{network.node_count} accounts</Chip>
            <Chip tone="neutral">{network.edge_count} transfers</Chip>
            <Chip tone="neutral">{formatInr(network.total_flow)} total flow</Chip>
          </>
        )}
      </div>

      <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
        Contributing signals
      </h4>
      <ul className="mb-3 divide-y divide-ink-800">
        {assessment.signals.map((sig) => (
          <li key={sig.code} className="py-2">
            <div className="flex items-baseline gap-2">
              <span className="tnum w-9 shrink-0 text-right font-mono text-2xs font-semibold text-risk-medium">
                +{sig.contribution}
              </span>
              <div className="min-w-0">
                <p className="text-xs font-medium text-slateish-100">{sig.label}</p>
                <p className="mt-0.5 text-2xs leading-snug text-slateish-400">{sig.detail}</p>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {assessment.top_nodes?.length > 0 && (
        <div className="mb-3">
          <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
            Highest-scoring participants
          </h4>
          <ul className="space-y-1">
            {assessment.top_nodes.map((node) => (
              <li
                key={node.account_ref}
                className="flex items-center gap-2 rounded bg-ink-900/60 px-2 py-1 text-2xs"
              >
                <span className="tnum font-mono text-slateish-100">{node.account_ref}</span>
                <Chip tone="neutral">{humanise(node.role)}</Chip>
                <span className="tnum ml-auto shrink-0 font-mono text-risk-high">
                  {Math.round(node.gnn_node_score)}/100
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {assessment.structural_metrics && (
        <details className="mb-3 rounded border border-ink-700 bg-ink-900/60">
          <summary className="cursor-pointer px-2.5 py-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400 hover:text-slateish-200">
            Measured structural metrics
          </summary>
          <div className="border-t border-ink-800 px-2.5 py-2">
            {Object.entries(assessment.structural_metrics).map(([key, value]) => (
              <KeyValue
                key={key}
                label={humanise(key)}
                value={typeof value === 'number' ? formatNumber(value, 2) : String(value)}
                mono
              />
            ))}
          </div>
        </details>
      )}

      <ProvenanceNote provenance={assessment.provenance} className="mb-2" />
      <Advisory tone="warning" className="!text-[10px]">
        {assessment.disclaimer}
      </Advisory>
    </Card>
  )
}

/* -------------------------------------------------------------------- page */

export default function NetworkPage() {
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const { can } = useAuth()
  const canSweep = can('alerts:update')

  const [selectedNetwork, setSelectedNetwork] = useState(params.get('network') ?? '')
  const [accountSearch, setAccountSearch] = useState(params.get('account') ?? '')
  const [exploreAccount, setExploreAccount] = useState(params.get('account') ?? '')
  const [hops, setHops] = useState('2')
  const [minRisk, setMinRisk] = useState('0')
  const [minAmount, setMinAmount] = useState('0')
  const [suspiciousOnly, setSuspiciousOnly] = useState(true)
  const [selectedNode, setSelectedNode] = useState(null)
  const [focusNeighbours, setFocusNeighbours] = useState(false)

  const networksQuery = useApi(
    (signal) => api.networks({ suspicious_only: suspiciousOnly, page_size: 60 }, signal),
    [suspiciousOnly],
  )
  const networks = networksQuery.data?.items ?? networksQuery.data ?? []

  // Default to the highest-risk cluster
  useEffect(() => {
    if (!selectedNetwork && !exploreAccount && networks.length) {
      setSelectedNetwork(networks[0].network_ref)
    }
  }, [networks, selectedNetwork, exploreAccount])

  // Only the inputs the active endpoint actually takes. A cluster graph ignores
  // hops/risk/amount (those filter client-side below), so changing them must not
  // refetch it.
  const graphKey = JSON.stringify(
    exploreAccount
      ? ['account', exploreAccount, hops, minRisk, minAmount]
      : selectedNetwork
        ? ['network', selectedNetwork]
        : ['overview', minRisk, minAmount],
  )
  const graphQuery = useApi(
    (signal) => {
      if (exploreAccount) {
        return api.exploreGraph(
          {
            account_ref: exploreAccount,
            hops: Number(hops),
            min_risk: Number(minRisk),
            min_amount: Number(minAmount),
          },
          signal,
        )
      }
      if (selectedNetwork) return api.networkGraph(selectedNetwork, signal)
      return api.exploreGraph({ min_risk: Number(minRisk), min_amount: Number(minAmount) }, signal)
    },
    [graphKey],
  )

  const graph = graphQuery.data
  const activeNetwork = networks.find((n) => n.network_ref === selectedNetwork)

  // Client-side filters on top of the server payload, so the canvas reacts instantly
  const filteredNodes = useMemo(
    () => (graph?.nodes ?? []).filter((n) => n.gnn_node_score >= Number(minRisk)),
    [graph, minRisk],
  )
  const visibleIds = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes])
  const filteredEdges = useMemo(
    () =>
      (graph?.edges ?? []).filter(
        (e) =>
          e.amount >= Number(minAmount) && visibleIds.has(e.source) && visibleIds.has(e.target),
      ),
    [graph, minAmount, visibleIds],
  )

  const runAnalysis = useMutation(async () => {
    const result = await api.runNetworkAnalysis({ raise_alerts: true })
    toast.success(
      `Detected ${result.clusters_detected} cluster(s), ${result.clusters_suspicious} flagged. ` +
        (result.alerts_created > 0
          ? `${result.alerts_created} new alert(s) raised; clusters already alerted were refreshed.`
          : 'No new alerts; clusters already alerted were refreshed.'),
      { title: 'Graph analysis complete' },
    )
    networksQuery.reload()
    graphQuery.reload()
    notifyAlertsChanged()
    return result
  })

  const runGnn = useMutation(async () => {
    const result = await api.runGnnScoring({ hours: 24 })
    toast.success(
      `${result.scored} account(s) active in the last 24h of activity scored; ${result.flagged} above the model's threshold.`,
      { title: 'GraphSAGE scoring complete' },
    )
    notifyAlertsChanged()
    return result
  })

  function startGnnScoring() {
    runGnn.run().catch((err) => {
      toast.error(err?.message ?? 'GNN scoring failed.', { title: 'GraphSAGE scoring failed' })
    })
  }

  function startAnalysis() {
    runAnalysis.run().catch((err) => {
      toast.error(err?.message ?? 'The detection sweep failed.', {
        title: 'Graph analysis failed',
      })
    })
  }

  function investigateNetwork(ref) {
    setExploreAccount('')
    setAccountSearch('')
    setSelectedNetwork(ref)
    setSelectedNode(null)
    setFocusNeighbours(false)
    params.set('network', ref)
    params.delete('account')
    setParams(params)
  }

  function onSearchAccount(event) {
    event.preventDefault()
    const value = accountSearch.trim().toUpperCase()
    if (!value) return
    setExploreAccount(value)
    setSelectedNetwork('')
    setSelectedNode(value)
    params.set('account', value)
    params.delete('network')
    setParams(params)
  }

  function clearExploration() {
    setExploreAccount('')
    setAccountSearch('')
    setSelectedNode(null)
    setFocusNeighbours(false)
    params.delete('account')
    setParams(params)
  }

  return (
    <>
      <PageHeader
        icon={NetworkIcon}
        title="Financial Network Intelligence"
        subtitle="Graph construction → structural typology detection → GNN inference → suspicious nodes, edges and subgraphs. Findings are model-generated indicators requiring investigation."
      >
        {canSweep && (
          <Button
            variant="secondary"
            icon={RefreshCw}
            loading={runAnalysis.pending}
            onClick={startAnalysis}
            title="Rebuild the graph, re-detect typologies and re-score with the GNN"
          >
            {runAnalysis.pending ? 'Analysing…' : 'Run detection sweep'}
          </Button>
        )}
        {canSweep && (
          <Button
            variant="secondary"
            icon={BrainCircuit}
            loading={runGnn.pending}
            onClick={startGnnScoring}
            title="Score recently active accounts with the trained GraphSAGE model"
          >
            {runGnn.pending ? 'Scoring…' : 'Run GNN scoring'}
          </Button>
        )}
      </PageHeader>

      <div className="grid gap-3 xl:grid-cols-[270px_1fr_340px]">
        {/* ------------------------------------------------ cluster sidebar */}
        <Card padded={false} className="overflow-hidden xl:max-h-[calc(100vh-190px)]">
          <div className="border-b border-ink-800 p-3">
            <CardHeader
              icon={Layers}
              title="Detected clusters"
              subtitle={`${networks.length} cluster(s)`}
              className="mb-2"
            />
            <label className="flex items-center gap-2 text-2xs text-slateish-300">
              <input
                type="checkbox"
                checked={suspiciousOnly}
                onChange={(e) => setSuspiciousOnly(e.target.checked)}
                className="h-3 w-3 rounded border-ink-600 bg-ink-900 accent-info"
              />
              Flagged clusters only
            </label>
          </div>
          <div className="overflow-y-auto">
            <ClusterList
              networks={networks}
              selected={selectedNetwork}
              onSelect={investigateNetwork}
              loading={networksQuery.loading}
            />
          </div>
        </Card>

        {/* -------------------------------------------------------- canvas */}
        <div className="space-y-3">
          <Card padded={false} className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-2.5">
              <form onSubmit={onSearchAccount} className="relative">
                <Search
                  size={12}
                  className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-slateish-400"
                  aria-hidden="true"
                />
                <input
                  value={accountSearch}
                  onChange={(e) => setAccountSearch(e.target.value)}
                  placeholder="Find account (ACC-…)"
                  aria-label="Search for an account"
                  className="w-44 rounded border border-ink-600 bg-ink-900 py-1 pl-6.5 pr-2 text-2xs text-slateish-100 placeholder:text-slateish-400/70 focus:border-info/60 focus:outline-none"
                  style={{ paddingLeft: '1.6rem' }}
                />
              </form>
              {exploreAccount && (
                <>
                  <Select
                    value={hops}
                    onChange={(e) => setHops(e.target.value)}
                    options={HOP_OPTIONS}
                    aria-label="Expand by hops"
                  />
                  <Button size="xs" variant="ghost" icon={X} onClick={clearExploration}>
                    Exit exploration
                  </Button>
                </>
              )}
              <span className="mx-1 h-4 w-px bg-ink-700" aria-hidden="true" />
              <Filter size={12} className="text-slateish-400" aria-hidden="true" />
              <Select
                value={minRisk}
                onChange={(e) => setMinRisk(e.target.value)}
                options={RISK_FILTERS}
                aria-label="Filter by node risk"
              />
              <Select
                value={minAmount}
                onChange={(e) => setMinAmount(e.target.value)}
                options={AMOUNT_FILTERS}
                aria-label="Filter by transfer amount"
              />
              <span className="tnum ml-auto font-mono text-2xs text-slateish-400">
                {filteredNodes.length} nodes · {filteredEdges.length} edges
              </span>
            </div>

            <div className="relative h-[540px] w-full">
              {graphQuery.loading && (
                <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 bg-ink-950/70 text-slateish-400">
                  <Spinner size={18} />
                  <span className="text-xs">Building graph…</span>
                </div>
              )}
              {graphQuery.error && <ErrorState error={graphQuery.error} onRetry={graphQuery.reload} />}
              {!graphQuery.error && filteredNodes.length === 0 && !graphQuery.loading && (
                <EmptyState
                  icon={NetworkIcon}
                  title="Nothing to display"
                  message="No node meets the current filters. Lower the risk threshold or run the detection sweep."
                />
              )}
              {!graphQuery.error && filteredNodes.length > 0 && (
                <NetworkGraph
                  nodes={filteredNodes}
                  edges={filteredEdges}
                  selectedNodeId={selectedNode ?? null}
                  layoutKey={graphKey}
                  focusNeighboursOf={focusNeighbours ? selectedNode : null}
                  onNodeSelect={(node) => {
                    setSelectedNode(node.account_ref)
                  }}
                  onEdgeSelect={(edge) => {
                    if (edge?.transaction_ref) {
                      toast.info(
                        `${edge.transaction_ref} · ${formatInr(edge.amount)} · edge score ${edge.gnn_edge_score}/100`,
                        { title: 'Transfer selected' },
                      )
                    }
                  }}
                />
              )}
            </div>

            <div className="border-t border-ink-800 p-2.5">
              <GraphLegend />
            </div>
          </Card>

          {activeNetwork && (
            <Card>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-semibold text-slateish-100">
                      {activeNetwork.label}
                    </h3>
                    <RiskBadge
                      level={activeNetwork.risk_level}
                      score={activeNetwork.risk_score}
                      showScore
                    />
                  </div>
                  <p className="mt-1 text-2xs leading-snug text-slateish-400">
                    {activeNetwork.summary}
                  </p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Link
                    to={`/investigations?network=${activeNetwork.network_ref}`}
                    className="inline-flex items-center gap-1.5 rounded border border-info bg-info px-2.5 py-1.5 text-xs font-medium text-white hover:bg-info/85"
                  >
                    <Crosshair size={13} aria-hidden="true" /> Investigate network
                  </Link>
                </div>
              </div>
              <DataList
                className="mt-3 border-t border-ink-800 pt-3"
                columns={3}
                items={[
                  { label: 'Pattern', value: patternLabel(activeNetwork.pattern) },
                  { label: 'Accounts', value: formatNumber(activeNetwork.node_count), mono: true },
                  { label: 'Transfers', value: formatNumber(activeNetwork.edge_count), mono: true },
                  { label: 'Total flow', value: formatInr(activeNetwork.total_flow), mono: true },
                  {
                    label: 'Detected',
                    value: formatDateTime(activeNetwork.detected_at),
                    mono: true,
                  },
                  {
                    label: 'Flagged nodes / edges',
                    value: `${graph?.stats?.suspicious_nodes ?? 0} / ${graph?.stats?.suspicious_edges ?? 0}`,
                    mono: true,
                  },
                ]}
              />
            </Card>
          )}
        </div>

        {/* -------------------------------------------------- right column */}
        <div className="space-y-3 xl:max-h-[calc(100vh-190px)] xl:overflow-y-auto">
          {selectedNode && (
            <NodePanel
              accountRef={selectedNode}
              hops={hops}
              focused={focusNeighbours}
              onFocus={() => setFocusNeighbours((v) => !v)}
              onClose={() => {
                setSelectedNode(null)
                setFocusNeighbours(false)
              }}
            />
          )}

          {graph?.assessment ? (
            <AssessmentPanel assessment={graph.assessment} network={activeNetwork} />
          ) : (
            !selectedNode && (
              <Card>
                <EmptyState
                  icon={Sparkles}
                  title="Select a cluster"
                  message="Choose a detected cluster to see the GNN's assessment, or click any node on the canvas to inspect it."
                />
              </Card>
            )
          )}
        </div>
      </div>
    </>
  )
}
