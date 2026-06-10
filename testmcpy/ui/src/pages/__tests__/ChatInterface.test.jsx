import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import ChatInterface from '../ChatInterface'

vi.mock('@microlink/react-json-view', () => ({ default: () => null }))
vi.mock('react-markdown', () => ({ default: ({ children }) => children }))
vi.mock('remark-gfm', () => ({ default: () => null }))
vi.mock('../../hooks/useKeyboardShortcuts', () => ({
  useKeyboardShortcuts: () => {},
  useAnnounce: () => () => {},
}))
vi.mock('../../hooks/useEditorTheme', () => ({
  useEditorTheme: () => ({ jsonTheme: 'rjv-default' }),
}))
vi.mock('../../components/ToolCallTimeline', () => ({ default: () => null }))

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
    })
  )
})

describe('ChatInterface', () => {
  it('renders without crashing', () => {
    render(<BrowserRouter><ChatInterface /></BrowserRouter>)
  })

  it('shows input textarea', () => {
    render(<BrowserRouter><ChatInterface /></BrowserRouter>)
    const textarea = document.querySelector('textarea')
    expect(textarea).toBeTruthy()
  })
})
