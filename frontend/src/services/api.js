/**
 * API client.
 *
 * All business logic lives on the backend; this module only transports data.
 * The JWT is held in sessionStorage (cleared when the tab closes) and attached
 * as a bearer token. No secret, key or threshold is ever hard-coded here.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const TOKEN_KEY = 'aml.access_token'

export class ApiError extends Error {
  constructor(message, { status, code, field, requestId, details } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.field = field
    this.requestId = requestId
    this.details = details
  }

  get isAuthError() {
    return this.status === 401
  }

  get isForbidden() {
    return this.status === 403
  }
}

export const tokenStore = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
}

/** Callback invoked when the server rejects our token, so the app can log out. */
let onUnauthorized = null
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

function buildQuery(params) {
  if (!params) return ''
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, String(item)))
    } else {
      search.append(key, String(value))
    }
  })
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

async function request(path, { method = 'GET', body, params, signal } = {}) {
  const token = tokenStore.get()
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetch(`${BASE_URL}/api${path}${buildQuery(params)}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new ApiError(
      'Cannot reach the API. Is the backend running on port 8000?',
      { status: 0, code: 'network_error' }
    )
  }

  if (response.status === 204) return null

  const requestId = response.headers.get('X-Request-ID')
  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { error: { code: 'bad_response', message: text.slice(0, 300) } }
    }
  }

  if (!response.ok) {
    // FastAPI puts our structured errors in `detail`; our own handlers use `error`
    const detail = payload?.detail ?? payload?.error ?? {}
    const message =
      (typeof detail === 'string' ? detail : detail.message) ||
      `Request failed with status ${response.status}`

    if (response.status === 401 && onUnauthorized) onUnauthorized()

    throw new ApiError(message, {
      status: response.status,
      code: detail.code,
      field: detail.field,
      requestId,
      details: payload?.details,
    })
  }

  return payload
}

const get = (path, params, signal) => request(path, { params, signal })
const post = (path, body, params) => request(path, { method: 'POST', body, params })
const patch = (path, body) => request(path, { method: 'PATCH', body })
/** Path segment from user/data input (refs, search text) - never raw. */
const seg = (value) => encodeURIComponent(String(value))

export const api = {
  // --- auth ---------------------------------------------------------
  login: (username, password) => post('/auth/login', { username, password }),
  me: () => get('/auth/me'),
  logout: () => post('/auth/logout'),
  listUsers: () => get('/auth/users'),
  createUser: (payload) => post('/auth/users', payload),
  updateUser: (username, payload) => patch(`/auth/users/${seg(username)}`, payload),

  // --- dashboard ----------------------------------------------------
  dashboard: (window, signal) => get('/dashboard/overview', { window }, signal),
  health: () => get('/health'),
  settings: () => get('/settings'),

  // --- transactions -------------------------------------------------
  transactions: (params, signal) => get('/transactions', params, signal),
  transaction: (ref, signal) => get(`/transactions/${seg(ref)}`, undefined, signal),
  orders: (params, signal) => get('/transactions/orders', params, signal),
  validatePayment: (payload) => post('/transactions/validate', payload),
  analyzeTransaction: (payload) => post('/transactions/analyze', payload),
  gatewayDecision: (payload) => post('/transactions/decision', payload),

  // --- customers ----------------------------------------------------
  customers: (params, signal) => get('/customers', params, signal),
  customer: (ref, signal) => get(`/customers/${seg(ref)}`, undefined, signal),
  customerRisk: (ref, signal) => get(`/customers/${seg(ref)}/risk`, undefined, signal),
  proactiveOverview: (params, signal) => get('/customers/proactive-overview', params, signal),

  // --- alerts / reactive --------------------------------------------
  alerts: (params, signal) => get('/alerts', params, signal),
  alert: (ref, signal) => get(`/alerts/${seg(ref)}`, undefined, signal),
  alertStats: (signal) => get('/alerts/stats', undefined, signal),
  updateAlertStatus: (ref, payload) => patch(`/alerts/${seg(ref)}/status`, payload),
  assignAlert: (ref, assignee_username) =>
    post(`/alerts/${seg(ref)}/assign`, { assignee_username }),
  reactiveOverview: (params, signal) => get('/reactive/overview', params, signal),
  runReactiveSweep: (params) => post('/reactive/run', undefined, params),

  // --- networks / GNN -----------------------------------------------
  networks: (params, signal) => get('/networks', params, signal),
  network: (ref, signal) => get(`/networks/${seg(ref)}`, undefined, signal),
  networkGraph: (ref, signal) => get(`/networks/${seg(ref)}/graph`, undefined, signal),
  networkAssessment: (ref, signal) =>
    get(`/networks/${seg(ref)}/assessment`, undefined, signal),
  exploreGraph: (params, signal) => get('/networks/graph', params, signal),
  inspectNode: (accountRef, params, signal) =>
    get(`/networks/node/${seg(accountRef)}`, params, signal),
  runNetworkAnalysis: (params) => post('/networks/analyse', undefined, params),
  // Window GNN (GraphSAGE trained on IBM AMLworld)
  gnnStatus: (signal) => get('/networks/gnn/status', undefined, signal),
  runGnnScoring: (params) => post('/networks/gnn/score', undefined, params),
  gnnAccount: (accountRef, signal) =>
    get(`/networks/gnn/accounts/${seg(accountRef)}`, undefined, signal),

  // --- investigations -----------------------------------------------
  investigations: (params, signal) => get('/investigations', params, signal),
  investigation: (ref, signal) => get(`/investigations/${seg(ref)}`, undefined, signal),
  createInvestigation: (payload) => post('/investigations', payload),
  addInvestigationNote: (ref, payload) => post(`/investigations/${seg(ref)}/notes`, payload),
  updateInvestigationStatus: (ref, payload) =>
    patch(`/investigations/${seg(ref)}/status`, payload),
  assignInvestigation: (ref, assignee_username) =>
    post(`/investigations/${seg(ref)}/assign`, { assignee_username }),

  // --- rules --------------------------------------------------------
  rules: (params, signal) => get('/rules', params, signal),
  updateRule: (code, payload) => patch(`/rules/${seg(code)}`, payload),
  createRule: (payload) => post('/rules', payload),

  // --- models / audit / demo ----------------------------------------
  modelInsights: (signal) => get('/models/insights', undefined, signal),
  auditLogs: (params, signal) => get('/audit-logs', params, signal),
  auditFacets: () => get('/audit-logs/actions'),
  demoScenarios: () => get('/demo/scenarios'),
  runDemo: (payload) => post('/demo/run', payload),
}
