import { Database, Lock, Settings as SettingsIcon, ShieldCheck, Users } from 'lucide-react'

import {
  Advisory,
  Card,
  CardHeader,
  Chip,
  EmptyState,
  ErrorState,
  KeyValue,
  PageHeader,
  RiskBadge,
  Skeleton,
  Table,
  Td,
  Th,
  Tr,
} from '../components/ui.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import { useApi } from '../hooks/useApi.js'
import { api } from '../services/api.js'
import { humanise } from '../utils/format.js'

export default function SettingsPage() {
  const { user, permissions, isAdmin, can } = useAuth()
  const settings = useApi(() => api.settings(), [])
  const users = useApi(() => api.listUsers(), [], { enabled: can('users:manage') })

  const data = settings.data

  return (
    <>
      <PageHeader
        icon={SettingsIcon}
        title="Settings"
        subtitle="Platform configuration, risk thresholds, active engines and role permissions."
      />

      {settings.error && <ErrorState error={settings.error} onRetry={settings.reload} />}
      {settings.loading && <Skeleton className="h-64" />}

      {data && (
        <div className="space-y-3">
          <div className="grid gap-3 lg:grid-cols-2">
            <Card>
              <CardHeader icon={Database} title="Deployment" />
              <KeyValue label="Application" value={data.app_name} />
              <KeyValue label="Environment" value={data.environment.toUpperCase()} />
              <KeyValue label="Version" value={data.version} mono />
              <KeyValue label="Database engine" value={data.database_engine} mono />
              {data.environment !== 'production' && (
                <Advisory className="mt-2">
                  This deployment runs on synthetic data. No payment provider is integrated and no
                  real financial data is processed.
                </Advisory>
              )}
            </Card>

            <Card>
              <CardHeader
                icon={ShieldCheck}
                title="Risk decision thresholds"
                subtitle="Score bands that map a 0-100 score onto an action. Configured via environment variables."
              />
              <div className="space-y-2">
                {[
                  ['LOW', `0 – ${data.thresholds.medium - 1}`, 'Allow'],
                  [
                    'MEDIUM',
                    `${data.thresholds.medium} – ${data.thresholds.high - 1}`,
                    'Monitor / additional verification',
                  ],
                  [
                    'HIGH',
                    `${data.thresholds.high} – ${data.thresholds.critical - 1}`,
                    'Review / hold',
                  ],
                  ['CRITICAL', `${data.thresholds.critical} – 100`, 'Block / escalate'],
                ].map(([band, range, action]) => (
                  <div
                    key={band}
                    className="flex items-center gap-3 rounded border border-ink-700 bg-ink-900/60 px-2.5 py-2"
                  >
                    <RiskBadge level={band} />
                    <span className="tnum font-mono text-2xs text-slateish-200">{range}</span>
                    <span className="ml-auto text-2xs text-slateish-400">{action}</span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-2xs leading-snug text-slateish-400">
                These are demonstration thresholds. In production they would be set by the
                institution&apos;s risk appetite and reviewed periodically.
              </p>
            </Card>
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Proactive model engine"
                action={
                  <Chip tone={data.ml_engine.trained ? 'low' : 'medium'}>
                    {data.ml_engine.trained ? 'trained' : 'untrained fallback'}
                  </Chip>
                }
              />
              {Object.entries(data.ml_engine).map(([key, value]) => (
                <KeyValue
                  key={key}
                  label={humanise(key)}
                  value={typeof value === 'boolean' ? (value ? 'yes' : 'no') : String(value)}
                  mono={key !== 'notes' && key !== 'training_data'}
                />
              ))}
            </Card>

            <Card>
              <CardHeader
                title="Graph / GNN engine"
                action={
                  <Chip tone={data.gnn_engine.trained ? 'low' : 'medium'}>
                    {data.gnn_engine.trained ? 'trained GNN' : 'untrained analytic'}
                  </Chip>
                }
              />
              {Object.entries(data.gnn_engine).map(([key, value]) => (
                <KeyValue
                  key={key}
                  label={humanise(key)}
                  value={typeof value === 'boolean' ? (value ? 'yes' : 'no') : String(value)}
                  mono={key !== 'notes' && key !== 'training_data' && key !== 'architecture'}
                />
              ))}
            </Card>
          </div>

          {/* --------------------------------------------- role permissions */}
          <Card padded={false}>
            <div className="p-4 pb-2">
              <CardHeader
                icon={Lock}
                title="Role permissions"
                subtitle="Capability matrix held server-side. The frontend receives the resolved list only to hide controls; every endpoint re-checks."
                className="mb-0"
              />
            </div>
            <div className="grid gap-3 p-4 md:grid-cols-2">
              {Object.entries(data.roles).map(([role, caps]) => (
                <div key={role} className="rounded border border-ink-700 bg-ink-900/60 p-3">
                  <div className="mb-2 flex items-center gap-2">
                    <span className="text-xs font-semibold text-slateish-100">{role}</span>
                    {user?.role === role && <Chip tone="info">your role</Chip>}
                    <span className="tnum ml-auto font-mono text-2xs text-slateish-400">
                      {caps.length} capabilities
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {caps.map((cap) => (
                      <Chip
                        key={cap}
                        tone={permissions.includes(cap) && user?.role === role ? 'low' : 'neutral'}
                      >
                        {cap}
                      </Chip>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* ------------------------------------------------- user admin */}
          {can('users:manage') && (
            <Card padded={false}>
              <div className="p-4 pb-2">
                <CardHeader
                  icon={Users}
                  title="Users"
                  subtitle="Administrator view. Passwords are bcrypt-hashed and never retrievable."
                  className="mb-0"
                />
              </div>
              {users.loading ? (
                <div className="p-4">
                  <Skeleton className="h-24" />
                </div>
              ) : users.data?.length ? (
                <Table>
                  <thead>
                    <tr>
                      <Th>Username</Th>
                      <Th>Full name</Th>
                      <Th>Email</Th>
                      <Th>Role</Th>
                      <Th>Team</Th>
                      <Th align="center">Active</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.data.map((u) => (
                      <Tr key={u.username}>
                        <Td mono className="text-slateish-100">
                          {u.username}
                        </Td>
                        <Td>{u.full_name}</Td>
                        <Td className="text-slateish-400">{u.email}</Td>
                        <Td>
                          <Chip tone={u.role === 'ADMIN' ? 'accent' : 'neutral'}>{u.role}</Chip>
                        </Td>
                        <Td className="text-slateish-400">{u.team ?? '—'}</Td>
                        <Td align="center">
                          {u.is_active ? (
                            <span className="text-risk-low">yes</span>
                          ) : (
                            <span className="text-slateish-400">no</span>
                          )}
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </Table>
              ) : (
                <EmptyState title="No users" />
              )}
            </Card>
          )}

          {!isAdmin && (
            <Advisory>
              Some configuration is visible only to administrators. Your role is{' '}
              <strong className="text-slateish-200">{user?.role}</strong>.
            </Advisory>
          )}
        </div>
      )}
    </>
  )
}
