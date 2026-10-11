/** Small data-fetching hooks. Keeps loading/error/retry handling uniform. */
import { useCallback, useEffect, useRef, useState } from 'react'

/** Window event other code dispatches when alert data has changed server-side. */
export const ALERTS_CHANGED_EVENT = 'aml:alerts-changed'

/** Tell every listening view (header badge, alert lists...) to refresh. */
export function notifyAlertsChanged() {
  window.dispatchEvent(new Event(ALERTS_CHANGED_EVENT))
}

/**
 * Fetch on mount and whenever `deps` change.
 * `fetcher` receives an AbortSignal so superseded requests are cancelled.
 *
 * Two kinds of fetch:
 *  - a deps change is a NEW query: previous data is cleared, `loading` is true,
 *    so a view never shows one record's data under another record's heading.
 *  - `reload()`, polling, refetch-on-focus and `refetchOn` events are REFRESHES
 *    of the same query: the current data stays on screen, `refreshing` is true,
 *    and a failed refresh keeps the data and only sets `error`.
 *
 * Options:
 *  - enabled          skip fetching entirely while false
 *  - refetchInterval  ms between background refreshes (paused while the tab is hidden)
 *  - refetchOnFocus   refresh when the tab becomes visible again
 *  - refetchOn        window event name(s) that trigger a refresh
 */
export function useApi(
  fetcher,
  deps = [],
  { enabled = true, refetchInterval = 0, refetchOnFocus = false, refetchOn = null } = {},
) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(enabled)
  const [refreshing, setRefreshing] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const backgroundRef = useRef(false)
  const hasDataRef = useRef(false)

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      setRefreshing(false)
      return undefined
    }
    const controller = new AbortController()
    let cancelled = false
    // A refresh with nothing on screen yet (e.g. retry after a failed first
    // load) behaves like a fresh load, so the user sees it working.
    const background = backgroundRef.current && hasDataRef.current
    backgroundRef.current = false

    if (background) {
      setRefreshing(true)
    } else {
      hasDataRef.current = false
      setData(null)
      setLoading(true)
      setError(null)
    }

    Promise.resolve(fetcherRef.current(controller.signal))
      .then((result) => {
        if (cancelled) return
        hasDataRef.current = result !== null && result !== undefined
        setData(result)
        setError(null)
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError' || err?.code === 'aborted') return
        setError(err)
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
        setRefreshing(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken, enabled])

  const reload = useCallback(() => {
    backgroundRef.current = true
    setReloadToken((t) => t + 1)
  }, [])

  useEffect(() => {
    if (!enabled || !refetchInterval) return undefined
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') reload()
    }, refetchInterval)
    return () => clearInterval(id)
  }, [enabled, refetchInterval, reload])

  useEffect(() => {
    if (!enabled || !refetchOnFocus) return undefined
    const onVisible = () => {
      if (document.visibilityState === 'visible') reload()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [enabled, refetchOnFocus, reload])

  const events = [].concat(refetchOn ?? []).join('|')
  useEffect(() => {
    if (!enabled || !events) return undefined
    const names = events.split('|')
    names.forEach((name) => window.addEventListener(name, reload))
    return () => names.forEach((name) => window.removeEventListener(name, reload))
  }, [enabled, events, reload])

  return { data, error, loading, refreshing, reload, setData }
}

/** Wraps a mutating call with pending state and error surfacing. */
export function useMutation(action) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)

  const run = useCallback(
    async (...args) => {
      setPending(true)
      setError(null)
      try {
        return await action(...args)
      } catch (err) {
        setError(err)
        throw err
      } finally {
        setPending(false)
      }
    },
    [action],
  )

  return { run, pending, error }
}

/** Debounce a rapidly-changing value (search boxes). */
export function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}
