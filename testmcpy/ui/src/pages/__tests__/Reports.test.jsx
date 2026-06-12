import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Reports from '../Reports'
import { NotificationProvider } from '../../components/NotificationProvider'

vi.mock('react-markdown', () => ({ default: ({ children }) => children }))
vi.mock('remark-gfm', () => ({ default: () => null }))
vi.mock('../../components/TraceView', () => ({ default: () => null }))

const runs = [
  {
    run_id: 'run_001',
    test_file: 'tests/file_one.yaml',
    passed: 2,
    failed: 0,
    total_tests: 2,
    model: 'claude-sonnet-4-5',
    provider: 'anthropic',
    timestamp: '2026-06-10T19:42:18Z',
    total_cost: 0.01,
    total_tokens: 1000,
    total_duration: 12.5,
  },
  {
    run_id: 'run_002',
    test_file: 'tests/file_two.yaml',
    passed: 1,
    failed: 1,
    total_tests: 2,
    model: 'claude-sonnet-4-5',
    provider: 'anthropic',
    timestamp: '2026-06-10T19:40:00Z',
    total_cost: 0.02,
    total_tokens: 2000,
    total_duration: 20.0,
  },
]

const runDetails = {
  metadata: {
    test_file: 'tests/file_two.yaml',
    model: 'claude-sonnet-4-5',
    provider: 'anthropic',
    passed: 1,
    failed: 1,
    total_tests: 2,
    timestamp: '2026-06-10T19:40:00Z',
  },
  results: [],
}

function mockFetch() {
  global.fetch = vi.fn((url) => {
    const u = String(url)
    let body = {}
    if (u.includes('/api/results/list')) body = { runs, total: runs.length }
    else if (u.includes('/api/smoke-reports/list')) body = { reports: [] }
    else if (u.includes('/api/results/filters')) body = { models: [], providers: [], test_files: [] }
    else if (u.includes('/api/results/run/')) body = runDetails
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
  })
}

function renderReports(initialEntry) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <NotificationProvider>
        <Routes>
          <Route path="/reports" element={<Reports />} />
        </Routes>
      </NotificationProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  mockFetch()
})

describe('Reports deep link', () => {
  it('scrolls the deep-linked run list item into view', async () => {
    const scrolled = []
    window.HTMLElement.prototype.scrollIntoView = vi.fn(function () {
      scrolled.push(this)
    })

    renderReports('/reports?run=run_002&type=tests')

    await waitFor(() => expect(scrolled.length).toBe(1))
    expect(scrolled[0].textContent).toContain('tests/file_two.yaml')
  })

  it('does not scroll when there is no run param', async () => {
    const scrollSpy = vi.fn()
    window.HTMLElement.prototype.scrollIntoView = scrollSpy

    renderReports('/reports')

    await screen.findByText('tests/file_one.yaml')
    expect(scrollSpy).not.toHaveBeenCalled()
  })
})
