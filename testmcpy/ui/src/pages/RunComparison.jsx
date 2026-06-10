import React, { useState, useEffect, useCallback } from 'react'
import {
  GitCompare,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ArrowUp,
  ArrowDown,
  Minus,
  Plus,
  Cpu,
  Clock,
  DollarSign,
  Hash,
  Trophy,
  RefreshCw,
  Share2,
  Download,
} from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ResponsiveContainer,
} from 'recharts'

function formatDuration(ms) {
  if (!ms) return '-'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function formatCost(cost) {
  if (!cost) return '$0.00'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  return `$${cost.toFixed(2)}`
}

function formatTokens(tokens) {
  if (!tokens) return '0'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(0)}K`
  return tokens.toString()
}

function RunComparison() {
  const [runs, setRuns] = useState([])
  const [selectedRunIds, setSelectedRunIds] = useState([])
  const [comparison, setComparison] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingRuns, setLoadingRuns] = useState(true)
  const [error, setError] = useState(null)
  const [filterModel, setFilterModel] = useState('')
  const [filterTestFile, setFilterTestFile] = useState('')
  const [filterOptions, setFilterOptions] = useState({ models: [], providers: [], test_files: [] })

  // Sort state
  const [sortBy, setSortBy] = useState(null)
  const [sortDir, setSortDir] = useState('desc')

  // Regressions-only toggle
  const [regressionsOnly, setRegressionsOnly] = useState(false)

  // Share feedback
  const [copiedShare, setCopiedShare] = useState(false)

  // On mount, read ?runs= from URL and pre-populate selectedRunIds
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const runsParam = params.get('runs')
    if (runsParam) {
      const ids = runsParam.split(',').filter(Boolean)
      if (ids.length > 0) {
        setSelectedRunIds(ids)
      }
    }
  }, [])

  const loadFilterOptions = useCallback(async () => {
    try {
      const res = await fetch('/api/results/filters')
      if (res.ok) setFilterOptions(await res.json())
    } catch (err) {
      console.error('Failed to load filters:', err)
    }
  }, [])

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true)
    try {
      const params = new URLSearchParams({ limit: '200' })
      if (filterModel) params.set('model', filterModel)
      if (filterTestFile) params.set('test_file', filterTestFile)
      const res = await fetch(`/api/results/list?${params}`)
      if (res.ok) {
        const data = await res.json()
        setRuns(data.runs || [])
      }
    } catch (err) {
      console.error('Failed to load runs:', err)
    } finally {
      setLoadingRuns(false)
    }
  }, [filterModel, filterTestFile])

  // Fetch filter options once on mount
  useEffect(() => {
    loadFilterOptions()
  }, [loadFilterOptions])

  // Fetch runs when filters change
  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  const toggleRun = (runId) => {
    setSelectedRunIds(prev => {
      if (prev.includes(runId)) {
        return prev.filter(id => id !== runId)
      }
      return [...prev, runId]
    })
  }

  const compareRuns = async () => {
    if (selectedRunIds.length < 2) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_ids: selectedRunIds }),
      })
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Failed: ${res.status}`)
      }
      const data = await res.json()
      setComparison(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const getCellStyle = (cell) => {
    if (!cell || cell.status === 'missing') return 'bg-surface-elevated text-text-disabled'
    if (cell.passed) return 'bg-success/10 text-success'
    return 'bg-error/10 text-error'
  }

  const getChangeIcon = (change) => {
    switch (change) {
      case 'regression':
        return <ArrowDown size={12} className="text-error" title="Regression" />
      case 'improvement':
        return <ArrowUp size={12} className="text-success" title="Improvement" />
      case 'new':
        return <Plus size={12} className="text-info-light" title="New test" />
      default:
        return null
    }
  }

  const handleSortToggle = (field) => {
    if (sortBy === field) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(field)
      setSortDir('desc')
    }
  }

  const handleShare = () => {
    const url = window.location.pathname + '?runs=' + selectedRunIds.join(',')
    navigator.clipboard.writeText(window.location.origin + url).then(() => {
      setCopiedShare(true)
      setTimeout(() => setCopiedShare(false), 2000)
    })
  }

  const handleExportCSV = () => {
    if (!comparison) return
    const runs = sortedRuns
    const header = 'Test,' + runs.map(r => r.model || r.run_id).join(',')
    const rows = comparison.rows.map(row => {
      const cols = runs.map(r => {
        const cell = row.cells[r.run_id]
        return cell?.passed ? 'pass' : 'fail'
      })
      return [row.question_id, ...cols].join(',')
    })
    const csv = [header, ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `comparison-${Date.now()}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // Derive sorted runs
  const sortedRuns = comparison ? [...comparison.runs] : []
  if (sortBy) {
    sortedRuns.sort((a, b) => {
      const va = a[sortBy] != null ? a[sortBy] : 0
      const vb = b[sortBy] != null ? b[sortBy] : 0
      return sortDir === 'desc' ? vb - va : va - vb
    })
  }

  // Chart data
  const chartData = (comparison?.runs || []).map(run => ({
    name: run.model || (run.run_id ? run.run_id.slice(0, 8) : 'Run'),
    pass_rate: run.pass_rate != null ? Math.round(run.pass_rate * 100) : 0,
  }))

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-6 py-4 border-b border-border bg-surface-elevated">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <GitCompare size={24} className="text-primary" />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-semibold text-text-primary">Run Comparison</h1>
              <p className="text-sm text-text-tertiary">Compare test runs side by side</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {comparison && (
              <>
                <button
                  onClick={handleShare}
                  className="btn btn-secondary text-xs"
                  title="Copy shareable link"
                >
                  <Share2 size={14} />
                  {copiedShare ? 'Copied!' : 'Share'}
                </button>
                <button
                  onClick={handleExportCSV}
                  className="btn btn-secondary text-xs"
                  title="Export as CSV"
                >
                  <Download size={14} />
                  Export CSV
                </button>
              </>
            )}
            <button
              onClick={compareRuns}
              disabled={selectedRunIds.length < 2 || loading}
              className="btn btn-primary disabled:opacity-50"
            >
              {loading ? <Loader2 size={16} className="animate-spin" /> : <GitCompare size={16} />}
              Compare ({selectedRunIds.length})
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4 md:p-6 space-y-6">
        {error && (
          <div className="p-4 bg-error/10 border border-error/30 rounded-lg text-error text-sm">
            {error}
          </div>
        )}

        {/* Run selector */}
        {!comparison && (
          <div className="p-4 rounded-xl bg-surface border border-border">
            <div className="flex items-center gap-3 mb-3 flex-wrap">
              <h3 className="text-sm font-semibold text-text-primary">
                Select runs to compare (min 2)
              </h3>
              <div className="flex items-center gap-2 ml-auto">
                {filterOptions.models.length > 1 && (
                  <select
                    value={filterModel}
                    onChange={(e) => setFilterModel(e.target.value)}
                    className="text-xs py-1 px-2 rounded border border-border bg-surface-elevated text-text-primary"
                  >
                    <option value="">All Models</option>
                    {filterOptions.models.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                )}
                {filterOptions.test_files.length > 1 && (
                  <select
                    value={filterTestFile}
                    onChange={(e) => setFilterTestFile(e.target.value)}
                    className="text-xs py-1 px-2 rounded border border-border bg-surface-elevated text-text-primary"
                  >
                    <option value="">All Test Files</option>
                    {filterOptions.test_files.map(f => <option key={f} value={f}>{f.split('/').pop()}</option>)}
                  </select>
                )}
                {(filterModel || filterTestFile) && (
                  <button
                    onClick={() => { setFilterModel(''); setFilterTestFile('') }}
                    className="text-xs text-text-tertiary hover:text-text-secondary"
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
            {loadingRuns ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="animate-spin text-primary" size={24} />
              </div>
            ) : runs.length === 0 ? (
              <div className="text-center py-8 text-text-tertiary">
                No test runs found. Run some tests first.
              </div>
            ) : (
              <div className="space-y-1 max-h-96 overflow-y-auto">
                {runs.map(run => {
                  const isSelected = selectedRunIds.includes(run.run_id)
                  const passRate = run.total_tests > 0
                    ? ((run.passed / run.total_tests) * 100).toFixed(0)
                    : 0
                  return (
                    <div
                      key={run.run_id}
                      onClick={() => toggleRun(run.run_id)}
                      className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                        isSelected
                          ? 'bg-primary/10 border border-primary/40'
                          : 'hover:bg-surface-hover border border-transparent'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        readOnly
                        className="rounded border-border flex-shrink-0"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm text-text-primary truncate">
                            {run.test_file}
                          </span>
                          <span className={`text-xs px-1.5 py-0.5 rounded ${
                            Number(passRate) >= 90 ? 'bg-success/20 text-success' :
                            Number(passRate) >= 70 ? 'bg-warning/20 text-warning' :
                            'bg-error/20 text-error'
                          }`}>
                            {passRate}%
                          </span>
                        </div>
                        <div className="flex items-center gap-3 mt-1 text-xs text-text-tertiary">
                          <span className="flex items-center gap-1">
                            <Cpu size={10} /> {run.model}
                          </span>
                          <span>{run.provider}</span>
                          <span>{new Date(run.timestamp).toLocaleDateString()}</span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Comparison matrix */}
        {comparison && (() => {
          // Use sortedRuns for all column rendering
          const runsToShow = sortedRuns.length > 0 ? sortedRuns : comparison.runs
          // Build run_id -> column data map for quick lookup
          const colMap = {}
          comparison.columns.forEach(c => { colMap[c.run_id] = c })

          const bestPassRate = Math.max(...comparison.columns.map(c => c.pass_rate))
          const nonzeroCosts = comparison.columns.filter(c => c.total_cost > 0).map(c => Math.round(c.total_cost * 100))
          const minCostCents = nonzeroCosts.length > 0 ? Math.min(...nonzeroCosts) : null
          const isBestCol = (col) => col.pass_rate === bestPassRate
          const isCheapestCol = (col) => col.total_cost > 0 && minCostCents !== null && Math.round(col.total_cost * 100) === minCostCents

          // Filter rows for regressions-only
          const visibleRows = regressionsOnly
            ? comparison.rows.filter(row => {
                const statuses = runsToShow.map(r => row.cells[r.run_id]?.passed)
                const hasPass = statuses.some(Boolean)
                const hasFail = statuses.some(s => s === false)
                return hasPass && hasFail
              })
            : comparison.rows

          return (
          <>
            {/* Pass Rate Chart */}
            <div className="rounded-xl bg-surface border border-border p-4">
              <h3 className="text-sm font-semibold text-text-primary mb-3">Pass Rate by Run</h3>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'currentColor' }} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: 'currentColor' }} unit="%" />
                  <Tooltip formatter={(value) => [`${value}%`, 'Pass Rate']} />
                  <Bar dataKey="pass_rate" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill="#22c55e" />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="flex items-center justify-between flex-wrap gap-2">
              <h3 className="text-sm font-semibold text-text-primary">
                Comparison Matrix ({comparison.total_questions} tests)
              </h3>
              <div className="flex items-center gap-2 flex-wrap">
                <label className="flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={regressionsOnly}
                    onChange={(e) => setRegressionsOnly(e.target.checked)}
                    className="rounded border-border"
                  />
                  Show differences only
                </label>
                <button
                  onClick={() => setComparison(null)}
                  className="btn btn-ghost text-xs"
                >
                  <RefreshCw size={14} /> New Comparison
                </button>
              </div>
            </div>

            <div className="rounded-xl bg-surface border border-border overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="p-3 text-left text-xs text-text-tertiary uppercase tracking-wide sticky left-0 bg-surface z-10">
                      Test Case
                    </th>
                    {runsToShow.map((run) => {
                      const col = colMap[run.run_id] || {}
                      const isBestPassRate = isBestCol(col)
                      const isCheapest = isCheapestCol(col)
                      return (
                        <th key={run.run_id} className="p-3 text-center min-w-[160px]">
                          <div className="text-xs font-semibold text-text-primary">{col.model}</div>
                          <div className="text-[10px] text-text-tertiary">{col.provider}</div>
                          <div
                            className={`text-xs font-bold mt-1 cursor-pointer hover:opacity-80 ${
                              col.pass_rate >= 90 ? 'text-success' :
                              col.pass_rate >= 70 ? 'text-warning' : 'text-error'
                            }`}
                            onClick={() => handleSortToggle('pass_rate')}
                            title="Sort by pass rate"
                          >
                            {isBestPassRate && <Trophy size={10} className="inline mr-0.5" />}
                            {col.pass_rate}%
                            {sortBy === 'pass_rate' && (
                              <span className="ml-0.5">{sortDir === 'desc' ? ' ↓' : ' ↑'}</span>
                            )}
                          </div>
                          <div className="flex items-center justify-center gap-2 mt-1 text-[10px] text-text-tertiary">
                            {col.total_cost > 0 && (
                              <span
                                className={`flex items-center gap-0.5 cursor-pointer hover:opacity-80 ${isCheapest ? 'text-success font-semibold' : ''}`}
                                onClick={() => handleSortToggle('total_cost')}
                                title="Sort by cost"
                              >
                                <DollarSign size={8} />{formatCost(col.total_cost)}
                                {sortBy === 'total_cost' && (
                                  <span>{sortDir === 'desc' ? '↓' : '↑'}</span>
                                )}
                              </span>
                            )}
                            {col.total_tokens > 0 && (
                              <span className="flex items-center gap-0.5">
                                <Hash size={8} />{formatTokens(col.total_tokens)}
                              </span>
                            )}
                          </div>
                        </th>
                      )
                    })}
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row, idx) => (
                    <tr key={row.question_id} className={idx % 2 === 0 ? '' : 'bg-surface-elevated/50'}>
                      <td className="p-3 text-text-primary font-medium text-xs sticky left-0 bg-inherit z-10 max-w-[200px] truncate">
                        {row.question_id}
                      </td>
                      {runsToShow.map(run => {
                        const cell = row.cells[run.run_id]
                        return (
                          <td key={run.run_id} className={`p-3 text-center ${getCellStyle(cell)}`}>
                            <div className="flex items-center justify-center gap-1">
                              {cell?.status === 'pass' && <CheckCircle size={14} />}
                              {cell?.status === 'fail' && <XCircle size={14} />}
                              {cell?.status === 'missing' && <Minus size={14} />}
                              {getChangeIcon(cell?.change)}
                            </div>
                            {cell?.score != null && (
                              <div className="text-[10px] font-mono mt-0.5 opacity-80">
                                {(cell.score * 100).toFixed(0)}%
                              </div>
                            )}
                            {cell?.duration_ms != null && (
                              <div className="text-[10px] text-text-tertiary mt-0.5 flex items-center justify-center gap-0.5">
                                <Clock size={8} /> {formatDuration(cell.duration_ms)}
                              </div>
                            )}
                            {cell?.cost_usd > 0 && (
                              <div className="text-[10px] text-text-tertiary mt-0.5 flex items-center justify-center gap-0.5">
                                <DollarSign size={8} /> {formatCost(cell.cost_usd)}
                              </div>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                  {visibleRows.length === 0 && (
                    <tr>
                      <td colSpan={runsToShow.length + 1} className="p-6 text-center text-text-tertiary text-xs">
                        No rows match the current filter.
                      </td>
                    </tr>
                  )}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 border-border bg-surface-elevated">
                    <td className="p-3 text-xs font-semibold text-text-primary sticky left-0 bg-surface-elevated z-10">
                      Summary
                    </td>
                    {runsToShow.map(run => {
                      const col = colMap[run.run_id] || {}
                      const isBest = isBestCol(col)
                      const isCheapest = isCheapestCol(col)
                      return (
                        <td key={run.run_id} className="p-3 text-center">
                          <div className={`text-xs font-bold ${isBest ? 'text-success' : 'text-text-secondary'}`}>
                            {isBest && <Trophy size={10} className="inline mr-0.5" />}
                            {col.passed}/{col.total} ({col.pass_rate}%)
                          </div>
                          {col.total_cost > 0 && (
                            <div className={`text-[10px] mt-0.5 ${isCheapest ? 'text-success font-semibold' : 'text-text-tertiary'}`}>
                              {isCheapest && '(cheapest) '}{formatCost(col.total_cost)}
                            </div>
                          )}
                          {col.total_tokens > 0 && (
                            <div className="text-[10px] text-text-tertiary mt-0.5">
                              {formatTokens(col.total_tokens)} tokens
                            </div>
                          )}
                          {col.total_duration_ms > 0 && (
                            <div className="text-[10px] text-text-tertiary mt-0.5">
                              {formatDuration(col.total_duration_ms)} total
                            </div>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                </tfoot>
              </table>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-4 text-xs text-text-tertiary flex-wrap">
              <span className="flex items-center gap-1"><CheckCircle size={12} className="text-success" /> Pass</span>
              <span className="flex items-center gap-1"><XCircle size={12} className="text-error" /> Fail</span>
              <span className="flex items-center gap-1"><Minus size={12} className="text-text-disabled" /> Missing</span>
              <span className="flex items-center gap-1"><ArrowDown size={12} className="text-error" /> Regression</span>
              <span className="flex items-center gap-1"><ArrowUp size={12} className="text-success" /> Improvement</span>
            </div>
          </>
          )
        })()}
      </div>
    </div>
  )
}

export default RunComparison
