import React, { useState } from 'react'
import { Download, CheckCircle2, XCircle, Clock, Zap, TrendingUp, TrendingDown, Minus, AlertCircle } from 'lucide-react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

const median = (arr) => {
  const s = [...arr].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

const ToolComparison = ({ comparisonResults }) => {
  const [showRawOutputs, setShowRawOutputs] = useState(true)
  // Track expanded state per iteration index per profile
  const [expandedOutputs, setExpandedOutputs] = useState({})

  if (!comparisonResults) {
    return null
  }

  const { profile1, profile2, tool_name, results1, results2, metrics } = comparisonResults

  // Helper to format time
  const formatTime = (ms) => {
    if (ms < 1000) return `${ms.toFixed(0)}ms`
    return `${(ms / 1000).toFixed(2)}s`
  }

  // Helper to determine which is faster
  const getFasterIndicator = (time1, time2) => {
    const diff = Math.abs(time1 - time2)
    const percentDiff = (diff / Math.max(time1, time2)) * 100

    if (percentDiff < 5) {
      return { icon: Minus, text: 'Similar', color: 'text-text-secondary' }
    }

    if (time1 < time2) {
      return { icon: TrendingUp, text: `${percentDiff.toFixed(1)}% faster`, color: 'text-success' }
    }

    return { icon: TrendingDown, text: `${percentDiff.toFixed(1)}% slower`, color: 'text-danger' }
  }

  // Helper to format JSON for display
  const formatJSON = (obj) => {
    try {
      return JSON.stringify(obj, null, 2)
    } catch (e) {
      return String(obj)
    }
  }

  // Calculate average metrics
  const avgTime1 = results1.reduce((sum, r) => sum + (r.duration_ms || 0), 0) / results1.length
  const avgTime2 = results2.reduce((sum, r) => sum + (r.duration_ms || 0), 0) / results2.length
  const successRate1 = (results1.filter(r => r.success).length / results1.length) * 100
  const successRate2 = (results2.filter(r => r.success).length / results2.length) * 100

  // Median latencies
  const durations1 = results1.map(r => r.duration_ms || 0)
  const durations2 = results2.map(r => r.duration_ms || 0)
  const medianTime1 = durations1.length > 0 ? median(durations1) : 0
  const medianTime2 = durations2.length > 0 ? median(durations2) : 0

  // Per-iteration latency chart data
  const latencyChartData = results1.map((r1, idx) => ({
    iteration: `#${idx + 1}`,
    [profile1]: r1.duration_ms || 0,
    [profile2]: (results2[idx] && results2[idx].duration_ms) || 0,
  }))

  const downloadResults = () => {
    const dataStr = JSON.stringify(comparisonResults, null, 2)
    const blob = new Blob([dataStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `comparison-${tool_name}-${Date.now()}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  const toggleOutputExpand = (key) => {
    setExpandedOutputs(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const renderOutput = (result, expandKey) => {
    if (!result.success) {
      return (
        <div className="bg-danger/10 border border-danger/30 rounded p-3">
          <p className="text-sm text-danger">{result.error || 'Unknown error'}</p>
        </div>
      )
    }
    const text = formatJSON(result.result)
    const isLong = text.length > 500
    const isExpanded = expandedOutputs[expandKey]
    return (
      <div className="bg-surface rounded border border-border p-3">
        <pre className={`text-xs text-text-primary overflow-auto font-mono whitespace-pre-wrap break-words ${isExpanded ? '' : 'max-h-48'}`}>
          {text}
        </pre>
        {isLong && (
          <button
            onClick={() => toggleOutputExpand(expandKey)}
            className="mt-2 text-xs text-primary hover:underline"
          >
            {isExpanded ? 'Collapse' : 'Expand'}
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl md:text-2xl font-bold text-text-primary">{tool_name}</h2>
          <p className="text-sm text-text-secondary mt-1">
            Comparison Results - {results1.length} iteration{results1.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button
          onClick={downloadResults}
          className="btn btn-secondary text-sm"
        >
          <Download size={16} />
          <span>Download JSON</span>
        </button>
      </div>

      {/* Metrics Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6">
        {/* Profile 1 Metrics */}
        <div className="bg-surface-elevated border border-border rounded-lg p-4 md:p-6">
          <h3 className="font-semibold text-text-primary mb-4 flex items-center gap-2">
            <div className="w-3 h-3 bg-primary rounded-full"></div>
            {profile1}
          </h3>
          <div className="space-y-4">
            <div>
              <div className="text-xs text-text-tertiary mb-1">Average Response Time</div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-bold text-text-primary">{formatTime(avgTime1)}</span>
                {results1.length > 1 && (
                  <span className="text-xs text-text-tertiary">
                    ({formatTime(Math.min(...results1.map(r => r.duration_ms || 0)))} - {formatTime(Math.max(...results1.map(r => r.duration_ms || 0)))})
                  </span>
                )}
              </div>
              <div className="text-xs text-text-tertiary mt-1">Median: {formatTime(medianTime1)}</div>
            </div>
            <div>
              <div className="text-xs text-text-tertiary mb-1">Success Rate</div>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-bold text-text-primary">{successRate1.toFixed(0)}%</span>
                {successRate1 === 100 ? (
                  <CheckCircle2 size={20} className="text-success" />
                ) : successRate1 > 0 ? (
                  <AlertCircle size={20} className="text-warning" />
                ) : (
                  <XCircle size={20} className="text-danger" />
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Profile 2 Metrics */}
        <div className="bg-surface-elevated border border-border rounded-lg p-4 md:p-6">
          <h3 className="font-semibold text-text-primary mb-4 flex items-center gap-2">
            <div className="w-3 h-3 bg-accent rounded-full"></div>
            {profile2}
          </h3>
          <div className="space-y-4">
            <div>
              <div className="text-xs text-text-tertiary mb-1">Average Response Time</div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-bold text-text-primary">{formatTime(avgTime2)}</span>
                {results2.length > 1 && (
                  <span className="text-xs text-text-tertiary">
                    ({formatTime(Math.min(...results2.map(r => r.duration_ms || 0)))} - {formatTime(Math.max(...results2.map(r => r.duration_ms || 0)))})
                  </span>
                )}
              </div>
              <div className="text-xs text-text-tertiary mt-1">Median: {formatTime(medianTime2)}</div>
              {(() => {
                const indicator = getFasterIndicator(avgTime2, avgTime1)
                return (
                  <div className={`flex items-center gap-1 mt-1 text-sm ${indicator.color}`}>
                    <indicator.icon size={14} />
                    <span>{indicator.text}</span>
                  </div>
                )
              })()}
            </div>
            <div>
              <div className="text-xs text-text-tertiary mb-1">Success Rate</div>
              <div className="flex items-center gap-2">
                <span className="text-2xl font-bold text-text-primary">{successRate2.toFixed(0)}%</span>
                {successRate2 === 100 ? (
                  <CheckCircle2 size={20} className="text-success" />
                ) : successRate2 > 0 ? (
                  <AlertCircle size={20} className="text-warning" />
                ) : (
                  <XCircle size={20} className="text-danger" />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Per-iteration latency chart */}
      {latencyChartData.length > 0 && (
        <div className="bg-surface-elevated border border-border rounded-lg p-4">
          <h3 className="font-semibold text-text-primary mb-3 text-sm">Per-Iteration Latency</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={latencyChartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis dataKey="iteration" tick={{ fontSize: 11, fill: 'currentColor' }} />
              <YAxis tick={{ fontSize: 11, fill: 'currentColor' }} unit="ms" />
              <Tooltip formatter={(value) => [`${value.toFixed(0)}ms`, '']} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey={profile1} fill="#6366f1" radius={[3, 3, 0, 0]} />
              <Bar dataKey={profile2} fill="#f59e0b" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Toggle for raw outputs */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowRawOutputs(!showRawOutputs)}
          className={`btn text-sm ${showRawOutputs ? 'btn-primary' : 'btn-secondary'}`}
        >
          {showRawOutputs ? 'Hide' : 'Show'} Individual Responses
        </button>
      </div>

      {/* Side-by-Side Responses */}
      {showRawOutputs && (
        <div className="space-y-4">
          {results1.map((result1, idx) => {
            const result2 = results2[idx]
            const indicator = result1.duration_ms && result2.duration_ms
              ? getFasterIndicator(result2.duration_ms, result1.duration_ms)
              : null

            return (
              <div key={idx} className="border border-border rounded-lg overflow-hidden">
                {/* Iteration Header */}
                <div className="bg-surface-elevated border-b border-border px-4 py-3">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold text-text-primary">
                      Iteration {idx + 1}
                    </h4>
                    {indicator && (
                      <div className={`flex items-center gap-1 text-sm ${indicator.color}`}>
                        <indicator.icon size={14} />
                        <span>{profile2} {indicator.text}</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Side-by-Side Content */}
                <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-border">
                  {/* Profile 1 Result */}
                  <div className="p-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 bg-primary rounded-full"></div>
                        <span className="text-sm font-medium text-text-secondary">{profile1}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-text-tertiary">
                        {result1.success ? (
                          <div className="flex items-center gap-1 text-success">
                            <CheckCircle2 size={14} />
                            <span>Success</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 text-danger">
                            <XCircle size={14} />
                            <span>Failed</span>
                          </div>
                        )}
                        {result1.duration_ms && (
                          <div className="flex items-center gap-1">
                            <Clock size={14} />
                            <span>{formatTime(result1.duration_ms)}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    {renderOutput(result1, `p1-${idx}`)}
                  </div>

                  {/* Profile 2 Result */}
                  <div className="p-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 bg-accent rounded-full"></div>
                        <span className="text-sm font-medium text-text-secondary">{profile2}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-text-tertiary">
                        {result2.success ? (
                          <div className="flex items-center gap-1 text-success">
                            <CheckCircle2 size={14} />
                            <span>Success</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 text-danger">
                            <XCircle size={14} />
                            <span>Failed</span>
                          </div>
                        )}
                        {result2.duration_ms && (
                          <div className="flex items-center gap-1">
                            <Clock size={14} />
                            <span>{formatTime(result2.duration_ms)}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    {renderOutput(result2, `p2-${idx}`)}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default ToolComparison
