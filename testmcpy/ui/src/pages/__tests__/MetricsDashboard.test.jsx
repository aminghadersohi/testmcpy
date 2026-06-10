import { render } from '@testing-library/react'
import { describe, it, vi, beforeEach } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import MetricsDashboard from '../MetricsDashboard'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }) => children,
  LineChart: () => null,
  BarChart: () => null,
  Bar: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  PieChart: () => null,
  Pie: () => null,
  Cell: () => null,
}))

const mockMetrics = {
  summary: {
    total_runs: 5,
    total_questions: 50,
    pass_rate: 90.0,
    total_cost: 1.23,
    avg_cost_per_run: 0.246,
    total_tokens: 5000,
    avg_latency_ms: 800,
    false_positive_count: 2,
    false_positive_rate: 4.0,
  },
  time_series: [],
  model_breakdown: [],
}

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(mockMetrics) })
  )
})

describe('MetricsDashboard', () => {
  it('renders without crashing', () => {
    render(<BrowserRouter><MetricsDashboard /></BrowserRouter>)
  })
})
