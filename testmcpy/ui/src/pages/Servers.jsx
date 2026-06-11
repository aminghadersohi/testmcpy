import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  Heart,
  Server,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  Wrench,
  Wifi,
  WifiOff,
  X,
  Info,
  Grid3X3,
  Play,
  AlertCircle,
  Check,
  Minus,
} from 'lucide-react'
import MCPProfileSelector from '../components/MCPProfileSelector'

// ---------------------------------------------------------------------------
// Health tab (formerly pages/MCPHealth.jsx)
// ---------------------------------------------------------------------------

function formatMs(ms) {
  if (!ms && ms !== 0) return '-'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

function formatTime(isoStr) {
  if (!isoStr) return '-'
  return new Date(isoStr).toLocaleTimeString()
}

function formatElapsed(isoStr) {
  if (!isoStr) return null
  const diffSec = Math.round((Date.now() - new Date(isoStr).getTime()) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  return `${Math.floor(diffSec / 60)}m ago`
}

function isRecentSuccess(isoStr) {
  if (!isoStr) return false
  const diffSec = (Date.now() - new Date(isoStr).getTime()) / 1000
  return diffSec <= 300 // within 5 minutes
}

function getHealthStatusColor(status, lastSuccessAt) {
  if (status === 'error' && isRecentSuccess(lastSuccessAt)) return 'text-warning'
  switch (status) {
    case 'healthy': return 'text-success'
    case 'timeout': return 'text-warning'
    case 'unreachable':
    case 'error': return 'text-error'
    default: return 'text-text-tertiary'
  }
}

function getHealthStatusBg(status, lastSuccessAt) {
  if (status === 'error' && isRecentSuccess(lastSuccessAt)) return 'bg-warning/10 border-warning/30'
  switch (status) {
    case 'healthy': return 'bg-success/10 border-success/30'
    case 'timeout': return 'bg-warning/10 border-warning/30'
    case 'unreachable':
    case 'error': return 'bg-error/10 border-error/30'
    default: return 'bg-surface border-border'
  }
}

function getHealthStatusIcon(status, lastSuccessAt) {
  if (status === 'error' && isRecentSuccess(lastSuccessAt)) {
    return <AlertTriangle size={20} className="text-warning" />
  }
  switch (status) {
    case 'healthy': return <CheckCircle size={20} className="text-success" />
    case 'timeout': return <AlertTriangle size={20} className="text-warning" />
    case 'unreachable': return <WifiOff size={20} className="text-error" />
    case 'error': return <XCircle size={20} className="text-error" />
    default: return <Loader2 size={20} className="text-text-tertiary animate-spin" />
  }
}

const AUTO_REFRESH_INTERVAL = 30000

function HealthTab() {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [bannerDismissed, setBannerDismissed] = useState(false)
  const intervalRef = useRef(null)

  const checkHealth = useCallback(async (showSpinner = true) => {
    if (showSpinner) setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/health/mcp')
      if (!res.ok) throw new Error(`Failed: ${res.status}`)
      const data = await res.json()
      setHealth(data)
    } catch (err) {
      setError(err.message)
    } finally {
      if (showSpinner) setLoading(false)
    }
  }, [])

  useEffect(() => {
    checkHealth()
  }, [checkHealth])

  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => checkHealth(false), AUTO_REFRESH_INTERVAL)
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [autoRefresh, checkHealth])

  const servers = health?.servers || []

  return (
    <div className="h-full flex flex-col">
      {/* Controls bar */}
      <div className="flex-shrink-0 px-4 md:px-6 py-3 border-b border-border bg-surface-elevated">
        <div className="flex items-center justify-between flex-wrap gap-3">
          {health ? (
            <div className="flex items-center gap-4 text-sm">
              <span className="text-text-secondary">{health.total} server(s)</span>
              <span className="flex items-center gap-1 text-success">
                <Wifi size={14} /> {health.healthy} healthy
              </span>
              {health.unhealthy > 0 && (
                <span className="flex items-center gap-1 text-error">
                  <WifiOff size={14} /> {health.unhealthy} unhealthy
                </span>
              )}
            </div>
          ) : (
            <span className="text-sm text-text-tertiary">Monitor availability of configured MCP servers</span>
          )}
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 text-xs text-text-tertiary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-border"
              />
              Auto-refresh (30s)
            </label>
            <button
              onClick={() => checkHealth()}
              className="btn btn-ghost"
              disabled={loading}
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
              <span>Check Now</span>
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4 md:p-6">
        {/* Info banner */}
        {!bannerDismissed && (
          <div className="flex items-start gap-3 p-3 mb-4 bg-info/10 border border-info/30 rounded-lg text-sm text-text-secondary">
            <Info size={16} className="text-info flex-shrink-0 mt-0.5" />
            <span className="flex-1">
              Tip: First connections may take a moment due to auth setup. If servers appear failed just after configuration, try clicking Refresh.
            </span>
            <button
              onClick={() => setBannerDismissed(true)}
              className="text-text-tertiary hover:text-text-secondary flex-shrink-0"
              aria-label="Dismiss"
            >
              <X size={14} />
            </button>
          </div>
        )}

        {error && (
          <div className="p-4 bg-error/10 border border-error/30 rounded-lg text-error text-sm mb-4">
            {error}
          </div>
        )}

        {loading && !health ? (
          <div className="flex items-center justify-center h-full">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="animate-spin text-primary" size={32} />
              <span className="text-text-tertiary text-sm">Pinging MCP servers...</span>
            </div>
          </div>
        ) : servers.length === 0 ? (
          <div className="text-center py-16">
            <Server size={48} className="mx-auto mb-3 text-text-disabled opacity-50" />
            <p className="text-text-tertiary">No MCP servers configured</p>
            <p className="text-text-disabled text-sm mt-1">Add servers in MCP Profiles to monitor them</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {servers.map((server, idx) => (
              <div
                key={idx}
                className={`p-4 rounded-xl border transition-colors ${getHealthStatusBg(server.status, server.last_success_at)}`}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {getHealthStatusIcon(server.status, server.last_success_at)}
                    <div>
                      <div className="font-semibold text-text-primary text-sm">{server.server_name}</div>
                      <div className="text-xs text-text-tertiary">{server.profile_name}</div>
                    </div>
                  </div>
                  <span className={`text-xs font-semibold uppercase px-2 py-0.5 rounded ${getHealthStatusColor(server.status, server.last_success_at)} bg-surface/50`}>
                    {server.status}
                  </span>
                </div>

                <div className="space-y-2 text-xs">
                  <div className="flex items-center gap-2 text-text-secondary">
                    <Server size={12} className="text-text-tertiary flex-shrink-0" />
                    <span className="truncate">{server.server_url}</span>
                  </div>

                  {server.response_time_ms != null && (
                    <div className="flex items-center gap-2 text-text-secondary">
                      <Clock size={12} className="text-text-tertiary" />
                      Response: {formatMs(server.response_time_ms)}
                    </div>
                  )}

                  {server.tool_count != null && (
                    <div className="flex items-center gap-2 text-text-secondary">
                      <Wrench size={12} className="text-text-tertiary" />
                      {server.tool_count} tools available
                    </div>
                  )}

                  {server.error && (
                    <div className="p-2 bg-error/10 rounded text-error text-xs mt-2 break-words">
                      {server.error}
                      {server.error_class && (
                        <div className="text-text-tertiary mt-1">Error type: {server.error_class}</div>
                      )}
                    </div>
                  )}

                  {server.status !== 'healthy' && server.last_success_at && (
                    <div className="text-text-tertiary text-[10px]">
                      Last healthy: {formatElapsed(server.last_success_at)}
                    </div>
                  )}

                  <div className="text-text-disabled text-[10px] mt-1">
                    Checked: {formatTime(server.checked_at)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Schema Compat tab (formerly pages/CompatibilityMatrix.jsx)
// ---------------------------------------------------------------------------

function SchemaCompatTab() {
  const [selectedProfiles, setSelectedProfiles] = useState([])
  const [toolNames, setToolNames] = useState('')
  const [autoDiscover, setAutoDiscover] = useState(true)
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Auto-discover tools from the first selected profile
  const discoverTools = async () => {
    if (selectedProfiles.length === 0) return

    try {
      const params = new URLSearchParams()
      params.append('profiles', selectedProfiles[0])
      const res = await fetch(`/api/mcp/tools?${params.toString()}`)
      if (res.ok) {
        const tools = await res.json()
        const names = tools.map(t => t.name).join('\n')
        setToolNames(names)
      }
    } catch (err) {
      console.error('Failed to discover tools:', err)
    }
  }

  useEffect(() => {
    if (autoDiscover && selectedProfiles.length > 0) {
      discoverTools()
    }
  }, [selectedProfiles, autoDiscover])

  const runMatrix = async () => {
    const names = toolNames.split('\n').map(s => s.trim()).filter(s => s)
    if (selectedProfiles.length < 2) {
      setError('Select at least 2 MCP profiles')
      return
    }
    if (names.length === 0) {
      setError('Enter at least 1 tool name')
      return
    }

    setLoading(true)
    setError(null)
    setResults(null)

    try {
      const res = await fetch('/api/compatibility/matrix', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profiles: selectedProfiles,
          tool_names: names,
        }),
      })

      if (!res.ok) {
        const data = await res.json()
        throw new Error(data.detail || 'Matrix test failed')
      }

      const data = await res.json()
      setResults(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'pass':
        return <Check size={16} className="text-success" />
      case 'fail':
        return <X size={16} className="text-error" />
      case 'missing':
        return <Minus size={16} className="text-text-tertiary" />
      case 'error':
        return <AlertCircle size={16} className="text-warning" />
      default:
        return <Minus size={16} className="text-text-disabled" />
    }
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'pass': return 'bg-success/10 border-success/30'
      case 'fail': return 'bg-error/10 border-error/30'
      case 'missing': return 'bg-surface border-border'
      case 'error': return 'bg-warning/10 border-warning/30'
      default: return 'bg-surface border-border'
    }
  }

  return (
    <div className="h-full overflow-auto p-4 bg-background-subtle">
      <div className="max-w-6xl mx-auto">
        {/* Configuration */}
        <div className="bg-surface-elevated border border-border rounded-lg p-6 mb-6">
          <h3 className="font-bold text-lg mb-4">Configuration</h3>

          <div className="mb-4">
            <label className="block text-sm font-medium mb-1">
              MCP Profiles (select 2 or more)
            </label>
            <MCPProfileSelector
              selectedProfiles={selectedProfiles}
              onChange={setSelectedProfiles}
              multiple={true}
            />
            {selectedProfiles.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {selectedProfiles.map((p, idx) => (
                  <span key={idx} className="px-2 py-0.5 text-xs bg-primary/10 text-primary rounded border border-primary/20">
                    {p.split(':')[1] || p}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="mb-4">
            <div className="flex items-center justify-between mb-1">
              <label className="block text-sm font-medium">Tool Names (one per line)</label>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs text-text-secondary">
                  <input
                    type="checkbox"
                    checked={autoDiscover}
                    onChange={(e) => setAutoDiscover(e.target.checked)}
                    className="w-3.5 h-3.5"
                  />
                  Auto-discover from first profile
                </label>
                {selectedProfiles.length > 0 && (
                  <button
                    onClick={discoverTools}
                    className="text-xs text-primary hover:underline flex items-center gap-1"
                  >
                    <RefreshCw size={12} />
                    Refresh
                  </button>
                )}
              </div>
            </div>
            <textarea
              value={toolNames}
              onChange={(e) => setToolNames(e.target.value)}
              className="input w-full font-mono text-sm"
              rows={6}
              placeholder="list_charts&#10;get_chart_info&#10;execute_sql"
            />
            <p className="text-text-tertiary text-xs mt-1">
              {toolNames.split('\n').filter(s => s.trim()).length} tool(s) configured
            </p>
          </div>

          {error && (
            <div className="bg-error/10 border border-error/30 rounded p-3 mb-4 flex items-center gap-2">
              <AlertCircle size={16} className="text-error flex-shrink-0" />
              <span className="text-sm text-error">{error}</span>
            </div>
          )}

          <button
            onClick={runMatrix}
            disabled={loading || selectedProfiles.length < 2}
            className="btn btn-primary flex items-center gap-2"
          >
            {loading ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Running Matrix...
              </>
            ) : (
              <>
                <Play size={16} />
                Run Compatibility Matrix
              </>
            )}
          </button>
        </div>

        {/* Results */}
        {results && (
          <div className="bg-surface-elevated border border-border rounded-lg p-6">
            <h3 className="font-bold text-lg mb-4">Results</h3>

            {/* Matrix Grid */}
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="text-left text-sm font-medium p-2 border-b border-border min-w-[200px]">
                      Tool
                    </th>
                    {results.profiles.map((profile) => (
                      <th key={profile} className="text-center text-xs font-medium p-2 border-b border-border min-w-[120px]">
                        <div className="truncate" title={profile}>
                          {profile.split(':')[1] || profile}
                        </div>
                        <div className="text-text-tertiary font-normal truncate">
                          {profile.split(':')[0]}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {results.tool_names.map((toolName) => (
                    <tr key={toolName} className="hover:bg-surface-hover">
                      <td className="text-sm font-mono p-2 border-b border-border">
                        {toolName}
                      </td>
                      {results.profiles.map((profile) => {
                        const cell = results.matrix[toolName]?.[profile] || { status: 'unknown' }
                        return (
                          <td key={profile} className="p-2 border-b border-border text-center">
                            <div
                              className={`inline-flex items-center justify-center gap-1.5 px-2 py-1 rounded border ${getStatusColor(cell.status)}`}
                              title={cell.error || cell.status}
                            >
                              {getStatusIcon(cell.status)}
                              <span className="text-xs capitalize">{cell.status}</span>
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Legend */}
            <div className="mt-4 pt-4 border-t border-border flex flex-wrap gap-4 text-xs text-text-secondary">
              <div className="flex items-center gap-1.5">
                <Check size={14} className="text-success" />
                <span>Pass - tool exists and schema matches</span>
              </div>
              <div className="flex items-center gap-1.5">
                <X size={14} className="text-error" />
                <span>Fail - schema mismatch</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Minus size={14} className="text-text-tertiary" />
                <span>Missing - tool not found</span>
              </div>
              <div className="flex items-center gap-1.5">
                <AlertCircle size={14} className="text-warning" />
                <span>Error - connection issue</span>
              </div>
            </div>

            <div className="mt-3 text-xs text-text-tertiary">
              Reference profile: <span className="font-medium">{results.reference_profile}</span> (schemas compared against this)
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Servers page — Health + Schema Compat tabs
// ---------------------------------------------------------------------------

function Servers() {
  const [activeTab, setActiveTab] = useState('health')

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-6 py-4 border-b border-border bg-surface-elevated">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Server size={24} className="text-primary" />
          </div>
          <div>
            <h1 className="text-xl md:text-2xl font-semibold text-text-primary">Servers</h1>
            <p className="text-sm text-text-tertiary">MCP server health and cross-server schema compatibility</p>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-2 mt-4">
          <button
            onClick={() => setActiveTab('health')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
              activeTab === 'health'
                ? 'bg-primary text-white'
                : 'bg-surface hover:bg-surface-hover text-text-secondary'
            }`}
          >
            <Heart size={16} />
            Health
          </button>
          <button
            onClick={() => setActiveTab('compat')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
              activeTab === 'compat'
                ? 'bg-primary text-white'
                : 'bg-surface hover:bg-surface-hover text-text-secondary'
            }`}
          >
            <Grid3X3 size={16} />
            Schema Compat
          </button>
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === 'health' ? <HealthTab /> : <SchemaCompatTab />}
      </div>
    </div>
  )
}

export default Servers
