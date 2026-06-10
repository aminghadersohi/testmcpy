import React, { useState, useEffect, useCallback } from 'react'
import { formatCost } from '../utils/formatters'
import {
  BarChart3,
  TrendingUp,
  DollarSign,
  Clock,
  Hash,
  CheckCircle,
  XCircle,
  RefreshCw,
  Loader2,
  Filter,
  Calendar,
  Cpu,
  AlertTriangle,
} from 'lucide-react'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

function formatNumber(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return n.toString()
}

function formatMs(ms) {
  if (!ms) return '0ms'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function MetricsDashboard() {
  const [metrics, setMetrics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [granularity, setGranularity] = useState('daily')
  const [dateRange, setDateRange] = useState(30) // days
  const [providerFilter, setProviderFilter] = useState('')
  const [modelFilter, setModelFilter] = useState('')

  const isHourlyDisabled = dateRange > 3

  const handleDateRangeChange = (newRange) => {
    setDateRange(Number(newRange))
    if (Number(newRange) > 3 && granularity === 'hourly') {
      setGranularity('daily')
    }
  }

  const loadMetrics = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      const now = new Date()
      const from = new Date(now.getTime() - dateRange * 24 * 60 * 60 * 1000)
      params.set('date_from', from.toISOString())
      params.set('date_to', now.toISOString())
      params.set('granularity', granularity)
      if (providerFilter) params.set('llm_provider', providerFilter)
      if (modelFilter) params.set('model', modelFilter)

      const res = await fetch(`/api/metrics?${params}`)
      if (!res.ok) throw new Error(`Failed to load metrics: ${res.status}`)
      const data = await res.json()
      setMetrics(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [dateRange, granularity, providerFilter, modelFilter])

  useEffect(() => {
    loadMetrics()
  }, [loadMetrics])

  if (loading && !metrics) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="animate-spin text-primary" size={32} />
      </div>
    )
  }

  const summary = metrics?.summary || {}
  const timeSeries = metrics?.time_series || []
  const modelBreakdown = metrics?.model_breakdown || []

  const fpRate = summary.false_positive_rate || 0
  const fpCount = summary.false_positive_count || 0
  const fpIsZero = fpRate === 0 && fpCount === 0

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-6 py-4 border-b border-border bg-surface-elevated">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10">
              <BarChart3 size={24} className="text-primary" />
            </div>
            <div>
              <h1 className="text-xl md:text-2xl font-semibold text-text-primary">Metrics Dashboard</h1>
              <p className="text-sm text-text-tertiary">Aggregate performance metrics over time</p>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Date range */}
            <div className="flex items-center gap-1 bg-surface border border-border rounded-lg px-2 py-1.5">
              <Calendar size={14} className="text-text-tertiary" />
              <select
                value={dateRange}
                onChange={(e) => handleDateRangeChange(e.target.value)}
                className="bg-transparent text-sm text-text-primary outline-none cursor-pointer"
              >
                <option value={1}>1 day</option>
                <option value={2}>2 days</option>
                <option value={3}>3 days</option>
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
                <option value={60}>60 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>

            {/* Granularity */}
            <div className="flex items-center gap-1 bg-surface border border-border rounded-lg px-2 py-1.5">
              <Filter size={14} className="text-text-tertiary" />
              <select
                value={granularity}
                onChange={(e) => setGranularity(e.target.value)}
                className="bg-transparent text-sm text-text-primary outline-none cursor-pointer"
              >
                <option
                  value="hourly"
                  disabled={isHourlyDisabled}
                  title={isHourlyDisabled ? 'Only available for date ranges of 3 days or less' : ''}
                >
                  Hourly{isHourlyDisabled ? ' (unavailable)' : ''}
                </option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
              </select>
            </div>

            {/* Provider filter */}
            <input
              type="text"
              placeholder="Provider..."
              value={providerFilter}
              onChange={(e) => setProviderFilter(e.target.value)}
              className="bg-surface border border-border rounded-lg px-2 py-1.5 text-sm text-text-primary w-24 placeholder:text-text-disabled outline-none focus:border-primary"
            />

            {/* Model filter */}
            <input
              type="text"
              placeholder="Model..."
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
              className="bg-surface border border-border rounded-lg px-2 py-1.5 text-sm text-text-primary w-24 placeholder:text-text-disabled outline-none focus:border-primary"
            />

            <button
              onClick={loadMetrics}
              className="btn btn-ghost"
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 md:p-6 space-y-6">
        {error && (
          <div className="p-4 bg-error/10 border border-error/30 rounded-lg text-error text-sm">
            {error}
          </div>
        )}

        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="p-4 rounded-xl bg-surface border border-border">
            <div className="flex items-center gap-2 text-text-tertiary text-xs font-medium uppercase tracking-wide mb-2">
              <TrendingUp size={14} />
              Total Runs
            </div>
            <div className="text-2xl font-bold text-text-primary">{summary.total_runs || 0}</div>
            <div className="text-xs text-text-tertiary mt-1">{summary.total_questions || 0} questions</div>
          </div>

          <div className="p-4 rounded-xl bg-surface border border-border">
            <div className="flex items-center gap-2 text-text-tertiary text-xs font-medium uppercase tracking-wide mb-2">
              <CheckCircle size={14} className="text-success" />
              Pass Rate
            </div>
            <div className={`text-2xl font-bold ${
              summary.pass_rate >= 90 ? 'text-success' :
              summary.pass_rate >= 70 ? 'text-warning' : 'text-error'
            }`}>
              {summary.pass_rate || 0}%
            </div>
            <div className="text-xs text-text-tertiary mt-1">
              {summary.total_passed || 0} passed / {summary.total_failed || 0} failed
            </div>
          </div>

          <div className="p-4 rounded-xl bg-surface border border-border">
            <div className="flex items-center gap-2 text-text-tertiary text-xs font-medium uppercase tracking-wide mb-2">
              <DollarSign size={14} />
              Total Cost
            </div>
            <div className="text-2xl font-bold text-text-primary">{formatCost(summary.total_cost)}</div>
            <div className="text-xs text-text-tertiary mt-1">Avg {formatCost(summary.avg_cost_per_run)} per run</div>
          </div>

          <div className="p-4 rounded-xl bg-surface border border-border">
            <div className="flex items-center gap-2 text-text-tertiary text-xs font-medium uppercase tracking-wide mb-2">
              <Clock size={14} />
              Avg Latency
            </div>
            <div className="text-2xl font-bold text-text-primary">{formatMs(summary.avg_latency_ms)}</div>
            <div className="text-xs text-text-tertiary mt-1">{formatNumber(summary.total_tokens || 0)} tokens total</div>
          </div>

          {/* False Positive Rate card */}
          <div className={`p-4 rounded-xl border ${fpIsZero ? 'bg-surface border-border' : 'bg-amber-50 border-amber-200'}`}>
            <div className={`flex items-center gap-2 text-xs font-medium uppercase tracking-wide mb-2 ${fpIsZero ? 'text-text-tertiary' : 'text-amber-700'}`}>
              <AlertTriangle size={14} />
              False Positives
            </div>
            <div className={`text-2xl font-bold ${fpIsZero ? 'text-text-tertiary' : 'text-amber-700'}`}>
              {fpIsZero ? '—' : `${fpRate}%`}
            </div>
            <div className={`text-xs mt-1 ${fpIsZero ? 'text-text-disabled' : 'text-amber-700'}`}>
              {fpIsZero ? 'None flagged' : `${fpCount} flagged`}
            </div>
          </div>
        </div>

        {/* Charts */}
        {timeSeries.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="p-4 rounded-xl bg-surface border border-border">
              <h3 className="text-sm font-semibold text-text-primary mb-3">Pass Rate Over Time (%)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={timeSeries}>
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <CartesianGrid strokeDasharray="3 3" />
                  <Tooltip />
                  <Line type="monotone" dataKey="pass_rate" stroke="#4ade80" name="Pass Rate %" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="p-4 rounded-xl bg-surface border border-border">
              <h3 className="text-sm font-semibold text-text-primary mb-3">Cost Over Time ($)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={timeSeries}>
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <CartesianGrid strokeDasharray="3 3" />
                  <Tooltip />
                  <Bar dataKey="cost" fill="#60a5fa" name="Cost ($)" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="p-4 rounded-xl bg-surface border border-border">
              <h3 className="text-sm font-semibold text-text-primary mb-3">Avg Latency Over Time (ms)</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={timeSeries}>
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <CartesianGrid strokeDasharray="3 3" />
                  <Tooltip />
                  <Bar dataKey="avg_latency_ms" fill="#f59e0b" name="Latency (ms)" />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="p-4 rounded-xl bg-surface border border-border">
              <h3 className="text-sm font-semibold text-text-primary mb-3">Questions Over Time</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={timeSeries}>
                  <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <CartesianGrid strokeDasharray="3 3" />
                  <Tooltip />
                  <Bar dataKey="questions" fill="#a78bfa" name="Questions" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {timeSeries.length === 0 && !loading && (
          <div className="text-center py-12">
            <BarChart3 size={48} className="mx-auto mb-3 text-text-disabled opacity-50" />
            <p className="text-text-tertiary">No data for the selected period</p>
            <p className="text-text-disabled text-sm mt-1">Run some tests to see metrics here</p>
          </div>
        )}

        {/* Model Breakdown */}
        {modelBreakdown.length > 0 && (
          <div className="p-4 rounded-xl bg-surface border border-border">
            <h3 className="text-sm font-semibold text-text-primary mb-3">Model Breakdown</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-text-tertiary uppercase tracking-wide border-b border-border">
                    <th className="pb-2 pr-4">Model</th>
                    <th className="pb-2 pr-4">Provider</th>
                    <th className="pb-2 pr-4">Runs</th>
                    <th className="pb-2 pr-4">Pass Rate</th>
                    <th className="pb-2 pr-4">Avg Latency</th>
                    <th className="pb-2 pr-4">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {modelBreakdown.map((m, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td className="py-2 pr-4 font-medium text-text-primary flex items-center gap-2">
                        <Cpu size={14} className="text-text-tertiary" />
                        {m.model}
                      </td>
                      <td className="py-2 pr-4 text-text-secondary">{m.provider}</td>
                      <td className="py-2 pr-4 text-text-secondary">{m.runs}</td>
                      <td className="py-2 pr-4">
                        <span className={`font-medium ${
                          m.pass_rate >= 90 ? 'text-success' :
                          m.pass_rate >= 70 ? 'text-warning' : 'text-error'
                        }`}>
                          {m.pass_rate}%
                        </span>
                      </td>
                      <td className="py-2 pr-4 text-text-secondary font-mono">{formatMs(m.avg_latency_ms)}</td>
                      <td className="py-2 pr-4 text-text-secondary font-mono">{formatCost(m.cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default MetricsDashboard
