import React, { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { formatDate, formatCost, formatDurationMs } from '../utils/formatters'
import {
  TrendingUp,
  Trophy,
  Grid3x3,
  Zap,
  X,
  CheckCircle,
  XCircle,
  Loader2,
  RefreshCw,
  AlertTriangle,
  Copy,
  Check,
  Calendar,
  ExternalLink,
} from 'lucide-react'

const DATE_RANGES = [
  { value: '7d', label: 'Last 7 days', days: 7 },
  { value: '30d', label: 'Last 30 days', days: 30 },
  { value: '90d', label: 'Last 90 days', days: 90 },
  { value: 'all', label: 'All time', days: null },
]

const SINGLE_RUN_TITLE = 'single run — not statistically meaningful'

function dateFromForRange(range) {
  const entry = DATE_RANGES.find(r => r.value === range)
  if (!entry || entry.days == null) return null
  return new Date(Date.now() - entry.days * 24 * 60 * 60 * 1000).toISOString()
}

function formatPct(rate) {
  if (rate == null) return '—'
  return `${Math.round(rate * 100)}%`
}

// Tiny inline SVG sparkline of daily pass rates (0..1), up to 7 points.
function Sparkline({ trend }) {
  const points = (trend || []).slice(-7)
  if (points.length === 0) return null
  const w = 36
  const h = 10
  if (points.length === 1) {
    const cy = h - 1.5 - points[0] * (h - 3)
    return (
      <svg width={w} height={h} className="inline-block opacity-70" aria-hidden="true">
        <circle cx={w / 2} cy={cy} r={1.5} fill="currentColor" />
      </svg>
    )
  }
  const step = w / (points.length - 1)
  const coords = points
    .map((v, i) => `${(i * step).toFixed(1)},${(h - 1.5 - v * (h - 3)).toFixed(1)}`)
    .join(' ')
  return (
    <svg width={w} height={h} className="inline-block opacity-70" aria-hidden="true">
      <polyline points={coords} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

// One matrix cell: pass% + n + sparkline + flaky marker, statistically honest.
function MatrixCell({ cell, onClick }) {
  if (!cell) {
    return (
      <td
        className="px-2 py-2 text-center text-text-disabled border-b border-border min-w-[88px]"
        title="No runs for this test under this config"
      >
        —
      </td>
    )
  }

  const singleRun = cell.n === 1
  let tint = 'bg-surface text-text-secondary' // neutral for n=1
  if (!singleRun) {
    if (cell.pass_rate === 1) tint = 'bg-success/15 text-success'
    else if (cell.pass_rate === 0) tint = 'bg-error/15 text-error'
    else tint = 'bg-warning/15 text-warning'
  }

  const title = singleRun
    ? SINGLE_RUN_TITLE
    : `${formatPct(cell.pass_rate)} over ${cell.n} results · avg score ${cell.avg_score} · ${formatDurationMs(cell.avg_duration_ms)} · ${formatCost(cell.avg_cost)}`

  return (
    <td className="px-1 py-1 border-b border-border min-w-[88px]">
      <button
        onClick={onClick}
        title={title}
        className={`w-full rounded-md px-2 py-1.5 flex flex-col items-center gap-0.5 transition-colors hover:ring-1 hover:ring-primary/50 ${tint}`}
      >
        <span className="flex items-center gap-1">
          <span className="text-sm font-semibold">{formatPct(cell.pass_rate)}</span>
          {cell.flaky && <Zap size={10} className="text-warning" title="flaky" />}
        </span>
        <span className="text-[10px] text-text-tertiary">n={cell.n}</span>
        <Sparkline trend={cell.trend} />
      </button>
    </td>
  )
}

// Right-hand drill-down panel: chronological history of one question × config.
function DrillPanel({ drill, suite, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams({ question_id: drill.questionId })
        if (suite) params.set('suite_id', suite)
        if (drill.config.model) params.set('model', drill.config.model)
        if (drill.config.provider) params.set('provider', drill.config.provider)
        if (drill.config.mcp_profile) params.set('mcp_profile', drill.config.mcp_profile)
        const res = await fetch(`/api/analytics/question-history?${params}`)
        if (!res.ok) throw new Error(`Failed to load history: ${res.status}`)
        const json = await res.json()
        if (!cancelled) setData(json)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [drill, suite])

  return (
    <div className="fixed inset-0 z-40 md:static md:z-auto md:inset-auto w-full md:w-96 flex-shrink-0 md:border-l border-border bg-surface-elevated overflow-auto">
      <div className="sticky top-0 bg-surface-elevated border-b border-border px-4 py-3 flex items-start justify-between gap-2 z-10">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary truncate" title={drill.questionId}>
            {drill.questionId}
          </h3>
          <p className="text-xs text-text-tertiary truncate" title={drill.config.key}>
            {drill.config.key}
          </p>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-surface-hover text-text-tertiary hover:text-text-primary flex-shrink-0"
          aria-label="Close panel"
        >
          <X size={16} />
        </button>
      </div>

      <div className="p-3">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="animate-spin text-primary" size={24} />
          </div>
        ) : error ? (
          <div className="p-3 bg-error/10 border border-error/30 rounded-lg text-sm text-error">
            {error}
          </div>
        ) : !data?.points?.length ? (
          <p className="text-sm text-text-tertiary text-center py-6">No history for this cell</p>
        ) : (
          <div className="space-y-2">
            {data.points.map((pt, idx) => (
              <div
                key={`${pt.run_id}-${idx}`}
                className="p-2.5 rounded-lg border border-border bg-surface flex items-start gap-2"
              >
                {pt.passed ? (
                  <CheckCircle size={16} className="text-success flex-shrink-0 mt-0.5" />
                ) : (
                  <XCircle size={16} className="text-error flex-shrink-0 mt-0.5" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-text-secondary">{formatDate(pt.started_at)}</div>
                  <div className="flex items-center gap-3 mt-1 text-[11px] text-text-tertiary">
                    <span>score {pt.score}</span>
                    <span>{formatDurationMs(pt.duration_ms)}</span>
                    <span>{formatCost(pt.cost_usd)}</span>
                  </div>
                  {pt.error && (
                    <div className="mt-1 text-[11px] text-error truncate" title={pt.error}>
                      {pt.error}
                    </div>
                  )}
                </div>
                <Link
                  to={`/reports?run=${encodeURIComponent(pt.run_id)}`}
                  className="text-text-tertiary hover:text-primary flex-shrink-0"
                  title="Open run in Reports"
                >
                  <ExternalLink size={14} />
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function EmptyState() {
  const [copied, setCopied] = useState(false)
  const command = 'testmcpy bench tests/ --models claude-sonnet-4-5,gpt-4o --repeat 3'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Copy failed:', err)
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="text-center max-w-lg">
        <Grid3x3 size={48} className="mx-auto mb-3 text-text-disabled opacity-50" />
        <p className="text-text-primary font-medium">No completed runs across configs yet</p>
        <div className="mt-4 flex items-center gap-2 bg-surface border border-border rounded-lg px-3 py-2">
          <code className="flex-1 text-left text-xs font-mono text-text-secondary overflow-x-auto whitespace-nowrap">
            {command}
          </code>
          <button
            onClick={copy}
            className="p-1.5 rounded hover:bg-surface-hover text-text-tertiary hover:text-text-primary flex-shrink-0"
            title="Copy command"
            aria-label="Copy command"
          >
            {copied ? <Check size={14} className="text-success" /> : <Copy size={14} />}
          </button>
        </div>
        <p className="text-sm text-text-tertiary mt-3">
          or run the same suite with different --model/--profile flags
        </p>
      </div>
    </div>
  )
}

function Performance() {
  const [activeTab, setActiveTab] = useState('matrix')
  const [matrix, setMatrix] = useState(null)
  const [leaderboard, setLeaderboard] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [warningsDismissed, setWarningsDismissed] = useState(false)
  const [drill, setDrill] = useState(null)

  // Filters
  const [suite, setSuite] = useState('')
  const [dateRange, setDateRange] = useState('30d')
  const [minRuns, setMinRuns] = useState(1)
  const [includeProfile, setIncludeProfile] = useState(true)
  const [suiteOptions, setSuiteOptions] = useState([])

  useEffect(() => {
    const loadFilters = async () => {
      try {
        const res = await fetch('/api/results/filters')
        if (!res.ok) return
        const data = await res.json()
        setSuiteOptions(data.test_files || [])
      } catch (err) {
        console.error('Failed to load filter options:', err)
      }
    }
    loadFilters()
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (suite) params.set('suite_id', suite)
      const dateFrom = dateFromForRange(dateRange)
      if (dateFrom) params.set('date_from', dateFrom)
      params.set('include_profile', includeProfile ? 'true' : 'false')

      const matrixParams = new URLSearchParams(params)
      matrixParams.set('min_runs', String(minRuns))

      const [matrixRes, lbRes] = await Promise.all([
        fetch(`/api/analytics/matrix?${matrixParams}`),
        fetch(`/api/analytics/leaderboard?${params}`),
      ])
      if (!matrixRes.ok) throw new Error(`Failed to load matrix: ${matrixRes.status}`)
      if (!lbRes.ok) throw new Error(`Failed to load leaderboard: ${lbRes.status}`)
      const [matrixData, lbData] = await Promise.all([matrixRes.json(), lbRes.json()])
      setMatrix(matrixData)
      setLeaderboard(lbData)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [suite, dateRange, minRuns, includeProfile])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Close drill panel when filters change — its cell may no longer exist.
  useEffect(() => {
    setDrill(null)
  }, [suite, dateRange, minRuns, includeProfile])

  const configs = matrix?.configs || []
  const rows = matrix?.rows || []
  const warnings = matrix?.warnings || []
  const lbConfigs = leaderboard?.configs || []
  const isEmpty = !loading && configs.length === 0

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-6 py-4 border-b border-border bg-surface-elevated">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <TrendingUp size={24} className="text-primary" />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-semibold text-text-primary">Performance</h1>
              <p className="text-sm text-text-tertiary">Per-test results across model and MCP configurations</p>
            </div>
          </div>
          <button onClick={loadData} className="btn btn-ghost" disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          <select
            value={suite}
            onChange={(e) => setSuite(e.target.value)}
            className="input text-xs py-1.5 px-2"
            aria-label="Suite"
          >
            <option value="">All Suites</option>
            {suiteOptions.map(f => (
              <option key={f} value={f}>{f.split('/').pop()}</option>
            ))}
          </select>
          <div className="flex items-center gap-1 bg-surface border border-border rounded-lg px-2 py-1">
            <Calendar size={13} className="text-text-tertiary" />
            <select
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              className="bg-transparent text-xs text-text-primary outline-none cursor-pointer py-0.5"
              aria-label="Date range"
            >
              {DATE_RANGES.map(r => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-1.5 text-xs text-text-tertiary">
            Min runs
            <select
              value={minRuns}
              onChange={(e) => setMinRuns(Number(e.target.value))}
              className="input text-xs py-1.5 px-2"
              aria-label="Minimum runs"
            >
              {[1, 2, 3, 5].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-surface border border-border">
            <button
              onClick={() => setIncludeProfile(false)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                !includeProfile
                  ? 'bg-primary text-white'
                  : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              By model
            </button>
            <button
              onClick={() => setIncludeProfile(true)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                includeProfile
                  ? 'bg-primary text-white'
                  : 'text-text-secondary hover:text-text-primary hover:bg-surface-hover'
              }`}
            >
              By model + MCP profile
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-2 mt-4">
          <button
            onClick={() => setActiveTab('matrix')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
              activeTab === 'matrix'
                ? 'bg-primary text-white'
                : 'bg-surface hover:bg-surface-hover text-text-secondary'
            }`}
          >
            <Grid3x3 size={16} />
            Matrix
          </button>
          <button
            onClick={() => setActiveTab('leaderboard')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
              activeTab === 'leaderboard'
                ? 'bg-primary text-white'
                : 'bg-surface hover:bg-surface-hover text-text-secondary'
            }`}
          >
            <Trophy size={16} />
            Leaderboard
          </button>
        </div>
      </div>

      {/* Content */}
      {loading && !matrix ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="animate-spin text-primary" size={32} />
        </div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="p-4 bg-error/10 border border-error/30 rounded-lg text-sm text-error max-w-lg">
            {error}
          </div>
        </div>
      ) : isEmpty ? (
        <EmptyState />
      ) : (
        <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
          <div className="flex-1 overflow-auto p-4 md:p-6">
            {/* Warnings banner */}
            {activeTab === 'matrix' && warnings.length > 0 && !warningsDismissed && (
              <div className="mb-4 p-3 rounded-lg bg-warning/10 border border-warning/30 flex items-start gap-2">
                <AlertTriangle size={16} className="text-warning flex-shrink-0 mt-0.5" />
                <div className="flex-1 text-sm text-warning">
                  {warnings.map((w, i) => <div key={i}>{w}</div>)}
                </div>
                <button
                  onClick={() => setWarningsDismissed(true)}
                  className="p-0.5 rounded hover:bg-warning/20 text-warning flex-shrink-0"
                  aria-label="Dismiss warnings"
                >
                  <X size={14} />
                </button>
              </div>
            )}

            {activeTab === 'matrix' ? (
              <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="px-3 py-2 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide sticky left-0 z-[1] bg-surface-elevated">
                        Test
                      </th>
                      {configs.map(cfg => (
                        <th
                          key={cfg.key}
                          className="px-2 py-2 text-center text-xs font-semibold text-text-secondary min-w-[88px] max-w-[140px]"
                          title={cfg.key}
                        >
                          <div className="truncate">{cfg.key}</div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(row => (
                      <tr key={row.question_id} className="hover:bg-surface-hover/40">
                        <td
                          className="px-3 py-2 text-xs font-mono text-text-primary border-b border-border sticky left-0 z-[1] bg-surface-elevated max-w-[140px] md:max-w-[220px] truncate"
                          title={row.question_id}
                        >
                          {row.question_id}
                        </td>
                        {configs.map(cfg => (
                          <MatrixCell
                            key={cfg.key}
                            cell={row.cells[cfg.key]}
                            onClick={() => setDrill({ questionId: row.question_id, config: cfg })}
                          />
                        ))}
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-surface">
                      <td className="px-3 py-2 text-xs font-semibold text-text-secondary sticky left-0 z-[1] bg-surface">
                        All tests
                      </td>
                      {configs.map(cfg => (
                        <td key={cfg.key} className="px-2 py-2 text-center">
                          <div className="text-sm font-semibold text-text-primary">{formatPct(cfg.pass_rate)}</div>
                          <div className="text-[10px] text-text-tertiary">{cfg.n_runs} runs</div>
                        </td>
                      ))}
                    </tr>
                  </tfoot>
                </table>
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-border bg-surface-elevated">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="px-3 py-2 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">#</th>
                      <th className="px-3 py-2 text-left text-xs font-semibold text-text-secondary uppercase tracking-wide">Config</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-text-secondary uppercase tracking-wide">Pass rate</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-text-secondary uppercase tracking-wide">Runs</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-text-secondary uppercase tracking-wide">Flaky cells</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-text-secondary uppercase tracking-wide">Cost / pass</th>
                      <th className="px-3 py-2 text-right text-xs font-semibold text-text-secondary uppercase tracking-wide">Avg latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lbConfigs.map((cfg, idx) => (
                      <tr key={cfg.key} className="border-b border-border last:border-b-0 hover:bg-surface-hover/40">
                        <td className="px-3 py-2 text-text-tertiary">{idx + 1}</td>
                        <td className="px-3 py-2 font-mono text-xs text-text-primary">{cfg.key}</td>
                        <td className={`px-3 py-2 text-right font-semibold ${
                          cfg.n_runs <= 1
                            ? 'text-text-secondary'
                            : cfg.pass_rate === 1
                              ? 'text-success'
                              : cfg.pass_rate === 0
                                ? 'text-error'
                                : 'text-warning'
                        }`}>
                          {formatPct(cfg.pass_rate)}
                        </td>
                        <td className="px-3 py-2 text-right text-text-secondary">{cfg.n_runs}</td>
                        <td className="px-3 py-2 text-right">
                          {cfg.flaky_cells > 0 ? (
                            <span className="inline-flex items-center gap-1 text-warning">
                              <Zap size={11} />
                              {cfg.flaky_cells}
                            </span>
                          ) : (
                            <span className="text-text-tertiary">0</span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right text-text-secondary">
                          {cfg.cost_per_pass != null ? formatCost(cfg.cost_per_pass) : '—'}
                        </td>
                        <td className="px-3 py-2 text-right text-text-secondary">
                          {cfg.avg_duration_ms ? `${(cfg.avg_duration_ms / 1000).toFixed(1)}s` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {drill && (
            <DrillPanel drill={drill} suite={suite} onClose={() => setDrill(null)} />
          )}
        </div>
      )}
    </div>
  )
}

export default Performance
