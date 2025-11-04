import React, { useState, useEffect } from 'react'
import { Server, Check, AlertCircle, RefreshCw } from 'lucide-react'

function MCPProfiles() {
  const [profiles, setProfiles] = useState([])
  const [defaultProfile, setDefaultProfile] = useState(null)
  const [selectedProfiles, setSelectedProfiles] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadProfiles()
    // Load selected profiles from localStorage
    const saved = localStorage.getItem('selectedMCPProfiles')
    if (saved) {
      setSelectedProfiles(new Set(JSON.parse(saved)))
    }
  }, [])

  const fetchWithRetry = async (url, retries = 3, delay = 1000) => {
    for (let i = 0; i < retries; i++) {
      try {
        const response = await fetch(url)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response
      } catch (error) {
        if (i === retries - 1) throw error
        console.log(`Retry ${i + 1}/${retries} for ${url}...`)
        await new Promise(resolve => setTimeout(resolve, delay))
      }
    }
  }

  const loadProfiles = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchWithRetry('/api/mcp/profiles')
      const data = await res.json()

      if (data.error) {
        setError(data.error)
      } else if (data.message) {
        setError(data.message)
      } else {
        setProfiles(data.profiles || [])
        setDefaultProfile(data.default)

        // If no profiles selected and there's a default, select it
        if (selectedProfiles.size === 0 && data.default) {
          const newSelected = new Set([data.default])
          setSelectedProfiles(newSelected)
          localStorage.setItem('selectedMCPProfiles', JSON.stringify([data.default]))
        }
      }
    } catch (error) {
      console.error('Failed to load MCP profiles:', error)
      setError('Failed to load MCP profiles. Make sure .mcp_services.yaml exists.')
    } finally {
      setLoading(false)
    }
  }

  const toggleProfile = (profileId) => {
    const newSelected = new Set(selectedProfiles)
    if (newSelected.has(profileId)) {
      newSelected.delete(profileId)
    } else {
      newSelected.add(profileId)
    }
    setSelectedProfiles(newSelected)
    localStorage.setItem('selectedMCPProfiles', JSON.stringify(Array.from(newSelected)))
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
          <div className="text-text-secondary">Loading MCP profiles...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-border bg-surface-elevated">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">MCP Profiles</h1>
            <p className="text-text-secondary mt-1 text-base">
              Select which MCP services to use in chat
            </p>
          </div>
          <button
            onClick={loadProfiles}
            className="btn-secondary flex items-center gap-2"
          >
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {error ? (
          <div className="max-w-2xl mx-auto">
            <div className="bg-surface-elevated border border-warning rounded-lg p-4 flex items-start gap-3">
              <AlertCircle size={20} className="text-warning mt-0.5 flex-shrink-0" />
              <div>
                <h3 className="font-medium text-warning mb-1">Configuration Not Found</h3>
                <p className="text-text-secondary text-sm mb-3">{error}</p>
                <p className="text-text-secondary text-sm">
                  Create a <code className="font-mono bg-surface px-1 rounded">.mcp_services.yaml</code> file to define MCP profiles. See{' '}
                  <a
                    href="https://github.com/preset-io/testmcpy/blob/main/docs/MCP_PROFILES.md"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    documentation
                  </a> for examples.
                </p>
              </div>
            </div>
          </div>
        ) : profiles.length === 0 ? (
          <div className="max-w-2xl mx-auto text-center py-12">
            <Server size={48} className="text-text-disabled mx-auto mb-4" />
            <h2 className="text-xl font-medium mb-2">No MCP Profiles Found</h2>
            <p className="text-text-secondary mb-4">
              Create a .mcp_services.yaml file to configure multiple MCP services
            </p>
            <a
              href="https://github.com/preset-io/testmcpy/blob/main/docs/MCP_PROFILES.md"
              target="_blank"
              rel="noopener noreferrer"
              className="btn-primary inline-block"
            >
              View Documentation
            </a>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto">
            <div className="mb-4 text-sm text-text-secondary">
              Select one or more MCP services to use. Selected services will be available in the chat interface.
              {selectedProfiles.size > 0 && (
                <span className="ml-2 text-primary font-medium">
                  {selectedProfiles.size} profile{selectedProfiles.size !== 1 ? 's' : ''} selected
                </span>
              )}
            </div>

            <div className="grid gap-3">
              {profiles.map((profile) => {
                const isSelected = selectedProfiles.has(profile.id)
                const isDefault = profile.id === defaultProfile

                return (
                  <div
                    key={profile.id}
                    onClick={() => toggleProfile(profile.id)}
                    className={`
                      border rounded-lg p-4 cursor-pointer transition-all
                      ${isSelected
                        ? 'border-primary bg-primary/5'
                        : 'border-border bg-surface-elevated hover:border-primary/50'
                      }
                    `}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3 flex-1">
                        <div className={`
                          w-5 h-5 rounded border-2 flex items-center justify-center flex-shrink-0 mt-0.5
                          ${isSelected
                            ? 'border-primary bg-primary'
                            : 'border-border'
                          }
                        `}>
                          {isSelected && <Check size={14} className="text-white" />}
                        </div>

                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <h3 className="font-medium">{profile.name}</h3>
                            {isDefault && (
                              <span className="px-2 py-0.5 text-xs rounded-full bg-primary/20 text-primary">
                                Default
                              </span>
                            )}
                          </div>

                          <div className="text-sm text-text-secondary space-y-1">
                            <div className="flex items-center gap-2">
                              <span className="text-text-disabled">URL:</span>
                              <code className="font-mono text-xs bg-surface px-2 py-0.5 rounded">
                                {profile.mcp_url}
                              </code>
                            </div>

                            {profile.auth && (
                              <div className="flex items-center gap-2">
                                <span className="text-text-disabled">Auth:</span>
                                <span className="text-xs">{profile.auth.type || 'bearer'}</span>
                                {profile.auth.token && (
                                  <code className="font-mono text-xs bg-surface px-2 py-0.5 rounded">
                                    {profile.auth.token}
                                  </code>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      <Server
                        size={20}
                        className={isSelected ? 'text-primary' : 'text-text-disabled'}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default MCPProfiles
