/**
 * Route-level error boundary.
 *
 * A crash in one panel should degrade that panel, not blank the whole console —
 * an investigator mid-case should never lose the rest of the page.
 */
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Left as console output on purpose: this prototype has no error-reporting
    // backend, and silently swallowing a crash would be worse.
    console.error('Unhandled UI error:', error, info?.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div className="rounded-card border border-risk-high/40 bg-risk-highBg p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-risk-high" aria-hidden="true" />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slateish-100">
              This view failed to render
            </h2>
            <p className="mt-1 text-xs text-slateish-300">
              The rest of the console is unaffected. Reloading usually clears a transient
              failure; if it persists, the message below is the detail to report.
            </p>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded border border-ink-700 bg-ink-900/80 p-2 text-2xs text-slateish-400">
              {error.message ?? String(error)}
            </pre>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="mt-3 inline-flex items-center gap-1.5 rounded border border-ink-600 bg-ink-800 px-2.5 py-1.5 text-xs font-medium text-slateish-200 hover:bg-ink-750"
            >
              <RotateCcw size={13} aria-hidden="true" /> Retry this view
            </button>
          </div>
        </div>
      </div>
    )
  }
}
