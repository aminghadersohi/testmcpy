import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import ChatInterface from '../ChatInterface'
import { NotificationProvider } from '../../components/NotificationProvider'

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
    render(<BrowserRouter><NotificationProvider><ChatInterface /></NotificationProvider></BrowserRouter>)
  })

  it('shows input textarea', () => {
    render(<BrowserRouter><NotificationProvider><ChatInterface /></NotificationProvider></BrowserRouter>)
    const textarea = document.querySelector('textarea')
    expect(textarea).toBeTruthy()
  })

  it('send path does not throw (regression: collapsedThinking was never declared)', async () => {
    // The original crash was a ReferenceError on setCollapsedThinking inside sendMessage.
    // This test exercises the send path to ensure it no longer throws.
    const mockStream = {
      getReader: () => ({
        read: vi.fn()
          .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"type":"content","content":"hi"}\n\n') })
          .mockResolvedValueOnce({ done: true, value: undefined }),
      }),
    }
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, body: mockStream })
    )

    render(<BrowserRouter><NotificationProvider><ChatInterface /></NotificationProvider></BrowserRouter>)

    const textarea = document.querySelector('textarea')
    fireEvent.change(textarea, { target: { value: 'hello' } })

    // Find and click the send button — it may be a button with type submit or aria-label Send
    const sendBtn = document.querySelector('button[type="submit"]') ||
      Array.from(document.querySelectorAll('button')).find(b => /send/i.test(b.textContent + b.getAttribute('aria-label')))

    if (sendBtn) {
      await act(async () => { fireEvent.click(sendBtn) })
    } else {
      // Fallback: submit via Enter key on the form
      await act(async () => { fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true }) })
    }
    // If we reach here without a ReferenceError, the fix is working
  })
})
