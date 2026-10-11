import { Boxes, Lock, Save } from 'lucide-react'
import { useMemo, useState } from 'react'

import {
  Advisory,
  Button,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  PageHeader,
  SearchInput,
  Select,
  SkeletonTable,
  Table,
  Td,
  Th,
  Toggle,
  Tr,
} from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useToast } from '../context/ToastContext.jsx'
import { useApi, useMutation } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { formatNumber, humanise } from '../utils/format.js'

const LAYER_OPTIONS = [
  { value: '', label: 'All layers' },
  { value: 'INTEGRITY', label: 'Transaction integrity' },
  { value: 'PROACTIVE', label: 'Proactive (pre-transaction)' },
  { value: 'REACTIVE', label: 'Reactive (post-settlement)' },
  { value: 'NETWORK', label: 'Network (graph + GNN)' },
]

const LAYER_TONE = {
  INTEGRITY: 'critical',
  PROACTIVE: 'info',
  REACTIVE: 'neutral',
  NETWORK: 'accent',
}
const SEVERITY_TONE = { LOW: 'low', MEDIUM: 'medium', HIGH: 'high', CRITICAL: 'critical' }

function RuleRow({ rule, canEdit, onSaved }) {
  const toast = useToast()
  const [enabled, setEnabled] = useState(rule.enabled)
  const [threshold, setThreshold] = useState(String(rule.threshold))
  const [weight, setWeight] = useState(String(rule.score_weight))

  const dirty =
    enabled !== rule.enabled ||
    Number(threshold) !== rule.threshold ||
    Number(weight) !== rule.score_weight

  const save = useMutation(async () => {
    await api.updateRule(rule.code, {
      enabled,
      threshold: Number(threshold),
      score_weight: Number(weight),
    })
    toast.success(`${rule.code} updated.`)
    onSaved()
  })

  const toggle = useMutation(async (value) => {
    setEnabled(value)
    await api.updateRule(rule.code, { enabled: value })
    toast.info(`${rule.code} ${value ? 'enabled' : 'disabled'}.`)
    onSaved()
  })

  return (
    <Tr>
      <Td>
        <span className="tnum block font-mono text-2xs font-semibold text-slateish-100">
          {rule.code}
        </span>
        <span className="block max-w-[240px] truncate text-2xs text-slateish-300">
          {rule.name}
        </span>
      </Td>
      <Td className="max-w-[320px] whitespace-normal text-2xs leading-snug text-slateish-400">
        {rule.description}
      </Td>
      <Td>
        <Chip tone={LAYER_TONE[rule.layer] ?? 'neutral'}>{rule.layer}</Chip>
      </Td>
      <Td>
        <Chip tone={SEVERITY_TONE[rule.severity] ?? 'neutral'}>{rule.severity}</Chip>
      </Td>
      <Td align="right">
        {canEdit ? (
          <div className="flex items-center justify-end gap-1">
            <span className="text-[9.5px] text-slateish-400">{rule.operator}</span>
            <input
              type="number"
              step="any"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              className="tnum w-20 rounded border border-ink-600 bg-ink-900 px-1.5 py-0.5 text-right font-mono text-2xs text-slateish-100"
              aria-label={`${rule.code} threshold`}
            />
          </div>
        ) : (
          <span className="tnum font-mono text-2xs">
            {rule.operator} {rule.threshold}
          </span>
        )}
        {rule.threshold_unit && (
          <span className="mt-0.5 block text-[9.5px] text-slateish-400">
            {rule.threshold_unit}
          </span>
        )}
      </Td>
      <Td align="right">
        {canEdit ? (
          <input
            type="number"
            min="0"
            max="100"
            step="0.5"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            className="tnum w-16 rounded border border-ink-600 bg-ink-900 px-1.5 py-0.5 text-right font-mono text-2xs text-slateish-100"
            aria-label={`${rule.code} score weight`}
          />
        ) : (
          <span className="tnum font-mono text-2xs">{rule.score_weight}</span>
        )}
      </Td>
      <Td align="right" mono className="text-slateish-300">
        {formatNumber(rule.triggered_count)}
      </Td>
      <Td align="center">
        <Toggle
          checked={enabled}
          onChange={(value) => canEdit && toggle.run(value).catch(() => setEnabled(!value))}
          disabled={!canEdit || toggle.pending}
          label={`${rule.code} enabled`}
        />
      </Td>
      <Td align="center">
        {canEdit && dirty && (
          <Button
            size="xs"
            variant="primary"
            icon={Save}
            loading={save.pending}
            onClick={() => save.run().catch(() => {})}
          >
            Save
          </Button>
        )}
      </Td>
    </Tr>
  )
}

export default function RulesEnginePage() {
  const { can } = useAuth()
  const canEdit = can('rules:write')
  const [layer, setLayer] = useState('')
  const [search, setSearch] = useState('')

  const { data, error, loading, reload } = useApi(
    (signal) => api.rules({ page_size: 200 }, signal),
    [],
  )
  const rules = data?.items ?? data ?? []

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return rules.filter((rule) => {
      if (layer && rule.layer !== layer) return false
      if (!term) return true
      return (
        rule.code.toLowerCase().includes(term) ||
        rule.name.toLowerCase().includes(term) ||
        rule.description.toLowerCase().includes(term)
      )
    })
  }, [rules, layer, search])

  const byLayer = useMemo(() => {
    const counts = {}
    for (const rule of rules) {
      counts[rule.layer] = (counts[rule.layer] ?? 0) + 1
    }
    return counts
  }, [rules])

  const enabledCount = rules.filter((r) => r.enabled).length
  const totalTriggers = rules.reduce((acc, r) => acc + (r.triggered_count ?? 0), 0)

  return (
    <>
      <PageHeader
        icon={Boxes}
        title="Rules Engine"
        subtitle="Detection rules are data, not code paths. Thresholds and weights are read from the database at evaluation time, so retuning a rule changes what the platform flags immediately."
      >
        {!canEdit && (
          <Chip tone="medium">
            <Lock size={9} aria-hidden="true" /> read-only for your role
          </Chip>
        )}
      </PageHeader>

      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <Card>
          <p className="text-2xs uppercase tracking-wide text-slateish-400">Total rules</p>
          <p className="tnum mt-1 font-mono text-lg font-semibold text-slateish-100">
            {rules.length}
          </p>
        </Card>
        <Card>
          <p className="text-2xs uppercase tracking-wide text-slateish-400">Enabled</p>
          <p className="tnum mt-1 font-mono text-lg font-semibold text-risk-low">{enabledCount}</p>
        </Card>
        <Card>
          <p className="text-2xs uppercase tracking-wide text-slateish-400">Disabled</p>
          <p className="tnum mt-1 font-mono text-lg font-semibold text-slateish-400">
            {rules.length - enabledCount}
          </p>
        </Card>
        <Card>
          <p className="text-2xs uppercase tracking-wide text-slateish-400">Total triggers</p>
          <p className="tnum mt-1 font-mono text-lg font-semibold text-risk-medium">
            {formatNumber(totalTriggers)}
          </p>
        </Card>
        {['INTEGRITY', 'PROACTIVE', 'REACTIVE'].map((key) => (
          <Card key={key}>
            <p className="text-2xs uppercase tracking-wide text-slateish-400">
              {humanise(key)}
            </p>
            <p className="tnum mt-1 font-mono text-lg font-semibold text-slateish-100">
              {byLayer[key] ?? 0}
            </p>
          </Card>
        ))}
      </div>

      <Card padded={false} className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-800 p-3">
          <SearchInput
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rule code, name or description…"
            className="w-full sm:w-64"
            aria-label="Search rules"
          />
          <Select
            value={layer}
            onChange={(e) => setLayer(e.target.value)}
            options={LAYER_OPTIONS}
            aria-label="Filter by layer"
          />
          <span className="tnum ml-auto font-mono text-2xs text-slateish-400">
            {filtered.length} of {rules.length}
          </span>
        </div>

        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !error && <SkeletonTable rows={10} cols={9} />}
        {!loading && !error && filtered.length === 0 && (
          <EmptyState icon={Boxes} title="No rules match this filter" />
        )}

        {!loading && !error && filtered.length > 0 && (
          <Table>
            <thead>
              <tr>
                <Th>Rule</Th>
                <Th>Description</Th>
                <Th>Layer</Th>
                <Th>Severity</Th>
                <Th align="right">Threshold</Th>
                <Th align="right">Weight</Th>
                <Th align="right">Triggered</Th>
                <Th align="center">Status</Th>
                <Th align="center" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((rule) => (
                <RuleRow key={rule.code} rule={rule} canEdit={canEdit} onSaved={reload} />
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Advisory className="mt-3">
        The <strong className="text-slateish-200">weight</strong> is the number of points a rule
        contributes to the composite score when it fires; the composite blends these rule points
        with the model probability. Disabling a rule removes its contribution immediately, which is
        how an institution retains control over an automated system.
      </Advisory>
    </>
  )
}
