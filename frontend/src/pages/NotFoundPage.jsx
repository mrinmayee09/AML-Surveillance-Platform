import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-950 px-4">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full border border-ink-700 bg-ink-850">
          <Compass size={20} className="text-slateish-400" aria-hidden="true" />
        </div>
        <h1 className="text-base font-semibold text-white">Page not found</h1>
        <p className="mt-1.5 text-xs text-slateish-400">
          That route does not exist in the investigator console.
        </p>
        <Link
          to="/"
          className="mt-4 inline-block rounded border border-info bg-info px-3 py-1.5 text-xs font-medium text-white hover:bg-info/85"
        >
          Back to dashboard
        </Link>
      </div>
    </div>
  )
}
