/**
 * Interactive financial-network graph (React Flow).
 *
 * Encoding rules:
 *  - Node COLOUR   = risk band (semantic, matches the rest of the UI)
 *  - Node SIZE     = transaction throughput
 *  - Node SHAPE/ICON = entity type (account, merchant, company, wallet)
 *  - Node BORDER   = flagged by the model (dashed ring) - never colour alone
 *  - Edge WIDTH    = transfer amount
 *  - Edge COLOUR   = edge risk from the GNN edge head
 *  - Edge ANIMATION = only on flagged edges, so motion means something
 *
 * A node's role in a detected typology (SOURCE / INTERMEDIARY / CONVERGENCE) is
 * printed on the node, because that is what an investigator actually reads.
 */
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from 'reactflow'
import 'reactflow/dist/style.css'

import clsx from 'clsx'
import { Building2, CreditCard, Landmark, Store, Wallet } from 'lucide-react'
import { memo, useCallback, useEffect, useMemo } from 'react'

import { RISK_COLORS } from '../charts/index.jsx'
import { formatInr, riskMeta } from '../utils/format.js'

const ENTITY_ICONS = {
  ACCOUNT: Landmark,
  MERCHANT: Store,
  COMPANY: Building2,
  WALLET: Wallet,
  BENEFICIARY: CreditCard,
  CUSTOMER: Landmark,
}

const ROLE_LABELS = {
  SOURCE: 'Source',
  INTERMEDIARY: 'Intermediary',
  CONVERGENCE: 'Convergence',
  DISTRIBUTOR: 'Distributor',
  CYCLE_MEMBER: 'In cycle',
  PARTICIPANT: '',
}

function bandFor(score) {
  if (score >= 85) return 'CRITICAL'
  if (score >= 60) return 'HIGH'
  if (score >= 35) return 'MEDIUM'
  return 'LOW'
}

/* --------------------------------------------------------------- node type */

const AccountNode = memo(({ data, selected }) => {
  const band = bandFor(data.gnn_node_score)
  const color = RISK_COLORS[band]
  const Icon = ENTITY_ICONS[data.entity_type] ?? Landmark
  const role = ROLE_LABELS[data.role] ?? ''

  // Size scales with throughput so the money-movers are visually dominant
  const size = Math.min(78, 46 + Math.log10(Math.max(data.volume, 1)) * 3.6)

  return (
    <div className="group relative flex flex-col items-center">
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !bg-ink-500" />
      <div
        className={clsx(
          'flex items-center justify-center rounded-full transition-all',
          data.is_suspicious && 'ring-2 ring-offset-2 ring-offset-ink-950',
          selected && 'scale-110',
        )}
        style={{
          width: size,
          height: size,
          backgroundColor: `${color}22`,
          border: `2px ${data.is_suspicious ? 'dashed' : 'solid'} ${color}`,
          boxShadow: selected ? `0 0 0 3px ${color}44` : undefined,
          ...(data.is_suspicious ? { '--tw-ring-color': `${color}66` } : {}),
        }}
        title={`${data.account_ref} · ${data.label}\nModel score ${data.gnn_node_score}/100 (${band})\nThroughput ${formatInr(data.volume)} · ${data.connections} connections`}
      >
        <Icon size={Math.max(13, size / 3.6)} style={{ color }} aria-hidden="true" />
      </div>

      <div className="pointer-events-none mt-1 flex flex-col items-center">
        <span className="tnum max-w-[110px] truncate font-mono text-[9.5px] font-semibold text-slateish-100">
          {data.account_ref}
        </span>
        <span className="tnum text-[9px] font-medium" style={{ color }}>
          {Math.round(data.gnn_node_score)}/100 {band}
        </span>
        {role && (
          <span className="mt-0.5 rounded bg-ink-800/90 px-1 text-[8.5px] font-medium text-slateish-300">
            {role}
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !bg-ink-500" />
    </div>
  )
})
AccountNode.displayName = 'AccountNode'

/* --------------------------------------------------------------- edge type */

const FlowEdge = memo(
  ({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected }) => {
    const [path, labelX, labelY] = getBezierPath({
      sourceX,
      sourceY,
      sourcePosition,
      targetX,
      targetY,
      targetPosition,
    })
    const band = bandFor(data?.gnn_edge_score ?? 0)
    const color = data?.is_suspicious ? RISK_COLORS[band] : '#3b4d73'
    const width = Math.min(5, 1 + Math.log10(Math.max(data?.amount ?? 1, 1)) * 0.5)

    return (
      <>
        <BaseEdge
          id={id}
          path={path}
          style={{
            stroke: color,
            strokeWidth: selected ? width + 1.4 : width,
            strokeDasharray: data?.is_suspicious ? '6 3' : undefined,
            opacity: data?.is_suspicious ? 0.95 : 0.5,
          }}
          markerEnd={MarkerType.ArrowClosed}
        />
        {(selected || data?.is_suspicious) && (
          <EdgeLabelRenderer>
            <div
              style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
              className="pointer-events-none absolute rounded border border-ink-600 bg-ink-900/95 px-1 py-0.5"
            >
              <span className="tnum font-mono text-[9px] font-medium text-slateish-100">
                {formatInr(data?.amount ?? 0)}
              </span>
              {data?.hop_index !== null && data?.hop_index !== undefined && (
                <span className="ml-1 text-[8.5px] text-accent">hop {data.hop_index + 1}</span>
              )}
            </div>
          </EdgeLabelRenderer>
        )}
      </>
    )
  },
)
FlowEdge.displayName = 'FlowEdge'

const nodeTypes = { account: AccountNode }
const edgeTypes = { flow: FlowEdge }

/* ------------------------------------------------------------- transforms */

function toFlowNodes(nodes, { highlighted, dimmed }) {
  return (nodes ?? []).map((node, index) => {
    // Fall back to a deterministic spiral when the backend gave no layout hint
    const hasLayout = node.x !== 0 || node.y !== 0
    const angle = index * 2.399
    const radius = 60 + index * 13
    return {
      id: node.id,
      type: 'account',
      position: hasLayout
        ? { x: node.x, y: node.y }
        : { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius },
      data: node,
      style: {
        opacity: dimmed?.size ? (dimmed.has(node.id) ? 0.18 : 1) : 1,
        ...(highlighted?.has(node.id) ? { zIndex: 10 } : {}),
      },
    }
  })
}

function toFlowEdges(edges, { dimmed }) {
  return (edges ?? []).map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: 'flow',
    data: edge,
    animated: edge.is_suspicious,
    style: {
      opacity: dimmed?.size ? (dimmed.has(edge.source) || dimmed.has(edge.target) ? 0.1 : 1) : 1,
    },
  }))
}

/* -------------------------------------------------------------- component */

function GraphInner({
  nodes: rawNodes,
  edges: rawEdges,
  onNodeSelect,
  onEdgeSelect,
  selectedNodeId,
  focusNeighboursOf,
}) {
  const { fitView } = useReactFlow()

  // When highlighting a node's neighbourhood, everything else is dimmed
  const { highlighted, dimmed } = useMemo(() => {
    if (!focusNeighboursOf) return { highlighted: new Set(), dimmed: new Set() }
    const keep = new Set([focusNeighboursOf])
    for (const edge of rawEdges ?? []) {
      if (edge.source === focusNeighboursOf) keep.add(edge.target)
      if (edge.target === focusNeighboursOf) keep.add(edge.source)
    }
    const dim = new Set(
      (rawNodes ?? []).map((n) => n.id).filter((id) => !keep.has(id)),
    )
    return { highlighted: keep, dimmed: dim }
  }, [focusNeighboursOf, rawNodes, rawEdges])

  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    setNodes(toFlowNodes(rawNodes, { highlighted, dimmed }))
    setEdges(toFlowEdges(rawEdges, { dimmed }))
  }, [rawNodes, rawEdges, highlighted, dimmed, setNodes, setEdges])

  useEffect(() => {
    const id = setTimeout(() => fitView({ padding: 0.22, duration: 320 }), 60)
    return () => clearTimeout(id)
  }, [rawNodes, fitView])

  const handleNodeClick = useCallback(
    (_event, node) => onNodeSelect?.(node.data),
    [onNodeSelect],
  )
  const handleEdgeClick = useCallback(
    (_event, edge) => onEdgeSelect?.(edge.data),
    [onEdgeSelect],
  )

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleNodeClick}
      onEdgeClick={handleEdgeClick}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView
      minZoom={0.15}
      maxZoom={2.5}
      proOptions={{ hideAttribution: true }}
      defaultEdgeOptions={{ type: 'flow' }}
      className="bg-ink-950"
    >
      <Background color="#1e2b47" gap={22} size={1} />
      <Controls
        showInteractive={false}
        className="!rounded !border !border-ink-600 !bg-ink-900 [&>button]:!border-ink-700 [&>button]:!bg-ink-850 [&>button]:!fill-slateish-300 [&>button:hover]:!bg-ink-750"
      />
    </ReactFlow>
  )
}

/**
 * `GraphInner` calls `useReactFlow()`, which requires a React Flow store in the
 * tree above it. Wrapping in `ReactFlowProvider` supplies that store, so the
 * component can drive `fitView` itself rather than relying on being rendered as a
 * descendant of `<ReactFlow>`.
 */
export default function NetworkGraph(props) {
  return (
    <div className="h-full w-full">
      <ReactFlowProvider>
        <GraphInner {...props} />
      </ReactFlowProvider>
    </div>
  )
}

/** Legend explaining every visual encoding. Colour is never left unexplained. */
export function GraphLegend({ className }) {
  return (
    <div className={clsx('flex flex-wrap items-center gap-x-4 gap-y-2 text-2xs', className)}>
      <span className="font-semibold uppercase tracking-wider text-slateish-400">Legend</span>
      {['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((band) => (
        <span key={band} className="inline-flex items-center gap-1.5 text-slateish-300">
          <span
            className="h-2.5 w-2.5 rounded-full border"
            style={{
              backgroundColor: `${RISK_COLORS[band]}33`,
              borderColor: RISK_COLORS[band],
            }}
            aria-hidden="true"
          />
          {riskMeta(band).label}
        </span>
      ))}
      <span className="inline-flex items-center gap-1.5 text-slateish-300">
        <span
          className="h-2.5 w-2.5 rounded-full border-2 border-dashed"
          style={{ borderColor: RISK_COLORS.HIGH }}
          aria-hidden="true"
        />
        Dashed ring = model-flagged
      </span>
      <span className="inline-flex items-center gap-1.5 text-slateish-300">
        <svg width="20" height="6" aria-hidden="true">
          <line x1="0" y1="3" x2="20" y2="3" stroke={RISK_COLORS.HIGH} strokeWidth="2.5" strokeDasharray="5 3" />
        </svg>
        Flagged transfer
      </span>
      <span className="text-slateish-400">Node size = throughput · Edge width = amount</span>
    </div>
  )
}
