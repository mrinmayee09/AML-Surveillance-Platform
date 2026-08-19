/** Small data-fetching hooks. Keeps loading/error/retry handling uniform. */
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Fetch on mount and whenever `deps` change.
 * `fetcher` receives an AbortSignal so superseded requests are cancelled.
 */
export function useApi(fetcher, deps = [], { enabled = true } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(enabled)
  const [reloadToken, setReloadToken] = useState(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return undefined
    }
    const controller = new AbortController()
    let cancelled = false

    setLoading(true)
    setError(null)

    Promise.resolve(fetcherRef.current(controller.signal))
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (cancelled || err?.name === 'AbortError' || err?.code === 'aborted') return
        setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken, enabled])

  const reload = useCallback(() => setReloadToken((t) => t + 1), [])
  return { data, error, loading, reload, setData }
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
