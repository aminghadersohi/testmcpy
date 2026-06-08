import React, { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react'

const TestRunContext = createContext(null)

// Storage keys
const STORAGE_KEY = 'testmcpy_active_run'

export function TestRunProvider({ children }) {
  const [running, setRunning] = useState(false)
  const [runningTestName, setRunningTestName] = useState(null)
  const [testResults, setTestResults] = useState(null)
  const [streamingLogs, setStreamingLogs] = useState([])
  const [runningTests, setRunningTests] = useState({
    current: null,
    total: 0,
    completed: 0,
    status: 'idle'
  })
  const [testStatuses, setTestStatuses] = useState({})
  const [activeTestFile, setActiveTestFile] = useState(null)
  // Server-side run id of the in-flight run. Persisted so a browser
  // reload can reattach to the same run instead of orphaning it.
  // SC-108184.
  const [currentRunId, setCurrentRunId] = useState(null)
  // Per-file progress strip for directory batches. Set by the
  // `file_start` / `file_complete` events the server emits inside a
  // run_directory task. null when no batch is running.
  const [directoryRunProgress, setDirectoryRunProgress] = useState(null)
  // A historical run pinned into the Results tab. When non-null, the Results
  // tab renders this instead of the live `testResults`. Cleared automatically
  // at the start of any new run so live runs reclaim the tab.
  const [pinnedHistoryRun, setPinnedHistoryRun] = useState(null)
  const wsRef = useRef(null)
  // Reattach is wired up below but defined here so the mount effect can
  // refer to it via a ref (the ref is necessary because useCallback for
  // attachToRun needs `running` in its deps, and we don't want a stale
  // closure at mount time).
  const attachRef = useRef(null)

  // Load persisted state on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const data = JSON.parse(saved)
        // Only restore if it's recent (within last 5 minutes)
        const savedTime = new Date(data.timestamp).getTime()
        const now = Date.now()
        if (now - savedTime < 5 * 60 * 1000) {
          setStreamingLogs(data.logs || [])
          setTestResults(data.results || null)
          setTestStatuses(data.statuses || {})
          setRunningTests(data.runningTests || { current: null, total: 0, completed: 0, status: 'idle' })
          setActiveTestFile(data.testFile || null)
          setCurrentRunId(data.currentRunId || null)
          setDirectoryRunProgress(data.directoryRunProgress || null)
          // If the previous session was mid-run AND we have a run_id,
          // reattach to the server-side run. The server keeps the run
          // alive across browser reloads (SC-108184). Pre-fix this just
          // appended "⚠️ Previous run was interrupted by page reload".
          if (data.running && data.currentRunId && data.runningTests?.status === 'running') {
            // Re-mark running so the spinner / Stop button reappear
            // immediately; the attach completes asynchronously.
            setRunning(true)
            // Use the ref so we get the current attachToRun closure;
            // calling it inline at mount time would resolve to the
            // closure captured when the ref was empty.
            queueMicrotask(() => {
              if (attachRef.current) attachRef.current(data.currentRunId)
            })
          }
        } else {
          // Clear old data
          localStorage.removeItem(STORAGE_KEY)
        }
      }
    } catch (e) {
      console.error('Failed to restore test run state:', e)
    }
  }, [])

  // Persist state changes
  const persistState = useCallback(() => {
    try {
      const data = {
        timestamp: new Date().toISOString(),
        logs: streamingLogs,
        results: testResults,
        statuses: testStatuses,
        runningTests,
        testFile: activeTestFile,
        running,
        currentRunId,
        directoryRunProgress,
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
    } catch (e) {
      console.error('Failed to persist test run state:', e)
    }
  }, [
    streamingLogs,
    testResults,
    testStatuses,
    runningTests,
    activeTestFile,
    running,
    currentRunId,
    directoryRunProgress,
  ])

  // Persist on state changes
  useEffect(() => {
    persistState()
  }, [
    streamingLogs,
    testResults,
    testStatuses,
    runningTests,
    currentRunId,
    directoryRunProgress,
    persistState,
  ])

  // Shared SSE-style server-message handler used by all WS flows
  // (single-file run, single-test run, directory batch, reattach).
  //
  // Centralising the switch makes it cheap to add a new event type
  // server-side; pre-SC-108184 the switch was duplicated three times.
  // Each caller can pass options to tune behaviour for their flow:
  // - closeOnComplete: close the WS once `all_complete` arrives.
  //   Reattach mode passes false because the server closes its end.
  const _handleServerMessage = useCallback((ws, data, options = {}) => {
    const { closeOnComplete = true } = options
    switch (data.type) {
      case 'run_started': {
        setCurrentRunId(data.run_id)
        if (data.reattached) {
          setStreamingLogs(prev => [
            ...prev,
            `🔁 Reattached to run ${data.run_id} (server-side status: ${data.status})`,
          ])
        }
        break
      }
      case 'log':
      case 'log_replay': {
        setStreamingLogs(prev => [...prev, data.message])
        break
      }
      case 'test_start': {
        setRunningTests(prev => ({
          ...prev,
          current: data.test_name,
          completed: data.index ?? prev.completed,
          total: data.total ?? prev.total,
        }))
        setTestStatuses(prev => ({ ...prev, [data.test_name]: 'running' }))
        break
      }
      case 'test_complete': {
        const result = data.result
        setTestStatuses(prev => ({
          ...prev,
          [data.test_name]: result.passed ? 'passed' : 'failed',
        }))
        setTestResults(prev => {
          const prevResults = prev?.results || []
          // Replace any prior result with the same test_name (the
          // single-test rerun path uses this; for fresh runs it's a no-op).
          const existing = prevResults.filter(r => r.test_name !== data.test_name)
          const newResults = [...existing, result]
          return {
            summary: {
              total: newResults.length,
              passed: newResults.filter(r => r.passed).length,
              failed: newResults.filter(r => !r.passed).length,
              total_cost: newResults.reduce((sum, r) => sum + (r.cost || 0), 0),
              total_tokens: newResults.reduce(
                (sum, r) => sum + (r.token_usage?.total || 0),
                0,
              ),
            },
            results: newResults,
          }
        })
        break
      }
      case 'file_start': {
        setDirectoryRunProgress(prev => ({
          folder: prev?.folder ?? '',
          current: (data.index ?? 0) + 1,
          total: data.total ?? 0,
          name: data.name,
          test_path: data.test_path,
          // Preserve any partial summary built up so far.
          results: prev?.results ?? [],
        }))
        setStreamingLogs(prev => [...prev, `📂 File ${(data.index ?? 0) + 1}/${data.total}: ${data.name}`])
        break
      }
      case 'file_complete': {
        setDirectoryRunProgress(prev =>
          prev
            ? {
                ...prev,
                results: [...(prev.results || []), {
                  file: data.name,
                  test_path: data.test_path,
                  summary: data.summary,
                }],
              }
            : prev,
        )
        break
      }
      case 'all_complete': {
        if (data.summary && data.results) {
          setTestResults({ summary: data.summary, results: data.results })
        }
        setRunningTests(prev => ({
          ...prev,
          current: null,
          completed: data.summary?.total ?? prev.completed,
          status: 'completed',
        }))
        setRunning(false)
        setDirectoryRunProgress(null)
        setStreamingLogs(prev => [...prev, '✅ All tests complete!'])
        if (closeOnComplete) {
          try { ws.close() } catch (e) { /* noop */ }
        }
        break
      }
      case 'superseded': {
        // Another browser tab attached to the same run; this WS will
        // stop receiving live updates. Surface that so the user knows
        // why the log stream froze.
        setStreamingLogs(prev => [
          ...prev,
          `🔀 Another client attached to this run (token ${data.by_token}); this view is no longer live.`,
        ])
        setRunning(false)
        try { ws.close() } catch (e) { /* noop */ }
        break
      }
      case 'error': {
        setStreamingLogs(prev => [...prev, `❌ ERROR: ${data.message}`])
        if (data.traceback) {
          setStreamingLogs(prev => [...prev, data.traceback])
        }
        setRunning(false)
        setRunningTests(prev => ({ ...prev, status: 'error' }))
        if (closeOnComplete) {
          try { ws.close() } catch (e) { /* noop */ }
        }
        break
      }
      default:
        // Unknown type — silently drop. Forward-compatible.
        break
    }
  }, [])

  // Run all tests for a file
  const runTests = useCallback(async (testFile, testPath, llmConfig, mcpProfile, testLocations = [], llmProfile = null) => {
    if (running) return

    setRunning(true)
    setActiveTestFile(testFile)
    setTestResults(null)
    setPinnedHistoryRun(null)
    setStreamingLogs(['🚀 Starting test run...'])

    const tests = testLocations.length > 0 ? testLocations : [{ name: 'test' }]
    const totalTests = tests.length

    setRunningTests({
      current: 'Connecting...',
      total: totalTests,
      completed: 0,
      status: 'running'
    })

    // Reset all test statuses
    const initialStatuses = {}
    tests.forEach(t => initialStatuses[t.name] = 'idle')
    setTestStatuses(initialStatuses)

    // Create WebSocket connection
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/tests`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setStreamingLogs(prev => [...prev, '🔌 Connected to test runner'])
        ws.send(JSON.stringify({
          type: 'run_test',
          test_path: testPath,
          model: llmConfig.model,
          provider: llmConfig.provider,
          profile: mcpProfile,
          llm_profile: llmProfile,
        }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        _handleServerMessage(ws, data, { closeOnComplete: true })
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        setStreamingLogs(prev => [...prev, `❌ WebSocket error: ${error.message || 'Connection failed'}`])
        setRunning(false)
        setRunningTests(prev => ({ ...prev, status: 'error' }))
      }

      ws.onclose = (event) => {
        // Check if this was an unexpected close (test was still running)
        // Note: We use a closure check here since `running` state may be stale
        if (wsRef.current === ws) {
          // This WebSocket was still the active one
          setRunning(currentRunning => {
            if (currentRunning) {
              // Unexpected disconnect while test was running
              setStreamingLogs(prev => [...prev, '⚠️ Connection lost while test was running'])
              setRunningTests(prev => ({ ...prev, status: 'error', current: null }))
              return false
            }
            return currentRunning
          })
        }
        setStreamingLogs(prev => [...prev, '🔌 Disconnected'])
        wsRef.current = null
      }

    } catch (error) {
      console.error('Failed to run tests:', error)
      setStreamingLogs(prev => [...prev, `❌ Failed: ${error.message}`])
      setRunning(false)
      setRunningTests({
        current: null,
        total: 0,
        completed: 0,
        status: 'idle'
      })
    }
  }, [running])

  // Run a single test
  const runSingleTest = useCallback(async (testName, testFile, testPath, llmConfig, mcpProfile, llmProfile = null) => {
    if (running) return

    setRunning(true)
    setRunningTestName(testName)
    setActiveTestFile(testFile)
    setPinnedHistoryRun(null)
    setTestStatuses(prev => ({ ...prev, [testName]: 'running' }))
    setStreamingLogs([`🚀 Running test: ${testName}`])

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/tests`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setStreamingLogs(prev => [...prev, '🔌 Connected to test runner'])
        ws.send(JSON.stringify({
          type: 'run_test',
          test_path: testPath,
          test_name: testName,
          model: llmConfig.model,
          provider: llmConfig.provider,
          profile: mcpProfile,
          llm_profile: llmProfile,
        }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        _handleServerMessage(ws, data, { closeOnComplete: true })
        // Single-test path also clears the per-test cursor when its
        // dedicated test finishes (the shared handler doesn't know
        // about single-test mode).
        if (data.type === 'all_complete' || data.type === 'error') {
          setRunningTestName(null)
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        setStreamingLogs(prev => [...prev, `❌ WebSocket error`])
        setTestStatuses(prev => ({ ...prev, [testName]: 'failed' }))
        setRunning(false)
        setRunningTestName(null)
      }

      ws.onclose = () => {
        wsRef.current = null
      }

    } catch (error) {
      console.error('Failed to run test:', error)
      setStreamingLogs(prev => [...prev, `❌ Failed: ${error.message}`])
      setTestStatuses(prev => ({ ...prev, [testName]: 'failed' }))
      setRunning(false)
      setRunningTestName(null)
    }
  }, [running])

  // Run an entire directory batch under one server-side run_id.
  // Pre-SC-108184 this was a sequential HTTP POST loop with no log
  // streaming — the Logs tab never opened for batch runs.
  const runDirectory = useCallback(async (
    folderName,
    files,
    llmConfig,
    mcpProfile,
    llmProfile = null,
  ) => {
    if (running) return

    setRunning(true)
    setActiveTestFile(folderName)
    setTestResults(null)
    setPinnedHistoryRun(null)
    setStreamingLogs([`🚀 Starting directory run: ${folderName} (${files.length} file(s))`])
    setRunningTests({
      current: 'Connecting...',
      total: files.length,
      completed: 0,
      status: 'running',
    })
    setDirectoryRunProgress({
      folder: folderName,
      current: 0,
      total: files.length,
      results: [],
    })

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/tests`

    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        setStreamingLogs(prev => [...prev, '🔌 Connected to test runner'])
        ws.send(JSON.stringify({
          type: 'run_directory',
          folder: folderName,
          files: files.map(f => ({
            test_path: f.path || f.test_path,
            name: f.filename || f.name,
          })),
          model: llmConfig.model,
          provider: llmConfig.provider,
          profile: mcpProfile,
          llm_profile: llmProfile,
        }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        _handleServerMessage(ws, data, { closeOnComplete: true })
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        setStreamingLogs(prev => [...prev, `❌ WebSocket error: ${error.message || 'Connection failed'}`])
        setRunning(false)
        setRunningTests(prev => ({ ...prev, status: 'error' }))
        setDirectoryRunProgress(null)
      }

      ws.onclose = () => {
        if (wsRef.current === ws) {
          setRunning(currentRunning => {
            if (currentRunning) {
              setStreamingLogs(prev => [...prev, '⚠️ Connection lost during directory run'])
              setRunningTests(prev => ({ ...prev, status: 'error', current: null }))
              return false
            }
            return currentRunning
          })
        }
        setStreamingLogs(prev => [...prev, '🔌 Disconnected'])
        wsRef.current = null
      }
    } catch (error) {
      console.error('Failed to start directory run:', error)
      setStreamingLogs(prev => [...prev, `❌ Failed: ${error.message}`])
      setRunning(false)
      setRunningTests({ current: null, total: 0, completed: 0, status: 'idle' })
      setDirectoryRunProgress(null)
    }
  }, [running, _handleServerMessage])

  // Reattach to a server-side run by id. The server replays buffered
  // logs as `log_replay` events, then streams live updates until the
  // run finishes or another client supersedes us.
  const attachToRun = useCallback(async (runId) => {
    if (!runId) return
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/tests`
    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'attach', run_id: runId }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        _handleServerMessage(ws, data, { closeOnComplete: true })
      }

      ws.onerror = (error) => {
        console.error('Reattach WebSocket error:', error)
        setStreamingLogs(prev => [
          ...prev,
          `⚠️ Could not reattach to run ${runId}: ${error.message || 'connection failed'}`,
        ])
        setRunning(false)
      }

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
      }
    } catch (error) {
      console.error('Failed to reattach:', error)
      setStreamingLogs(prev => [...prev, `⚠️ Could not reattach: ${error.message}`])
      setRunning(false)
    }
  }, [_handleServerMessage])

  // Expose attachToRun via a ref so the mount-time restoration effect
  // can call the current closure even though it ran before the
  // useCallback was registered.
  useEffect(() => {
    attachRef.current = attachToRun
  }, [attachToRun])

  // Stop a running test — sends a stop message to the server and closes the socket.
  // The server-side task will be cancelled; results received so far are preserved.
  const stopTests = useCallback(() => {
    const ws = wsRef.current
    if (ws) {
      try {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'stop' }))
        }
      } catch (e) {
        // ignore — we're closing anyway
      }
      try { ws.close() } catch (e) { /* noop */ }
      wsRef.current = null
    }
    setStreamingLogs(prev => [...prev, '🛑 Stopped by user'])
    setRunning(false)
    setRunningTestName(null)
    setRunningTests(prev => ({ ...prev, current: null, status: 'stopped' }))
  }, [])

  // Clear logs
  const clearLogs = useCallback(() => {
    setStreamingLogs([])
  }, [])

  // Clear results
  const clearResults = useCallback(() => {
    setTestResults(null)
    setTestStatuses({})
    setStreamingLogs([])
    setRunningTests({ current: null, total: 0, completed: 0, status: 'idle' })
    setCurrentRunId(null)
    setDirectoryRunProgress(null)
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  // Reset test statuses (for when file content changes)
  const resetTestStatuses = useCallback((testNames) => {
    const initialStatuses = {}
    testNames.forEach(name => initialStatuses[name] = 'idle')
    setTestStatuses(initialStatuses)
  }, [])

  const value = {
    // State
    running,
    runningTestName,
    testResults,
    streamingLogs,
    runningTests,
    testStatuses,
    activeTestFile,
    pinnedHistoryRun,
    currentRunId,
    directoryRunProgress,
    // Actions
    runTests,
    runSingleTest,
    runDirectory,
    attachToRun,
    stopTests,
    clearLogs,
    clearResults,
    resetTestStatuses,
    setTestStatuses,
    setTestResults,
    setPinnedHistoryRun,
    setDirectoryRunProgress,
    // For "Run All LLMs" mode which manages its own state
    setRunning,
    setRunningTests,
  }

  return (
    <TestRunContext.Provider value={value}>
      {children}
    </TestRunContext.Provider>
  )
}

export function useTestRun() {
  const context = useContext(TestRunContext)
  if (!context) {
    throw new Error('useTestRun must be used within a TestRunProvider')
  }
  return context
}

export default TestRunContext
