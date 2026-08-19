/**
 * Chart components (Recharts).
 *
 * Conventions: risk colours are semantic and consistent with the rest of the UI,
 * every series is labelled, axes are muted so the data carries the contrast, and
 * tooltips give exact figures because this is an investigative tool.
 */
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatInr, formatNumber, formatPercent } from '../utils/format.js'

export const RISK_COLORS = {
  LOW: '#22a06b',
  MEDIUM: '#d99524',
  HIGH: '#e0533d',
  CRITICAL: '#c02a3f',
}
const AXIS = '#8b9ab5'
const GRID = '#1e2b47'

const axisProps = {
  stroke: AXIS,
  tick: { fill: AXIS, fontSize: 10 },
  tickLine: false,
  axisLine: { stroke: GRID },
}

function TooltipShell({ label, children }) {
  return (
    <div className="rounded border border-ink-600 bg-ink-900/97 px-2.5 py-2 shadow-raised">
      {label && <p className="mb-1 text-2xs font-semibold text-slateish-100">{label}</p>}
      <div className="space-y-0.5">{children}</div>
    </div>
  )
}

function TooltipRow({ color, name, value }) {
  return (
    <p className="flex items-center gap-1.5 text-2xs text-slateish-300">
      {color && (
        <span
          className="h-1.5 w-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
          aria-hidden="true"
        />
      )}
      <span className="text-slateish-400">{name}</span>
      <span className="tnum ml-auto pl-3 font-mono text-slateish-100">{value}</span>
    </p>
  )
}

/* ------------------------------------------------- risk distribution (bars) */

export function RiskDistributionChart({ data, height = 190 }) {
  const rows = (data ?? []).map((d) => ({ ...d, name: d.label }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="name" {...axisProps} />
        <YAxis {...axisProps} tickFormatter={(v) => formatNumber(v)} />
        <Tooltip
          cursor={{ fill: 'rgba(61,139,253,0.07)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={`${row.label} risk`}>
                <TooltipRow
                  color={RISK_COLORS[row.key]}
                  name="Transactions"
                  value={formatNumber(row.count)}
                />
                <TooltipRow name="Share" value={`${row.share}%`} />
                <TooltipRow name="Action" value={row.action} />
              </TooltipShell>
            )
          }}
        />
        <Bar dataKey="count" radius={[3, 3, 0, 0]} maxBarSize={54}>
          {rows.map((row) => (
            <Cell key={row.key} fill={RISK_COLORS[row.key] ?? AXIS} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------- stacked risk trend over time */

export function RiskTrendChart({ series, height = 230 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series ?? []} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
        <defs>
          {Object.entries(RISK_COLORS).map(([key, color]) => (
            <linearGradient key={key} id={`grad-${key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.42} />
              <stop offset="100%" stopColor={color} stopOpacity={0.04} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} minTickGap={22} />
        <YAxis {...axisProps} tickFormatter={(v) => formatNumber(v)} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const total = payload.reduce((acc, p) => acc + (p.value ?? 0), 0)
            return (
              <TooltipShell label={label}>
                {payload
                  .slice()
                  .reverse()
                  .map((p) => (
                    <TooltipRow
                      key={p.dataKey}
                      color={p.color}
                      name={p.name}
                      value={formatNumber(p.value)}
                    />
                  ))}
                <TooltipRow name="Total" value={formatNumber(total)} />
              </TooltipShell>
            )
          }}
        />
        <Legend
          verticalAlign="top"
          height={26}
          iconType="circle"
          iconSize={7}
          wrapperStyle={{ fontSize: 10, color: AXIS }}
        />
        {[
          ['low', 'Low', RISK_COLORS.LOW],
          ['medium', 'Medium', RISK_COLORS.MEDIUM],
          ['high', 'High', RISK_COLORS.HIGH],
          ['critical', 'Critical', RISK_COLORS.CRITICAL],
        ].map(([key, name, color]) => (
          <Area
            key={key}
            type="monotone"
            dataKey={key}
            name={name}
            stackId="risk"
            stroke={color}
            strokeWidth={1.4}
            fill={`url(#grad-${name.toUpperCase()})`}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------------------ alerts over time */

export function AlertsTrendChart({ series, height = 170 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={series ?? []} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} minTickGap={22} />
        <YAxis {...axisProps} allowDecimals={false} />
        <Tooltip
          cursor={{ fill: 'rgba(61,139,253,0.07)' }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipShell label={label}>
                <TooltipRow
                  color="#3d8bfd"
                  name="Alerts raised"
                  value={formatNumber(payload[0].value)}
                />
              </TooltipShell>
            ) : null
          }
        />
        <Bar dataKey="alerts" fill="#3d8bfd" radius={[2, 2, 0, 0]} maxBarSize={22} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/* --------------------------------------------- volume + suspicious share */

export function VolumeChart({ series, height = 170 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={series ?? []} margin={{ top: 4, right: 8, bottom: 0, left: -6 }}>
        <defs>
          <linearGradient id="grad-volume" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#4fd1c5" stopOpacity={0.36} />
            <stop offset="100%" stopColor="#4fd1c5" stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} minTickGap={22} />
        <YAxis {...axisProps} tickFormatter={(v) => formatInr(v)} width={62} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={label}>
                <TooltipRow color="#4fd1c5" name="Volume" value={formatInr(row.volume)} />
                <TooltipRow name="Transactions" value={formatNumber(row.total)} />
                <TooltipRow
                  name="Suspicious share"
                  value={`${row.suspicious_pct?.toFixed(2) ?? 0}%`}
                />
              </TooltipShell>
            )
          }}
        />
        <Area
          type="monotone"
          dataKey="volume"
          name="Volume"
          stroke="#4fd1c5"
          strokeWidth={1.5}
          fill="url(#grad-volume)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export function SuspiciousShareChart({ series, height = 170 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={series ?? []} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} minTickGap={22} />
        <YAxis {...axisProps} tickFormatter={(v) => `${v}%`} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={label}>
                <TooltipRow
                  color="#e0533d"
                  name="High+Critical share"
                  value={`${row.suspicious_pct?.toFixed(2)}%`}
                />
                <TooltipRow name="Average risk score" value={row.avg_risk?.toFixed(1)} />
              </TooltipShell>
            )
          }}
        />
        <Line
          type="monotone"
          dataKey="suspicious_pct"
          name="Suspicious %"
          stroke="#e0533d"
          strokeWidth={1.6}
          dot={false}
          activeDot={{ r: 3 }}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------------------ risk trajectory */

export function RiskTrajectoryChart({ trajectory, height = 200, thresholds }) {
  const data = (trajectory ?? []).map((p) => ({
    label: p.label,
    score: p.risk_score,
    level: p.risk_level,
  }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -22 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} />
        <YAxis {...axisProps} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} />
        <Tooltip
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={label}>
                <TooltipRow
                  color={RISK_COLORS[row.level]}
                  name="Risk score"
                  value={`${row.score}/100`}
                />
                <TooltipRow name="Band" value={row.level} />
              </TooltipShell>
            )
          }}
        />
        <Line
          type="monotone"
          dataKey="score"
          name="Risk score"
          stroke="#3d8bfd"
          strokeWidth={2}
          dot={({ cx, cy, payload }) => (
            <circle
              key={`${cx}-${cy}`}
              cx={cx}
              cy={cy}
              r={3.5}
              fill={RISK_COLORS[payload.level] ?? '#3d8bfd'}
              stroke="#0b1220"
              strokeWidth={1.5}
            />
          )}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function PortfolioTrendChart({ points, height = 180 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points ?? []} margin={{ top: 6, right: 10, bottom: 0, left: -22 }}>
        <defs>
          <linearGradient id="grad-portfolio" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3d8bfd" stopOpacity={0.34} />
            <stop offset="100%" stopColor="#3d8bfd" stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} minTickGap={18} />
        <YAxis {...axisProps} domain={[0, 100]} />
        <Tooltip
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipShell label={label}>
                <TooltipRow
                  color="#3d8bfd"
                  name="Portfolio average risk"
                  value={`${payload[0].value}/100`}
                />
              </TooltipShell>
            ) : null
          }
        />
        <Area
          type="monotone"
          dataKey="value"
          name="Average risk"
          stroke="#3d8bfd"
          strokeWidth={1.6}
          fill="url(#grad-portfolio)"
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------------------- channel / feature */

export function ChannelChart({ data, height = 190 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data ?? []}
        layout="vertical"
        margin={{ top: 2, right: 12, bottom: 0, left: 6 }}
      >
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" horizontal={false} />
        <XAxis type="number" {...axisProps} tickFormatter={(v) => formatNumber(v)} />
        <YAxis type="category" dataKey="channel" {...axisProps} width={54} />
        <Tooltip
          cursor={{ fill: 'rgba(61,139,253,0.07)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={row.channel}>
                <TooltipRow color="#3d8bfd" name="Transactions" value={formatNumber(row.count)} />
                <TooltipRow name="Volume" value={formatInr(row.volume)} />
                <TooltipRow name="Average risk" value={row.avg_risk?.toFixed(1)} />
                <TooltipRow name="High/Critical" value={formatNumber(row.high_risk_count)} />
              </TooltipShell>
            )
          }}
        />
        <Bar dataKey="count" fill="#3d8bfd" radius={[0, 3, 3, 0]} maxBarSize={16} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function FeatureImportanceChart({ features, height = 340, limit = 12 }) {
  const data = (features ?? [])
    .slice(0, limit)
    .map((f) => ({ ...f, pct: +(f.importance * 100).toFixed(2) }))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 2, right: 34, bottom: 0, left: 8 }}
      >
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" horizontal={false} />
        <XAxis type="number" {...axisProps} tickFormatter={(v) => `${v}%`} />
        <YAxis
          type="category"
          dataKey="label"
          {...axisProps}
          width={168}
          tick={{ fill: AXIS, fontSize: 9.5 }}
        />
        <Tooltip
          cursor={{ fill: 'rgba(79,209,197,0.07)' }}
          content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const row = payload[0].payload
            return (
              <TooltipShell label={row.label}>
                <TooltipRow color="#4fd1c5" name="Importance" value={`${row.pct}%`} />
                <p className="mt-1 max-w-xs text-2xs leading-snug text-slateish-400">
                  {row.description}
                </p>
              </TooltipShell>
            )
          }}
        />
        <Bar dataKey="pct" fill="#4fd1c5" radius={[0, 3, 3, 0]} maxBarSize={13} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ------------------------------------------------------- confusion matrix */

export function ConfusionMatrix({ matrix, labels }) {
  if (!matrix?.length) return null
  const total = matrix.flat().reduce((a, b) => a + b, 0) || 1
  const names = labels ?? ['Negative', 'Positive']
  const cellMeta = [
    ['True negative', '#22a06b'],
    ['False positive', '#d99524'],
    ['False negative', '#e0533d'],
    ['True positive', '#22a06b'],
  ]

  return (
    <div className="overflow-x-auto">
      <table className="text-2xs">
        <thead>
          <tr>
            <th className="p-1" />
            <th
              colSpan={2}
              className="pb-1.5 text-center text-2xs font-semibold uppercase tracking-wider text-slateish-400"
            >
              Predicted
            </th>
          </tr>
          <tr>
            <th className="p-1" />
            {names.map((n) => (
              <th key={n} className="px-2 pb-1 font-medium text-slateish-400">
                {n}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, r) => (
            <tr key={r}>
              <th className="whitespace-nowrap pr-2 text-right font-medium text-slateish-400">
                {names[r]}
                <span className="block text-[9px] font-normal opacity-70">actual</span>
              </th>
              {row.map((value, c) => {
                const idx = r * 2 + c
                const [label, color] = cellMeta[idx] ?? ['', AXIS]
                const share = (value / total) * 100
                return (
                  <td key={c} className="p-1">
                    <div
                      title={`${label}: ${value.toLocaleString()} (${share.toFixed(1)}%)`}
                      className="flex h-16 w-24 flex-col items-center justify-center rounded border"
                      style={{
                        borderColor: `${color}44`,
                        backgroundColor: `${color}${r === c ? '22' : '14'}`,
                      }}
                    >
                      <span className="tnum font-mono text-sm font-semibold text-slateish-100">
                        {value.toLocaleString()}
                      </span>
                      <span className="text-[9px] leading-tight" style={{ color }}>
                        {label}
                      </span>
                      <span className="tnum text-[9px] text-slateish-400">
                        {share.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ------------------------------------------------------------- geo bars */

export function GeoRiskList({ data }) {
  const rows = data ?? []
  if (!rows.length) return null
  const max = Math.max(...rows.map((r) => r.transactions), 1)
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={`${row.region}-${row.country}`}>
          <div className="flex items-baseline justify-between gap-2 text-2xs">
            <span className="truncate text-slateish-200">{row.country}</span>
            <span className="tnum shrink-0 font-mono text-slateish-400">
              {formatNumber(row.transactions)} txn · {formatInr(row.volume)}
            </span>
          </div>
          <div className="mt-1 flex items-center gap-2">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink-800">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${(row.transactions / max) * 100}%`,
                  backgroundColor: RISK_COLORS[row.risk_level] ?? AXIS,
                }}
              />
            </div>
            <span
              className="tnum w-16 shrink-0 text-right font-mono text-2xs"
              style={{ color: RISK_COLORS[row.risk_level] ?? AXIS }}
              title={`${row.high_risk_count} high or critical transactions`}
            >
              avg {row.avg_risk}
            </span>
          </div>
        </li>
      ))}
    </ul>
  )
}
