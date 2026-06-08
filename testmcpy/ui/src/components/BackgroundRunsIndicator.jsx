import React, { useEffect, useState, useRef } from 'react'
import { Activity, Loader2, Square, ChevronDown } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

/**
 * Sidebar badge that lists in-flight runs from /api/runs and offers a
 * one-click cancel for each one — works regardless of which page the
 * user is on (SC-108217). Pre-fix, a run started on /tests was
 * completely invisible once the user navigated to /reports or anywhere
 * else, and there was no kill switch.
 *
 * Polls every 5s (cheap; the endpoint is just an in-memory dict scan).
 * Renders nothing when no runs are active — zero visual cost on the
 * common case.
 */
export default function BackgroundRunsIndicator({ showLabels = true }) {
  const [runs, setRuns] = useState([])
  const [open, setOpen] = useState(false)
  const [stoppingIds, setStoppingIds] = useState(() => new Set())
  const navigate = useNavigate()
  const popoverRef = useRef(null)

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const res = await fetch('/api/runs?active_only=true')
        if (!res.ok) return
        const data = await res.json()
        if (!cancelled) setRuns(Array.isArray(data.runs) ? data.runs : [])
      } catch (e) {
        // Server unreachable — leave runs as-is; the next tick will retry.
      }
    }
    tick()
    const id = setInterval(tick, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Close popover on outside click.
  useEffect(() => {
    if (!open) return
    const onClick = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const handleStop = async (runId) => {
    setStoppingIds(prev => new Set(prev).add(runId))
    try {
      await fetch(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: 'POST' })
    } catch (e) {
      // ignore — the next poll will reflect the actual state
    }
  }

  if (runs.length === 0) return null

  return (
    <div ref={popoverRef} className="relative px-2">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg border transition-colors ${
          open
            ? 'bg-primary/15 border-primary/40 text-primary'
            : 'bg-yellow-500/10 border-yellow-500/30 text-yellow-300 hover:bg-yellow-500/15'
        }`}
        title={`${runs.length} run${runs.length === 1 ? '' : 's'} in progress`}
      >
        <Loader2 size={13} className="animate-spin flex-shrink-0" />
        {showLabels && (
          <>
            <span className="text-xs font-medium">{runs.length} run{runs.length === 1 ? '' : 's'}</span>
            <ChevronDown size={11} className={`ml-auto transition-transform ${open ? 'rotate-180' : ''}`} />
          </>
        )}
      </button>
      {open && (
        <div className="absolute z-50 left-2 right-2 mt-1 max-w-[28rem] min-w-[20rem] rounded-lg border border-border bg-surface-elevated shadow-lg overflow-hidden">
          <div className="px-3 py-2 border-b border-border text-[11px] font-semibold uppercase tracking-wider text-text-tertiary flex items-center gap-2">
            <Activity size={12} />
            <span>In-flight runs</span>
          </div>
          <div className="max-h-72 overflow-y-auto divide-y divide-border">
            {runs.map(run => {
              const label = describeRun(run)
              const isStopping = stoppingIds.has(run.run_id)
              return (
                <div key={run.run_id} className="px-3 py-2 flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-text-primary truncate" title={label}>
                      {label}
                    </div>
                    <div className="text-[10px] text-text-tertiary font-mono truncate">
                      {run.run_id} · {run.kind}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false)
                      navigate('/tests')
                    }}
                    className="text-[10px] px-2 py-1 rounded bg-primary/15 text-primary hover:bg-primary/25"
                    title="Open the Tests page (will reattach if you started this run here)"
                  >
                    Open
                  </button>
                  <button
                    type="button"
                    disabled={isStopping}
                    onClick={() => handleStop(run.run_id)}
                    className={`text-[10px] px-2 py-1 rounded inline-flex items-center gap-1 ${
                      isStopping
                        ? 'bg-text-disabled/15 text-text-disabled cursor-not-allowed'
                        : 'bg-red-500/15 text-red-300 hover:bg-red-500/25'
                    }`}
                    title="Kill this run"
                  >
                    <Square size={9} fill="currentColor" />
                    {isStopping ? 'Stopping…' : 'Kill'}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function describeRun(run) {
  const meta = run.meta || {}
  if (run.kind === 'directory') {
    const folder = meta.folder || 'directory batch'
    const n = (meta.files || []).length
    return `${folder} (${n} file${n === 1 ? '' : 's'})`
  }
  const path = meta.test_path || ''
  const name = path.split('/').filter(Boolean).slice(-1)[0] || path
  if (meta.test_name) return `${name} → ${meta.test_name}`
  return name || 'single run'
}
