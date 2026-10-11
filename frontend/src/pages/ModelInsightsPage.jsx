/**
 * Model Insights.
 *
 * This page is deliberately blunt about what is real and what is not. Metrics come
 * from the trained artifacts; where no artifact is loaded it says so rather than
 * showing plausible-looking numbers.
 */
import { AlertTriangle, BrainCircuit, CheckCircle2, Network, XCircle } from 'lucide-react'

import { ConfusionMatrix, FeatureImportanceChart } from '../charts/index.jsx'
import {
  Advisory,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  KeyValue,
  PageHeader,
  Skeleton,
  Table,
  Td,
  Th,
  Tr,
} from '../components/ui.jsx'
import { useApi } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatDateTime, formatNumber, formatPercent, humanise } from '../utils/format.js'

function MetricTile({ label, value, hint }) {
  return (
    <div className="rounded border border-ink-700 bg-ink-900/60 p-2.5" title={hint}>
      <p className="text-[9.5px] uppercase tracking-wide text-slateish-400">{label}</p>
      <p className="tnum mt-1 font-mono text-base font-semibold text-slateish-100">{value}</p>
    </div>
  )
}

function TrainedBanner({ trained, name }) {
  return trained ? (
    <div className="flex items-start gap-2 rounded border border-risk-low/35 bg-risk-lowBg px-3 py-2">
      <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-risk-low" aria-hidden="true" />
      <p className="text-2xs leading-snug text-slateish-200">
        <strong className="text-risk-low">A real fitted artifact is loaded.</strong> The metrics
        below were computed on data held out from training — they are not illustrative figures.
      </p>
    </div>
  ) : (
    <div className="flex items-start gap-2 rounded border border-risk-medium/40 bg-risk-mediumBg px-3 py-2">
      <XCircle size={13} className="mt-0.5 shrink-0 text-risk-medium" aria-hidden="true" />
      <p className="text-2xs leading-snug text-slateish-200">
        <strong className="text-risk-medium">No trained artifact is loaded for {name}.</strong> An
        untrained fallback is active, so no accuracy, precision, recall or confusion matrix is
        reported — showing any would be fabrication.
      </p>
    </div>
  )
}

function Caveats({ items }) {
  if (!items?.length) return null
  return (
    <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
      <h4 className="mb-2 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
        <AlertTriangle size={11} className="text-risk-medium" aria-hidden="true" />
        Limitations you should read
      </h4>
      <ul className="space-y-1.5">
        {items.map((caveat, index) => (
          <li key={index} className="flex gap-2 text-2xs leading-relaxed text-slateish-300">
            <span className="shrink-0 text-slateish-400">{index + 1}.</span>
            <span>{caveat}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function ModelInsightsPage() {
  const { data, error, loading, reload } = useApi((signal) => api.modelInsights(signal), [])

  if (error) return <ErrorState error={error} onRetry={reload} />

  const proactive = data?.proactive
  const gnn = data?.gnn
  const metrics = proactive?.metrics

  return (
    <>
      <PageHeader
        icon={BrainCircuit}
        title="Model Insights"
        subtitle="What each model is, what it was fitted on, how well it performs on held-out data, and where it must not be trusted."
      />

      {data && (
        <Advisory tone="warning" className="mb-4">
          {data.honesty_statement}
        </Advisory>
      )}

      {loading && <Skeleton className="h-96" />}

      {data && (
        <div className="space-y-4">
          {/* =============================================== PROACTIVE MODEL */}
          <Card>
            <CardHeader
              icon={BrainCircuit}
              title="Proactive behavioural risk model"
              subtitle={proactive.purpose}
              action={
                <Chip tone={proactive.provenance.trained ? 'low' : 'medium'}>
                  {proactive.provenance.trained ? 'trained' : 'untrained fallback'}
                </Chip>
              }
            />

            <TrainedBanner
              trained={proactive.provenance.trained}
              name="the proactive model"
            />

            <div className="mt-3 grid gap-3 lg:grid-cols-[300px_1fr]">
              <div className="space-y-2">
                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <KeyValue label="Model" value={proactive.provenance.model_name} mono />
                  <KeyValue label="Version" value={proactive.provenance.model_version} mono />
                  <KeyValue label="Algorithm" value={proactive.algorithm} />
                  <KeyValue label="Features" value={proactive.feature_count} mono />
                  {proactive.training_rows > 0 && (
                    <KeyValue
                      label="Training rows"
                      value={formatNumber(proactive.training_rows)}
                      mono
                    />
                  )}
                  {proactive.trained_at && (
                    <KeyValue label="Trained" value={formatDateTime(proactive.trained_at)} mono />
                  )}
                  {proactive.class_balance?.normal !== undefined && (
                    <KeyValue
                      label="Class balance"
                      value={`${formatNumber(proactive.class_balance.normal)} normal / ${formatNumber(proactive.class_balance.elevated_risk)} elevated`}
                      mono
                    />
                  )}
                </div>

                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                    Training data
                  </p>
                  <p className="text-2xs leading-relaxed text-slateish-300">
                    {proactive.provenance.training_data}
                  </p>
                </div>

                {Object.keys(proactive.hyperparameters ?? {}).length > 0 && (
                  <details className="rounded border border-ink-700 bg-ink-900/60">
                    <summary className="cursor-pointer px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400 hover:text-slateish-200">
                      Hyperparameters
                    </summary>
                    <div className="border-t border-ink-800 px-3 py-2">
                      {Object.entries(proactive.hyperparameters).map(([key, value]) => (
                        <KeyValue key={key} label={key} value={String(value)} mono />
                      ))}
                    </div>
                  </details>
                )}
              </div>

              <div className="space-y-3">
                {metrics ? (
                  <>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                      <MetricTile
                        label="Accuracy"
                        value={formatPercent(metrics.accuracy * 100)}
                        hint="Share of held-out rows classified correctly"
                      />
                      <MetricTile
                        label="Precision"
                        value={formatPercent(metrics.precision * 100)}
                        hint="Of those flagged as elevated risk, how many actually were"
                      />
                      <MetricTile
                        label="Recall"
                        value={formatPercent(metrics.recall * 100)}
                        hint="Of the actually elevated-risk rows, how many were caught"
                      />
                      <MetricTile label="F1" value={metrics.f1.toFixed(3)} hint="Harmonic mean of precision and recall" />
                      <MetricTile
                        label="ROC AUC"
                        value={metrics.roc_auc ? metrics.roc_auc.toFixed(3) : '—'}
                        hint="Ranking quality across all thresholds"
                      />
                    </div>
                    <div className="grid gap-3 md:grid-cols-2">
                      <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                        <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                          Confusion matrix
                        </p>
                        <ConfusionMatrix
                          matrix={metrics.confusion_matrix}
                          labels={metrics.labels}
                        />
                        <p className="mt-2 text-[9.5px] text-slateish-400">
                          {formatNumber(metrics.support)} held-out rows
                        </p>
                      </div>
                      <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                        <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                          How to read these numbers
                        </p>
                        <p className="text-2xs leading-relaxed text-slateish-300">
                          In AML, <strong className="text-slateish-100">recall</strong> matters more
                          than precision: a missed laundering network is far costlier than an extra
                          case for an analyst to clear. A false positive costs review time; a false
                          negative costs a regulatory failure. These figures come from a held-out
                          split of the same synthetic distribution the model was fitted on, so they
                          describe pattern recovery, not real-world detection skill.
                        </p>
                      </div>
                    </div>
                  </>
                ) : (
                  <EmptyState
                    icon={AlertTriangle}
                    title="No metrics available"
                    message="Nothing was fitted, so no performance figure can honestly be reported."
                  />
                )}
              </div>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_320px]">
              <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                  Feature importance
                </p>
                <p className="mb-2 text-[9.5px] text-slateish-400">
                  Global importance from the fitted forest. Per-customer explanations use
                  occlusion attribution instead, which interrogates the model for that specific
                  observation.
                </p>
                <FeatureImportanceChart features={proactive.features} />
              </div>
              <Caveats items={proactive.caveats} />
            </div>
          </Card>

          {/* ===================================================== GNN MODEL */}
          <Card>
            <CardHeader
              icon={Network}
              title="Graph neural network"
              subtitle={gnn.purpose}
              action={
                <Chip tone={gnn.provenance.trained ? 'low' : 'medium'}>
                  {gnn.provenance.trained ? 'trained' : 'untrained analytic engine'}
                </Chip>
              }
            />

            <TrainedBanner trained={gnn.provenance.trained} name="the GNN" />

            <div className="mt-3 grid gap-3 lg:grid-cols-[320px_1fr]">
              <div className="space-y-2">
                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <KeyValue label="Engine" value={gnn.provenance.model_name} mono />
                  <KeyValue label="Version" value={gnn.provenance.model_version} mono />
                  {gnn.trained_at && (
                    <KeyValue label="Trained" value={formatDateTime(gnn.trained_at)} mono />
                  )}
                  <KeyValue
                    label="Node features"
                    value={gnn.graph_summary.node_feature_count}
                    mono
                  />
                  <KeyValue
                    label="Edge features"
                    value={gnn.graph_summary.edge_feature_count}
                    mono
                  />
                </div>

                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                    Architecture
                  </p>
                  <p className="text-2xs leading-relaxed text-slateish-300">{gnn.architecture}</p>
                </div>

                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                    Training data
                  </p>
                  <p className="text-2xs leading-relaxed text-slateish-300">
                    {gnn.provenance.training_data}
                  </p>
                </div>

                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                    Live graph
                  </p>
                  <KeyValue
                    label="Accounts (nodes)"
                    value={formatNumber(gnn.graph_summary.live_accounts_nodes)}
                    mono
                  />
                  <KeyValue
                    label="Transactions (edges)"
                    value={formatNumber(gnn.graph_summary.live_transactions_edges)}
                    mono
                  />
                  <KeyValue
                    label="Clusters detected"
                    value={formatNumber(gnn.graph_summary.clusters_detected)}
                    mono
                  />
                  <KeyValue
                    label="Flagged suspicious"
                    value={formatNumber(gnn.graph_summary.clusters_flagged_suspicious)}
                    mono
                  />
                </div>
              </div>

              <div className="space-y-3">
                <div className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                    Tasks and held-out performance
                  </p>
                  <Table>
                    <thead>
                      <tr>
                        <Th>Task</Th>
                        <Th>Type</Th>
                        <Th>What it does</Th>
                        <Th>Held-out metric</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {gnn.tasks.map((task) => (
                        <Tr key={task.name}>
                          <Td className="font-medium text-slateish-100">{task.name}</Td>
                          <Td className="text-slateish-400">{task.type}</Td>
                          <Td className="max-w-[280px] whitespace-normal text-2xs leading-snug text-slateish-400">
                            {task.detail}
                          </Td>
                          <Td mono className="text-slateish-200">
                            {task.metric}
                          </Td>
                        </Tr>
                      ))}
                    </tbody>
                  </Table>
                </div>

                {Object.keys(gnn.hyperparameters ?? {}).length > 0 && (
                  <details className="rounded border border-ink-700 bg-ink-900/60">
                    <summary className="cursor-pointer px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400 hover:text-slateish-200">
                      Training configuration
                    </summary>
                    <div className="grid gap-x-6 border-t border-ink-800 px-3 py-2 sm:grid-cols-2">
                      {Object.entries(gnn.hyperparameters).map(([key, value]) => (
                        <KeyValue key={key} label={key} value={String(value)} mono />
                      ))}
                    </div>
                  </details>
                )}

                {gnn.graph_summary.node_features?.length > 0 && (
                  <details className="rounded border border-ink-700 bg-ink-900/60">
                    <summary className="cursor-pointer px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400 hover:text-slateish-200">
                      Graph feature space
                    </summary>
                    <div className="border-t border-ink-800 px-3 py-2">
                      <p className="mb-1 text-[9.5px] font-semibold uppercase text-slateish-400">
                        Node features
                      </p>
                      <ul className="mb-2 grid gap-x-4 sm:grid-cols-2">
                        {gnn.graph_summary.node_features.map((f) => (
                          <li key={f.name} className="text-2xs text-slateish-300">
                            <span className="font-mono text-slateish-400">{f.name}</span> —{' '}
                            {f.label}
                          </li>
                        ))}
                      </ul>
                      <p className="mb-1 text-[9.5px] font-semibold uppercase text-slateish-400">
                        Edge features
                      </p>
                      <ul className="grid gap-x-4 sm:grid-cols-2">
                        {gnn.graph_summary.edge_features.map((f) => (
                          <li key={f.name} className="text-2xs text-slateish-300">
                            <span className="font-mono text-slateish-400">{f.name}</span> —{' '}
                            {f.label}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </details>
                )}

                <Caveats items={gnn.caveats} />
              </div>
            </div>

            {gnn.signal_vocabulary?.length > 0 && (
              <div className="mt-3 rounded border border-ink-700 bg-ink-900/60 p-3">
                <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slateish-400">
                  Signal vocabulary
                </p>
                <p className="mb-2 text-[9.5px] text-slateish-400">
                  Every signal the network layer can report, and what it actually means. These are
                  observed structural characteristics — none of them asserts criminality.
                </p>
                <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {gnn.signal_vocabulary.map((sig) => (
                    <div key={sig.code}>
                      <p className="text-2xs font-medium text-slateish-200">{sig.label}</p>
                      <p className="text-[9.5px] leading-snug text-slateish-400">{sig.meaning}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </>
  )
}
