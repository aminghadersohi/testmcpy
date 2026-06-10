// Shared display formatters for dates, durations, costs and token counts.
// Import these instead of redefining per page so values render identically
// across Reports, Test Manager, Metrics, Compare, etc.

export function formatDate(timestamp) {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleString()
}

export function formatDuration(seconds) {
  if (!seconds) return '0s'
  if (seconds < 0.1) return `${(seconds * 1000).toFixed(0)}ms`
  return `${seconds.toFixed(1)}s`
}

export function formatDurationMs(ms) {
  if (!ms) return '-'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.round(ms)}ms`
}

export function formatCost(cost) {
  if (!cost) return '$0.00'
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  return `$${cost.toFixed(2)}`
}

export function formatTokens(tokens) {
  if (!tokens) return '0'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(0)}K`
  return tokens.toString()
}
