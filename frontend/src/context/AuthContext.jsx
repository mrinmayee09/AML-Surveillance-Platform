/**
 * Authentication state.
 *
 * The token lives in sessionStorage only - it is never written to a cookie or
 * localStorage, and no secret or model artifact is ever held in the frontend.
 * `permissions` is used purely to hide controls the user cannot use; every
 * endpoint re-checks authorisation server-side.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { api, setUnauthorizedHandler, tokenStore } from '../services/api.js'
import { useToast } from './ToastContext.jsx'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const toast = useToast()
  const [user, setUser] = useState(null)
  const [permissions, setPermissions] = useState([])
  const [status, setStatus] = useState('loading') // loading | authenticated | anonymous

  const applySession = useCallback((payload) => {
    tokenStore.set(payload.access_token)
    setUser(payload.user)
    setPermissions(payload.permissions ?? [])
    setStatus('authenticated')
  }, [])

  const clearSession = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    setPermissions([])
    setStatus('anonymous')
  }, [])

  // A 401 from any request drops the session immediately
  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (tokenStore.get()) {
        clearSession()
        toast.warning('Your session expired. Please sign in again.')
      }
    })
  }, [clearSession, toast])

  // Restore an existing session on reload
  useEffect(() => {
    let cancelled = false
    async function restore() {
      if (!tokenStore.get()) {
        setStatus('anonymous')
        return
      }
      try {
        const payload = await api.me()
        if (!cancelled) applySession(payload)
      } catch {
        if (!cancelled) clearSession()
      }
    }
    restore()
    return () => {
      cancelled = true
    }
  }, [applySession, clearSession])

  const login = useCallback(
    async (username, password) => {
      const payload = await api.login(username, password)
      applySession(payload)
      return payload.user
    },
    [applySession],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // Logging out locally matters even if the audit call fails
    }
    clearSession()
  }, [clearSession])

  const value = useMemo(
    () => ({
      user,
      permissions,
      status,
      isAuthenticated: status === 'authenticated',
      isAdmin: user?.role === 'ADMIN',
      can: (permission) => permissions.includes(permission),
      login,
      logout,
    }),
    [user, permissions, status, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside an AuthProvider')
  return ctx
}
