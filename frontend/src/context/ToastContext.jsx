import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const ToastContext = createContext(null)

const VARIANTS = {
  success: { icon: CheckCircle2, cls: 'border-risk-low/40 bg-risk-lowBg text-risk-low' },
  error: { icon: XCircle, cls: 'border-risk-high/40 bg-risk-highBg text-risk-high' },
  warning: { icon: AlertTriangle, cls: 'border-risk-medium/40 bg-risk-mediumBg text-risk-medium' },
  info: { icon: Info, cls: 'border-info/40 bg-info-soft text-info' },
}

let nextId = 1

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (message, { variant = 'info', title, duration = 5000 } = {}) => {
      const id = nextId++
      setToasts((current) => [...current, { id, message, variant, title }])
      if (duration > 0) setTimeout(() => dismiss(id), duration)
      return id
    },
    [dismiss],
  )

  const value = useMemo(
    () => ({
      push,
      dismiss,
      success: (m, o) => push(m, { ...o, variant: 'success' }),
      error: (m, o) => push(m, { ...o, variant: 'error' }),
      warning: (m, o) => push(m, { ...o, variant: 'warning' }),
      info: (m, o) => push(m, { ...o, variant: 'info' }),
    }),
    [push, dismiss],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
        role="region"
        aria-live="polite"
        aria-label="Notifications"
      >
        {toasts.map((toast) => {
          const { icon: Icon, cls } = VARIANTS[toast.variant] ?? VARIANTS.info
          return (
            <div
              key={toast.id}
              className={`pointer-events-auto flex items-start gap-2.5 rounded-card border px-3 py-2.5 shadow-raised backdrop-blur-sm animate-slide-up ${cls}`}
            >
              <Icon size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                {toast.title && (
                  <p className="text-xs font-semibold leading-tight">{toast.title}</p>
                )}
                <p className="break-words text-xs leading-snug text-slateish-200">
                  {toast.message}
                </p>
              </div>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                className="shrink-0 rounded p-0.5 text-slateish-400 transition-colors hover:text-slateish-100"
                aria-label="Dismiss notification"
              >
                <X size={13} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside a ToastProvider')
  return ctx
}
