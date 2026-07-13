import React, { useState, useEffect, useRef } from 'react'
import ConfirmDialog from '../components/ConfirmDialog'
import { useNotification } from '../components/NotificationProvider'
import {
  Cpu, Check, AlertCircle, RefreshCw, ChevronDown, ChevronRight,
  Edit2, Trash2, Plus, Save, X, Copy, Download, Settings,
  CheckCircle, XCircle, AlertTriangle, DollarSign, Zap, Play, Loader2,
  Eye, EyeOff, Key, Star, Wand2
} from 'lucide-react'
import Wizard from '../components/Wizard'

const PROVIDER_OPTIONS = [
  ['anthropic', 'Anthropic (Claude)'],
  ['openai', 'OpenAI (GPT)'],
  ['google', 'Google (Gemini)'],
  ['ollama', 'Ollama (Local)'],
  ['claude-code', 'Claude Code CLI'],
  ['claude-sdk', 'Claude Agent SDK'],
  ['codex-sdk', 'Codex SDK'],
  ['gemini-sdk', 'Gemini SDK'],
  ['assistant', 'Preset Assistant'],
]

const CLI_AUTH_PROVIDERS = ['claude-code', 'claude-sdk', 'codex-sdk']
const PROVIDER_SECRET_FIELDS = [
  'api_key', 'api_key_env', 'base_url', 'workspace_hash', 'domain', 'api_token',
  'api_secret', 'api_url', 'conversations_path', 'completions_path',
]

function registryProvider(provider) {
  return {
    'claude-code': 'claude-sdk',
    'codex-sdk': 'codex-cli',
  }[provider] || provider
}

export function switchProvider(formData, provider) {
  const resetFields = Object.fromEntries(PROVIDER_SECRET_FIELDS.map(field => [field, null]))
  return {
    ...formData,
    ...resetFields,
    provider,
    model: '',
    name: '',
    testResult: null,
    testLoading: false,
  }
}

export function normalizeProviderPayload(provider) {
  return Object.fromEntries(Object.entries(provider).map(([field, value]) => [
    field,
    PROVIDER_SECRET_FIELDS.includes(field) && typeof value === 'string' && !value.trim()
      ? null
      : value,
  ]))
}

export function normalizeLLMTestResponse(response, data) {
  if (response.ok) return data
  const detail = typeof data?.detail === 'string'
    ? data.detail
    : data?.detail
      ? JSON.stringify(data.detail)
      : `Provider test failed (${response.status})`
  return { success: false, tested: true, error: detail }
}

export function apiErrorMessage(data, fallback) {
  const detail = data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map(item => typeof item === 'string' ? item : item?.msg)
      .filter(Boolean)
    if (messages.length > 0) return messages.join('; ')
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail)
    } catch {
      // Fall through to the stable caller-provided message.
    }
  }
  return fallback
}

export function assistantConfigError(data) {
  if (!['assistant', 'chatbot'].includes(data.provider)) return null
  const requiredFields = [
    ['workspace_hash', 'Workspace hash'],
    ['domain', 'Domain'],
    ['api_url', 'Auth API URL'],
    ['api_token', 'API token'],
    ['api_secret', 'API secret'],
    ['conversations_path', 'Conversations path'],
    ['completions_path', 'Completions path'],
  ]
  const missing = requiredFields.find(([field]) => !data[field]?.trim())
  if (missing) return `${missing[1]} is required for Assistant`

  try {
    const url = new URL(data.api_url)
    if (!['http:', 'https:'].includes(url.protocol)) throw new Error('unsupported protocol')
  } catch {
    return 'Auth API URL must be an absolute HTTP(S) URL'
  }
  const validPath = value => /^\/(?!\/)[^?#\\\u0000-\u001f]*$/.test(value)
  if (!validPath(data.conversations_path)) {
    return 'Conversations path must be a same-origin path starting with one /'
  }
  if (!validPath(data.completions_path)) {
    return 'Completions path must be a same-origin path starting with one /'
  }
  return null
}

export function providerTestKey(profileId, providerIndex, provider) {
  return `${profileId}:${provider?._config_token || providerIndex}`
}

export function profileStateFromResponse(data) {
  const profiles = data.profiles || []
  return {
    profiles,
    defaultProfile: profiles.length > 0 ? (data.default || null) : null,
    error: data.message && profiles.length === 0 ? data.message : null,
  }
}

export async function createDefaultLLMConfig(availableModels, fetcher = fetch) {
  const defaultModel = availableModels.find(model => model.provider === 'anthropic' && model.is_default)
    || availableModels.find(model => model.provider === 'anthropic')
  if (!defaultModel) throw new Error('No Anthropic model is available in the registry')

  const createResponse = await fetcher('/api/llm/profiles/prod', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: 'Production',
      description: 'High-quality models for production use',
      providers: [{
        name: defaultModel.name,
        provider: 'anthropic',
        model: defaultModel.id,
        timeout: 60,
        default: true,
      }],
    }),
  })
  const createData = await createResponse.json()
  if (!createResponse.ok || !createData.success) {
    throw new Error(apiErrorMessage(createData, 'Failed to create configuration'))
  }

  const defaultResponse = await fetcher('/api/llm/profiles/default/prod', { method: 'PUT' })
  const defaultData = await defaultResponse.json()
  if (!defaultResponse.ok || !defaultData.success) {
    throw new Error(apiErrorMessage(defaultData, 'Configuration created, but could not set it as default'))
  }
}

export function LLMTestResult({ result }) {
  const notTested = result.tested === false
  const passed = result.success === true
  const containerClass = notTested
    ? 'bg-warning/10 border border-warning/30'
    : passed
      ? 'bg-success/10 border border-success/30'
      : 'bg-error/10 border border-error/30'
  const statusClass = notTested ? 'text-warning' : passed ? 'text-success' : 'text-error'
  const label = notTested ? 'Live test unavailable' : passed ? 'Test passed' : 'Test failed'

  return (
    <div className={`mt-2 p-2 rounded text-xs ${containerClass}`}>
      <div className="flex items-center gap-1.5">
        {notTested ? (
          <AlertTriangle size={12} className="text-warning" />
        ) : passed ? (
          <CheckCircle size={12} className="text-success" />
        ) : (
          <XCircle size={12} className="text-error" />
        )}
        <span className={statusClass}>{label}</span>
        {result.duration != null && (
          <span className="text-text-tertiary ml-auto">{result.duration.toFixed(2)}s</span>
        )}
      </div>
      {result.response && (
        <div className="mt-1 text-text-secondary truncate">Response: {result.response}</div>
      )}
      {result.error && (
        <div className={`mt-1 ${statusClass}`}>
          {notTested ? 'Reason' : 'Error'}: {result.error}
        </div>
      )}
    </div>
  )
}

// Provider icon helper
function getProviderIcon(provider) {
  switch (provider?.toLowerCase()) {
    case 'anthropic':
      return <span className="text-orange-500 font-bold text-xs">A</span>
    case 'openai':
      return <span className="text-green-500 font-bold text-xs">O</span>
    case 'google':
    case 'gemini':
      return <span className="text-blue-500 font-bold text-xs">G</span>
    case 'claude-code':
      return <span className="text-purple-500 font-bold text-xs">CC</span>
    case 'claude-sdk':
      return <span className="text-indigo-500 font-bold text-xs">SDK</span>
    case 'codex-sdk':
      return <span className="text-green-600 font-bold text-xs">CX</span>
    case 'gemini-sdk':
      return <span className="text-blue-600 font-bold text-xs">GS</span>
    case 'assistant':
    case 'chatbot':
      return <span className="text-cyan-600 font-bold text-xs">PA</span>
    case 'ollama':
      return <span className="text-text-tertiary font-bold text-xs">L</span>
    default:
      return <Cpu size={14} className="text-text-disabled" />
  }
}

// Profile editor modal
export function ProfileEditorModal({ profile, onSave, onCancel }) {
  const [profileId, setProfileId] = useState(profile?.profile_id || '')
  const [name, setName] = useState(profile?.name || '')
  const [description, setDescription] = useState(profile?.description || '')
  const [errors, setErrors] = useState({})
  const isNew = !profile

  const validate = () => {
    const newErrors = {}
    if (isNew && !profileId.trim()) newErrors.profileId = 'Profile ID is required'
    if (isNew && profileId && !/^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(profileId)) {
      newErrors.profileId = 'Start with a letter or number; then use letters, numbers, dots, underscores, tildes, or hyphens'
    }
    if (isNew && profileId.length > 64) newErrors.profileId = 'Profile ID must be 64 characters or fewer'
    if (!name.trim()) newErrors.name = 'Name is required'
    if (name.length > 255) newErrors.name = 'Name must be 255 characters or fewer'
    if (description.length > 2000) newErrors.description = 'Description must be 2000 characters or fewer'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (validate()) {
      onSave({ profileId, name, description })
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-0 md:p-4">
      <div className="bg-surface-elevated border border-border rounded-none md:rounded-lg p-6 md:max-w-md w-full h-full md:h-auto max-h-full md:max-h-[90vh] mx-0 md:mx-4 shadow-xl">
        <h3 className="text-lg font-bold mb-4">
          {isNew ? 'New LLM Profile' : 'Edit LLM Profile'}
        </h3>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label htmlFor="llm-profile-id" className="block text-sm font-medium mb-1 text-text-secondary">Profile ID</label>
              <input
                id="llm-profile-id"
                type="text"
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                className={`input w-full${errors.profileId ? ' border-error/50' : ''}`}
                placeholder="e.g., prod, dev, budget"
                maxLength={64}
                disabled={!isNew}
                autoFocus={isNew}
              />
              {errors.profileId && (
                <p className="text-error text-xs mt-1">{errors.profileId}</p>
              )}
            </div>
            <div>
              <label htmlFor="llm-profile-name" className="block text-sm font-medium mb-1 text-text-secondary">Profile Name</label>
              <input
                id="llm-profile-name"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={`input w-full${errors.name ? ' border-error/50' : ''}`}
                placeholder="e.g., Production, Development"
                maxLength={255}
                autoFocus={!isNew}
              />
              {errors.name && (
                <p className="text-error text-xs mt-1">{errors.name}</p>
              )}
            </div>
            <div>
              <label htmlFor="llm-profile-description" className="block text-sm font-medium mb-1 text-text-secondary">Description</label>
              <textarea
                id="llm-profile-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="input w-full"
                rows={3}
                maxLength={2000}
                placeholder="Describe when to use this profile..."
              />
              {errors.description && (
                <p className="text-error text-xs mt-1">{errors.description}</p>
              )}
            </div>
          </div>
          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-3 mt-6">
            <button type="button" onClick={onCancel} className="btn btn-secondary w-full sm:w-auto">
              Cancel
            </button>
            <button type="submit" className="btn btn-primary w-full sm:w-auto">
              <Save size={16} />
              {isNew ? 'Create Profile' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// Provider editor modal with model registry
export function ProviderEditorModal({ provider, availableModels, onSave, onCancel }) {
  const [formData, setFormData] = useState({
    ...(provider || {}),
    name: provider?.name || '',
    provider: provider?.provider || 'anthropic',
    model: provider?.model || '',
    // Keep absent fetched fields as null. Converting them to an empty string
    // makes a no-op edit look like a credential-destination change to the API.
    api_key: provider?.api_key ?? null,  // Direct API key
    api_key_env: provider?.api_key_env ?? null,  // Or env var name
    base_url: provider?.base_url ?? null,
    timeout: provider?.timeout ?? 60,
    default: provider?.default ?? false,
  })
  const [showApiKey, setShowApiKey] = useState(false)  // Toggle visibility
  const [errors, setErrors] = useState({})
  const [filteredModels, setFilteredModels] = useState([])
  const codexAuth = formData.provider === 'codex-sdk'

  useEffect(() => {
    // Filter models based on selected provider
    if (availableModels && formData.provider) {
      const providerKey = registryProvider(formData.provider.toLowerCase())
      const filtered = availableModels.filter(m =>
        m.provider === providerKey ||
        (providerKey === 'gemini' && m.provider === 'google')
      )
      setFilteredModels(filtered)

      // Suggest a default model only when none is set yet (new provider /
      // after a provider switch clears it). Never overwrite an existing value
      // — it may be a custom model name the user typed that isn't in the
      // registry.
      if (filtered.length > 0 && !formData.model) {
        const defaultModel = filtered.find(m => m.is_default) || filtered[0]
        setFormData(prev => ({ ...prev, model: defaultModel.id, name: prev.name || defaultModel.name }))
      }
    }
  }, [formData.provider, availableModels])

  const validate = () => {
    const newErrors = {}
    if (!formData.name.trim()) newErrors.name = 'Name is required'
    if (formData.name.length > 255) newErrors.name = 'Name must be 255 characters or fewer'
    if (!formData.model.trim()) newErrors.model = 'Model is required'
    if (formData.model.length > 255) newErrors.model = 'Model must be 255 characters or fewer'
    const assistantError = assistantConfigError(formData)
    if (assistantError) newErrors.assistant = assistantError
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (validate()) {
      onSave(normalizeProviderPayload(formData))
    }
  }

  const updateField = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }))
    if (errors[field]) {
      setErrors(prev => ({ ...prev, [field]: undefined }))
    }
  }

  const handleModelSelect = (modelId) => {
    // Accept any value (registry model id OR a custom model name typed in).
    updateField('model', modelId)
    const model = availableModels?.find(m => m.id === modelId)
    if (model && (!formData.name || formData.name === provider?.name)) {
      updateField('name', model.name)
    }
  }

  const selectedModel = availableModels?.find(m => m.id === formData.model)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 overflow-y-auto p-0 md:p-4">
      <div className="bg-surface-elevated border border-border rounded-none md:rounded-lg p-6 md:max-w-2xl w-full h-full md:h-auto max-h-full md:max-h-[90vh] my-0 md:my-8 shadow-xl overflow-y-auto">
        <h3 className="text-lg font-bold mb-4">
          {provider ? 'Edit Provider' : 'Add Provider'}
        </h3>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
            {/* Provider Type */}
            <div>
              <label htmlFor="llm-provider-type" className="block text-sm font-medium mb-1 text-text-secondary">Provider</label>
              <select
                id="llm-provider-type"
                value={formData.provider}
                onChange={(e) => setFormData(prev => switchProvider(prev, e.target.value))}
                className="input w-full"
              >
                {!PROVIDER_OPTIONS.some(([value]) => value === formData.provider) && (
                  <option value={formData.provider}>{formData.provider}</option>
                )}
                {PROVIDER_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>

            {/* Model Selection — combobox: pick a known model or type any name */}
            <div>
              <label htmlFor="llm-provider-model" className="block text-sm font-medium mb-1 text-text-secondary">Model</label>
              <input
                id="llm-provider-model"
                type="text"
                list="provider-model-options"
                value={formData.model}
                onChange={(e) => handleModelSelect(e.target.value)}
                className={`input w-full font-mono text-sm${errors.model ? ' border-error/50' : ''}`}
                placeholder="Select a model or type any model name"
                maxLength={255}
                autoComplete="off"
              />
              <datalist id="provider-model-options">
                {filteredModels.map(model => (
                  <option key={model.id} value={model.id}>
                    {model.name} — ${model.input_price_per_1m}/1M in, ${model.output_price_per_1m}/1M out
                  </option>
                ))}
              </datalist>
              <p className="text-text-tertiary text-xs mt-1">
                {filteredModels.length > 0
                  ? 'Choose from the list or type a custom model name.'
                  : 'Type the exact model name for this provider.'}
              </p>
              {errors.model && <p className="text-error text-xs mt-1">{errors.model}</p>}
            </div>

            {/* Model Info Card */}
            {selectedModel && (
              <div className="bg-surface rounded-lg p-3 border border-border">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium">{selectedModel.name}</div>
                    <div className="text-xs text-text-secondary mt-1">{selectedModel.description}</div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="flex items-center gap-1 text-text-secondary">
                      <DollarSign size={12} />
                      ${selectedModel.input_price_per_1m}/1M in
                    </div>
                    <div className="flex items-center gap-1 text-text-secondary">
                      <DollarSign size={12} />
                      ${selectedModel.output_price_per_1m}/1M out
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {selectedModel.capabilities?.map(cap => (
                    <span key={cap} className="px-1.5 py-0.5 bg-primary/10 text-primary text-xs rounded">
                      {cap}
                    </span>
                  ))}
                </div>
                <div className="text-xs text-text-tertiary mt-2">
                  Context: {selectedModel.context_window?.toLocaleString()} tokens
                </div>
              </div>
            )}

            {/* Display Name */}
            <div>
              <label htmlFor="llm-provider-name" className="block text-sm font-medium mb-1 text-text-secondary">Display Name</label>
              <input
                id="llm-provider-name"
                type="text"
                value={formData.name}
                onChange={(e) => updateField('name', e.target.value)}
                className={`input w-full${errors.name ? ' border-error/50' : ''}`}
                placeholder="e.g., Claude Sonnet 4.5"
                maxLength={255}
              />
              {errors.name && <p className="text-error text-xs mt-1">{errors.name}</p>}
            </div>

            {/* API Key Section - CLI and Assistant providers use their own auth. */}
            {![...CLI_AUTH_PROVIDERS, 'assistant', 'chatbot'].includes(formData.provider) && (
              <div className="space-y-3 p-3 bg-surface rounded-lg border border-border">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Key size={14} />
                  API Key Configuration
                </div>

                {/* Direct API Key */}
                <div>
                  <label htmlFor="llm-provider-api-key" className="block text-xs font-medium mb-1 text-text-secondary">API Key (direct)</label>
                  <div className="relative">
                    <input
                      id="llm-provider-api-key"
                      type={showApiKey ? 'text' : 'password'}
                      value={formData.api_key ?? ''}
                      onChange={(e) => updateField('api_key', e.target.value)}
                      className="input w-full font-mono text-sm pr-10"
                      placeholder="sk-ant-... or sk-..."
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-surface-hover rounded"
                    >
                      {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>

                <div className="text-center text-xs text-text-tertiary">— or —</div>

                {/* Environment Variable */}
                <div>
                  <label htmlFor="llm-provider-api-key-env" className="block text-xs font-medium mb-1 text-text-secondary">Environment Variable</label>
                  <input
                    id="llm-provider-api-key-env"
                    type="text"
                    value={formData.api_key_env ?? ''}
                    onChange={(e) => updateField('api_key_env', e.target.value)}
                    className="input w-full font-mono text-sm"
                    placeholder="e.g., ANTHROPIC_API_KEY"
                  />
                  <p className="text-text-tertiary text-xs mt-1">
                    Leave both empty to use default env var for the provider
                  </p>
                </div>
              </div>
            )}

            {/* Optional auth token for CLI-backed providers. */}
            {CLI_AUTH_PROVIDERS.includes(formData.provider) && (
              <div className="space-y-3 p-3 bg-surface rounded-lg border border-border">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Key size={14} />
                  {codexAuth ? 'OpenAI API key (optional)' : 'Claude auth token (optional)'}
                </div>

                {/* Direct token */}
                <div>
                  <label htmlFor="llm-provider-cli-token" className="block text-xs font-medium mb-1 text-text-secondary">{codexAuth ? 'OpenAI API key (direct)' : 'Token (direct)'}</label>
                  <div className="relative">
                    <input
                      id="llm-provider-cli-token"
                      type={showApiKey ? 'text' : 'password'}
                      value={formData.api_key ?? ''}
                      onChange={(e) => updateField('api_key', e.target.value)}
                      className="input w-full font-mono text-sm pr-10"
                      placeholder={codexAuth ? 'sk-...' : 'sk-ant-oat... or sk-ant-api...'}
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-surface-hover rounded"
                    >
                      {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>

                <div className="text-center text-xs text-text-tertiary">— or —</div>

                {/* Environment Variable */}
                <div>
                  <label htmlFor="llm-provider-cli-token-env" className="block text-xs font-medium mb-1 text-text-secondary">Environment Variable</label>
                  <input
                    id="llm-provider-cli-token-env"
                    type="text"
                    value={formData.api_key_env ?? ''}
                    onChange={(e) => updateField('api_key_env', e.target.value)}
                    className="input w-full font-mono text-sm"
                    placeholder={codexAuth ? 'e.g., OPENAI_API_KEY' : 'e.g., CLAUDE_CODE_OAUTH_TOKEN'}
                  />
                </div>

                <p className="text-text-secondary text-xs mt-1">
                  {codexAuth ? (
                    <>Provide an OpenAI API key. Leave blank only if the host's <code className="bg-surface px-1 rounded">~/.codex/auth.json</code> contains <code className="bg-surface px-1 rounded">OPENAI_API_KEY</code>; OAuth-only login is not supported.</>
                  ) : (
                    <>Paste a Claude subscription token from <code className="bg-surface px-1 rounded">claude setup-token</code> or an Anthropic API key. Leave blank to use the host's <code className="bg-surface px-1 rounded">claude</code> login.</>
                  )}
                </p>
              </div>
            )}

            {['assistant', 'chatbot'].includes(formData.provider) && (
              <div className="space-y-3 p-3 bg-surface rounded-lg border border-border">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Key size={14} /> Assistant connection
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="llm-assistant-workspace" className="block text-xs font-medium mb-1 text-text-secondary">Workspace Hash</label>
                    <input id="llm-assistant-workspace" type="text" value={formData.workspace_hash || ''} onChange={(e) => updateField('workspace_hash', e.target.value)} className="input w-full font-mono text-sm" />
                  </div>
                  <div>
                    <label htmlFor="llm-assistant-domain" className="block text-xs font-medium mb-1 text-text-secondary">Domain</label>
                    <input id="llm-assistant-domain" type="text" value={formData.domain || ''} onChange={(e) => updateField('domain', e.target.value)} className="input w-full font-mono text-sm" placeholder="example.com" />
                  </div>
                </div>
                <div>
                  <label htmlFor="llm-assistant-api-url" className="block text-xs font-medium mb-1 text-text-secondary">Auth API URL</label>
                  <input id="llm-assistant-api-url" type="url" value={formData.api_url || ''} onChange={(e) => updateField('api_url', e.target.value)} className="input w-full font-mono text-sm" />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="llm-assistant-api-token" className="block text-xs font-medium mb-1 text-text-secondary">API Token</label>
                    <input id="llm-assistant-api-token" type="password" value={formData.api_token || ''} onChange={(e) => updateField('api_token', e.target.value)} className="input w-full font-mono text-sm" autoComplete="new-password" />
                  </div>
                  <div>
                    <label htmlFor="llm-assistant-api-secret" className="block text-xs font-medium mb-1 text-text-secondary">API Secret</label>
                    <input id="llm-assistant-api-secret" type="password" value={formData.api_secret || ''} onChange={(e) => updateField('api_secret', e.target.value)} className="input w-full font-mono text-sm" autoComplete="new-password" />
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="llm-assistant-conversations" className="block text-xs font-medium mb-1 text-text-secondary">Conversations Path</label>
                    <input id="llm-assistant-conversations" type="text" value={formData.conversations_path || ''} onChange={(e) => updateField('conversations_path', e.target.value)} className="input w-full font-mono text-sm" />
                  </div>
                  <div>
                    <label htmlFor="llm-assistant-completions" className="block text-xs font-medium mb-1 text-text-secondary">Completions Path</label>
                    <input id="llm-assistant-completions" type="text" value={formData.completions_path || ''} onChange={(e) => updateField('completions_path', e.target.value)} className="input w-full font-mono text-sm" />
                  </div>
                </div>
                {errors.assistant && (
                  <p className="text-error text-xs mt-1">{errors.assistant}</p>
                )}
              </div>
            )}

            {/* Base URL (for Ollama) */}
            {formData.provider === 'ollama' && (
              <div>
                <label htmlFor="llm-provider-base-url" className="block text-sm font-medium mb-1 text-text-secondary">Base URL</label>
                <input
                  id="llm-provider-base-url"
                  type="text"
                  value={formData.base_url ?? ''}
                  onChange={(e) => updateField('base_url', e.target.value)}
                  className="input w-full font-mono text-sm"
                  placeholder="http://localhost:11434"
                />
              </div>
            )}

            {/* Timeout */}
            <div>
              <label htmlFor="llm-provider-timeout" className="block text-sm font-medium mb-1 text-text-secondary">Timeout (seconds)</label>
              <input
                id="llm-provider-timeout"
                type="number"
                value={formData.timeout}
                onChange={(e) => updateField('timeout', parseInt(e.target.value) || 60)}
                className="input w-full"
                min="10"
                max="300"
              />
            </div>

            {/* Default Provider */}
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="default"
                checked={formData.default}
                onChange={(e) => updateField('default', e.target.checked)}
                className="w-4 h-4"
              />
              <label htmlFor="default" className="text-sm">
                <span className="font-medium">Set as default provider</span>
                <span className="text-text-tertiary ml-1">(used when no specific provider requested)</span>
              </label>
            </div>
          </div>

          <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-3 mt-6 pt-4 border-t border-border">
            <button type="button" onClick={onCancel} className="btn btn-secondary w-full sm:w-auto">
              Cancel
            </button>
            <button type="submit" className="btn btn-primary w-full sm:w-auto">
              <Save size={16} />
              Save Provider
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// LLM Provider Wizard - guided multi-step flow for adding a provider
export function LLMWizard({ profiles, availableModels, onComplete, onCancel }) {
  const testRequestId = useRef(0)
  const [wizardData, setWizardData] = useState({
    // Step 1: Provider type
    provider: 'anthropic',
    // Step 2: Model selection
    model: '',
    name: '',
    // Step 3: Credentials
    api_key: '',
    api_key_env: '',
    base_url: '',
    workspace_hash: '',
    domain: '',
    api_token: '',
    api_secret: '',
    api_url: '',
    conversations_path: '',
    completions_path: '',
    timeout: 60,
    default: false,
    showApiKey: false,
    // Test result
    testResult: null,
    testLoading: false,
    // Step 4: Save
    targetProfileId: profiles.length > 0 ? profiles[0].profile_id : '',
  })

  const providerCards = [
    { value: 'anthropic', label: 'Anthropic', desc: 'Claude models - Sonnet, Opus, Haiku', color: 'text-orange-500', letter: 'A' },
    { value: 'openai', label: 'OpenAI', desc: 'GPT-4o, GPT-4 Turbo, o1 models', color: 'text-green-500', letter: 'O' },
    { value: 'google', label: 'Gemini', desc: 'Gemini 2.5 Pro/Flash, 1.5 Pro', color: 'text-blue-500', letter: 'G' },
    { value: 'ollama', label: 'Ollama', desc: 'Local models (Llama, Mistral, etc.)', color: 'text-text-tertiary', letter: 'L' },
    { value: 'claude-sdk', label: 'Claude SDK', desc: 'Agent SDK, uses Claude auth', color: 'text-indigo-500', letter: 'SDK' },
    { value: 'claude-code', label: 'Claude Code', desc: 'Claude Code CLI, no API key needed', color: 'text-purple-500', letter: 'CC' },
    { value: 'codex-sdk', label: 'Codex SDK', desc: 'OpenAI Agents SDK with native MCP', color: 'text-green-600', letter: 'CX' },
    { value: 'gemini-sdk', label: 'Gemini SDK', desc: 'Google ADK with native MCP', color: 'text-blue-600', letter: 'GS' },
    { value: 'assistant', label: 'Assistant', desc: 'Preset workspace assistant API', color: 'text-cyan-600', letter: 'PA' },
  ]

  // Get filtered models for selected provider
  const getFilteredModels = () => {
    if (!availableModels || !wizardData.provider) return []
    const key = registryProvider(wizardData.provider.toLowerCase())
    return availableModels.filter(m =>
      m.provider === key || (key === 'gemini' && m.provider === 'google')
    )
  }

  const updateTestConfiguration = (setData, updates) => {
    testRequestId.current += 1
    setData(prev => ({
      ...prev,
      ...(typeof updates === 'function' ? updates(prev) : updates),
      testResult: null,
      testLoading: false,
    }))
  }

  const handleTestCredentials = async () => {
    const requestId = ++testRequestId.current
    setWizardData(prev => ({ ...prev, testLoading: true, testResult: null }))
    try {
      const res = await fetch('/api/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: wizardData.provider,
          model: wizardData.model,
          api_key: wizardData.api_key || null,
          api_key_env: wizardData.api_key_env || null,
          base_url: wizardData.base_url || null,
          timeout: wizardData.timeout,
        })
      })
      const data = await res.json()
      if (requestId !== testRequestId.current) return
      setWizardData(prev => ({
        ...prev,
        testLoading: false,
        testResult: normalizeLLMTestResponse(res, data)
      }))
    } catch (err) {
      if (requestId !== testRequestId.current) return
      setWizardData(prev => ({
        ...prev,
        testLoading: false,
        testResult: { success: false, error: err.message }
      }))
    }
  }

  const steps = [
    {
      label: 'Provider',
      validate: (data) => {
        if (!data.provider) return 'Please select a provider'
        return true
      },
      component: ({ data, setData }) => (
        <div className="space-y-4">
          <p className="text-sm text-text-secondary">Choose your LLM provider:</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {providerCards.map(p => (
              <button
                key={p.value}
                type="button"
                onClick={() => {
                  testRequestId.current += 1
                  setData(prev => switchProvider(prev, p.value))
                }}
                className={`p-4 rounded-lg border-2 text-left transition-all ${
                  data.provider === p.value
                    ? 'border-primary bg-primary/10'
                    : 'border-border hover:border-primary/30'
                }`}
              >
                <div className={`text-lg font-bold ${p.color} mb-1`}>{p.letter}</div>
                <div className="font-medium text-sm">{p.label}</div>
                <div className="text-xs text-text-tertiary mt-1">{p.desc}</div>
              </button>
            ))}
          </div>
        </div>
      ),
    },
    {
      label: 'Model',
      validate: (data) => {
        if (!data.model.trim()) return 'Please select or enter a model'
        if (data.model.length > 255) return 'Model must be 255 characters or fewer'
        return true
      },
      component: ({ data, setData }) => {
        const filtered = getFilteredModels()
        const selectedModel = availableModels?.find(m => m.id === data.model)

        return (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1 text-text-secondary">Model</label>
              <input
                aria-label="Model"
                type="text"
                list="wizard-model-options"
                value={data.model}
                onChange={(e) => {
                  const model = availableModels?.find(m => m.id === e.target.value)
                  updateTestConfiguration(setData, prev => ({
                    model: e.target.value,
                    name: model && !prev.name?.trim() ? model.name : prev.name,
                  }))
                }}
                className="input w-full font-mono text-sm"
                placeholder="Select a model or type any model name"
                autoComplete="off"
                autoFocus
                maxLength={255}
              />
              <datalist id="wizard-model-options">
                {filtered.map(model => (
                  <option key={model.id} value={model.id}>
                    {model.name} — ${model.input_price_per_1m}/1M in, ${model.output_price_per_1m}/1M out
                  </option>
                ))}
              </datalist>
              <p className="text-text-tertiary text-xs mt-1">
                {filtered.length > 0
                  ? 'Choose from the list or type a custom model name.'
                  : 'Type the exact model name for this provider.'}
              </p>
            </div>

            {selectedModel && (
              <div className="bg-surface rounded-lg p-3 border border-border">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-medium">{selectedModel.name}</div>
                    <div className="text-xs text-text-secondary mt-1">{selectedModel.description}</div>
                  </div>
                  <div className="text-right text-xs">
                    <div className="flex items-center gap-1 text-text-secondary">
                      <DollarSign size={12} /> ${selectedModel.input_price_per_1m}/1M in
                    </div>
                    <div className="flex items-center gap-1 text-text-secondary">
                      <DollarSign size={12} /> ${selectedModel.output_price_per_1m}/1M out
                    </div>
                  </div>
                </div>
                {selectedModel.capabilities?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {selectedModel.capabilities.map(cap => (
                      <span key={cap} className="px-1.5 py-0.5 bg-primary/10 text-primary text-xs rounded">
                        {cap}
                      </span>
                    ))}
                  </div>
                )}
                <div className="text-xs text-text-tertiary mt-2">
                  Context: {selectedModel.context_window?.toLocaleString()} tokens
                </div>
              </div>
            )}

            <div>
              <label className="block text-sm font-medium mb-1 text-text-secondary">Display Name</label>
              <input
                aria-label="Display Name"
                type="text"
                value={data.name}
                onChange={(e) => setData(prev => ({ ...prev, name: e.target.value }))}
                className="input w-full"
                placeholder="e.g., Claude Sonnet 4"
              />
            </div>
          </div>
        )
      },
    },
    {
      label: 'Credentials',
      optional: CLI_AUTH_PROVIDERS.includes(wizardData.provider),
      validate: (data) => {
        if (!data.name.trim()) return 'Display name is required'
        if (data.name.length > 255) return 'Display name must be 255 characters or fewer'
        const assistantError = assistantConfigError(data)
        if (assistantError) return assistantError
        return true
      },
      component: ({ data, setData }) => {
        const cliAuth = CLI_AUTH_PROVIDERS.includes(data.provider)
        const assistant = ['assistant', 'chatbot'].includes(data.provider)
        const codexAuth = data.provider === 'codex-sdk'

        return (
          <div className="space-y-4">
            {assistant ? (
              <div className="space-y-3 p-3 bg-surface rounded-lg border border-border">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Key size={14} /> Assistant connection
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input aria-label="Workspace Hash" type="text" value={data.workspace_hash || ''} onChange={(e) => updateTestConfiguration(setData, { workspace_hash: e.target.value })} className="input w-full font-mono text-sm" placeholder="Workspace hash" />
                  <input aria-label="Domain" type="text" value={data.domain || ''} onChange={(e) => updateTestConfiguration(setData, { domain: e.target.value })} className="input w-full font-mono text-sm" placeholder="Workspace domain" />
                </div>
                <input aria-label="Auth API URL" type="url" value={data.api_url || ''} onChange={(e) => updateTestConfiguration(setData, { api_url: e.target.value })} className="input w-full font-mono text-sm" placeholder="Auth API URL" />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input aria-label="API Token" type="password" value={data.api_token || ''} onChange={(e) => updateTestConfiguration(setData, { api_token: e.target.value })} className="input w-full font-mono text-sm" placeholder="API token" autoComplete="new-password" />
                  <input aria-label="API Secret" type="password" value={data.api_secret || ''} onChange={(e) => updateTestConfiguration(setData, { api_secret: e.target.value })} className="input w-full font-mono text-sm" placeholder="API secret" autoComplete="new-password" />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input aria-label="Conversations Path" type="text" value={data.conversations_path || ''} onChange={(e) => updateTestConfiguration(setData, { conversations_path: e.target.value })} className="input w-full font-mono text-sm" placeholder="/api/v1/copilot/conversations" />
                  <input aria-label="Completions Path" type="text" value={data.completions_path || ''} onChange={(e) => updateTestConfiguration(setData, { completions_path: e.target.value })} className="input w-full font-mono text-sm" placeholder="/api/v1/copilot/completions" />
                </div>
              </div>
            ) : cliAuth ? (
              <div className="space-y-3 p-3 bg-surface rounded-lg border border-border">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Key size={14} /> {codexAuth ? 'OpenAI API key (optional)' : 'Claude auth token (optional)'}
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1 text-text-secondary">{codexAuth ? 'OpenAI API key (direct)' : 'Token (direct)'}</label>
                  <div className="relative">
                    <input
                      aria-label="Token (direct)"
                      type={data.showApiKey ? 'text' : 'password'}
                      value={data.api_key}
                      onChange={(e) => updateTestConfiguration(setData, { api_key: e.target.value })}
                      className="input w-full font-mono text-sm pr-10"
                      placeholder={codexAuth ? 'sk-...' : 'sk-ant-oat... or sk-ant-api...'}
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setData(prev => ({ ...prev, showApiKey: !prev.showApiKey }))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-surface-hover rounded"
                    >
                      {data.showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
                <div className="text-center text-xs text-text-tertiary">-- or --</div>
                <div>
                  <label className="block text-xs font-medium mb-1 text-text-secondary">Environment Variable</label>
                  <input
                    aria-label="Environment Variable"
                    type="text"
                    value={data.api_key_env}
                    onChange={(e) => updateTestConfiguration(setData, { api_key_env: e.target.value })}
                    className="input w-full font-mono text-sm"
                    placeholder={codexAuth ? 'e.g., OPENAI_API_KEY' : 'e.g., CLAUDE_CODE_OAUTH_TOKEN'}
                  />
                </div>
                <p className="text-text-secondary text-xs mt-1">
                  {codexAuth ? (
                    <>Provide an OpenAI API key. Leave blank only if the host's <code className="bg-surface px-1 rounded">~/.codex/auth.json</code> contains <code className="bg-surface px-1 rounded">OPENAI_API_KEY</code>; OAuth-only login is not supported.</>
                  ) : (
                    <>Paste a Claude subscription token from <code className="bg-surface px-1 rounded">claude setup-token</code> or an Anthropic API key. Leave blank to use the host's <code className="bg-surface px-1 rounded">claude</code> login.</>
                  )}
                </p>
              </div>
            ) : (
              <div className="space-y-3 p-3 bg-surface rounded-lg border border-border">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Key size={14} /> API Key Configuration
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1 text-text-secondary">API Key (direct)</label>
                  <div className="relative">
                    <input
                      aria-label="API Key (direct)"
                      type={data.showApiKey ? 'text' : 'password'}
                      value={data.api_key}
                      onChange={(e) => updateTestConfiguration(setData, { api_key: e.target.value })}
                      className="input w-full font-mono text-sm pr-10"
                    placeholder="sk-ant-... or sk-..."
                    maxLength={4096}
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setData(prev => ({ ...prev, showApiKey: !prev.showApiKey }))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-1 hover:bg-surface-hover rounded"
                    >
                      {data.showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
                <div className="text-center text-xs text-text-tertiary">-- or --</div>
                <div>
                  <label className="block text-xs font-medium mb-1 text-text-secondary">Environment Variable</label>
                  <input
                    aria-label="Environment Variable"
                    type="text"
                    value={data.api_key_env}
                    onChange={(e) => updateTestConfiguration(setData, { api_key_env: e.target.value })}
                    className="input w-full font-mono text-sm"
                    placeholder="e.g., ANTHROPIC_API_KEY"
                  />
                  <p className="text-text-tertiary text-xs mt-1">Leave both empty to use default env var</p>
                </div>
              </div>
            )}

            {data.provider === 'ollama' && (
              <div>
                <label className="block text-sm font-medium mb-1 text-text-secondary">Base URL</label>
                <input
                  aria-label="Base URL"
                  type="text"
                  value={data.base_url}
                  onChange={(e) => updateTestConfiguration(setData, { base_url: e.target.value })}
                  className="input w-full font-mono text-sm"
                  placeholder="http://localhost:11434"
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium mb-1 text-text-secondary">Timeout (seconds)</label>
              <input
                aria-label="Timeout (seconds)"
                type="number"
                value={data.timeout}
                onChange={(e) => updateTestConfiguration(setData, { timeout: parseInt(e.target.value) || 60 })}
                className="input w-full"
                min="10" max="300"
              />
            </div>

            <div className="flex items-center gap-2">
              <input type="checkbox" id="wiz_default_llm"
                checked={data.default}
                onChange={(e) => setData(prev => ({ ...prev, default: e.target.checked }))}
                className="w-4 h-4" />
              <label htmlFor="wiz_default_llm" className="text-sm">
                <span className="font-medium">Set as default provider</span>
              </label>
            </div>

            {/* Test button */}
            <div className="pt-2 border-t border-border">
              <button
                onClick={handleTestCredentials}
                disabled={data.testLoading}
                className="btn btn-secondary text-sm"
              >
                {data.testLoading ? (
                  <><Loader2 size={14} className="animate-spin" /> Testing...</>
                ) : (
                  <><Play size={14} /> Test Credentials</>
                )}
              </button>
              {data.testResult && (
                <LLMTestResult result={data.testResult} />
              )}
            </div>
          </div>
        )
      },
    },
    {
      label: 'Save',
      validate: (data) => {
        if (!data.targetProfileId) return 'Please select a profile'
        return true
      },
      component: ({ data, setData }) => {
        const selectedModel = availableModels?.find(m => m.id === data.model)
        return (
          <div className="space-y-4">
            <h4 className="text-sm font-medium text-text-secondary">Review your LLM provider configuration:</h4>
            <div className="bg-surface rounded-lg p-4 border border-border space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-text-tertiary">Provider</span>
                <span className="font-medium">{data.provider}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-tertiary">Model</span>
                <span className="font-mono text-xs">{data.model}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-tertiary">Display Name</span>
                <span>{data.name}</span>
              </div>
              {selectedModel && (
                <div className="flex justify-between">
                  <span className="text-text-tertiary">Pricing</span>
                  <span className="text-xs">${selectedModel.input_price_per_1m}/1M in, ${selectedModel.output_price_per_1m}/1M out</span>
                </div>
              )}
              {data.testResult?.success && (
                <div className="flex justify-between">
                  <span className="text-text-tertiary">Credential Test</span>
                  <span className="text-success flex items-center gap-1"><CheckCircle size={12} /> Passed</span>
                </div>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium mb-1 text-text-secondary">Add to Profile</label>
              <select
                aria-label="Add to Profile"
                value={data.targetProfileId}
                onChange={(e) => setData(prev => ({ ...prev, targetProfileId: e.target.value }))}
                className="input w-full"
              >
                {profiles.map(p => (
                  <option key={p.profile_id} value={p.profile_id}>{p.name}</option>
                ))}
              </select>
            </div>
          </div>
        )
      },
    },
  ]

  const handleComplete = (data) => {
    const providerData = {
      name: data.name,
      provider: data.provider,
      model: data.model,
      api_key: data.api_key || undefined,
      api_key_env: data.api_key_env || undefined,
      base_url: data.base_url || undefined,
      workspace_hash: data.workspace_hash || undefined,
      domain: data.domain || undefined,
      api_token: data.api_token || undefined,
      api_secret: data.api_secret || undefined,
      api_url: data.api_url || undefined,
      conversations_path: data.conversations_path || undefined,
      completions_path: data.completions_path || undefined,
      timeout: data.timeout,
      default: data.default,
    }
    return onComplete(data.targetProfileId, providerData)
  }

  return (
    <Wizard
      title="Add LLM Provider"
      steps={steps}
      data={wizardData}
      setData={setWizardData}
      onComplete={handleComplete}
      onCancel={onCancel}
    />
  )
}

function LLMProfiles({ selectedProfile, onSelectProfile, onProfilesChange, hideHeader = false }) {
  const [profiles, setProfiles] = useState([])
  const [defaultProfile, setDefaultProfile] = useState(null)
  const [availableModels, setAvailableModels] = useState([])
  const [expandedProfiles, setExpandedProfiles] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [confirmDialog, setConfirmDialog] = useState(null)
  const [profileEditor, setProfileEditor] = useState(null)
  const [providerEditor, setProviderEditor] = useState(null)
  const [testingProvider, setTestingProvider] = useState(null) // "profileId:providerIndex"
  const [testResults, setTestResults] = useState({}) // { "profileId:providerIndex": { success, response, error, duration } }
  const providerTestRequests = useRef({})
  const [showLLMWizard, setShowLLMWizard] = useState(false)

  useEffect(() => {
    loadProfiles()
    loadAvailableModels()
  }, [])

  useEffect(() => {
    // Auto-expand all profiles when they're loaded
    if (profiles.length > 0) {
      const allProfileIds = profiles.map(p => p.profile_id)
      setExpandedProfiles(new Set(allProfileIds))
    }
  }, [profiles])

  const loadProfiles = async (notifyParent = false) => {
    setLoading(true)
    setError(null)
    providerTestRequests.current = {}
    setTestingProvider(null)
    setTestResults({})
    try {
      const res = await fetch('/api/llm/profiles')
      const data = await res.json()
      if (!res.ok) throw new Error(apiErrorMessage(data, `Failed to load profiles (${res.status})`))

      const nextState = profileStateFromResponse(data)
      setProfiles(nextState.profiles)
      setDefaultProfile(nextState.defaultProfile)
      setError(nextState.error)
      // Notify parent component to refresh its state, including deletion of
      // the final profile.
      if (notifyParent && onProfilesChange) {
        onProfilesChange()
      }
    } catch (error) {
      console.error('Failed to load LLM profiles:', error)
      setError('Failed to load LLM profiles')
    } finally {
      setLoading(false)
    }
  }

  const loadAvailableModels = async () => {
    try {
      const res = await fetch('/api/llm/models')
      const data = await res.json()
      if (!res.ok) throw new Error(apiErrorMessage(data, `Failed to load models (${res.status})`))
      setAvailableModels(data.models || [])
    } catch (error) {
      console.error('Failed to load available models:', error)
    }
  }

  const { success: notifySuccess, error: notifyError, warning: notifyWarning } = useNotification()
  const showToast = (message, type = 'success') => {
    if (type === 'error') notifyError(message)
    else if (type === 'warning') notifyWarning(message)
    else notifySuccess(message)
  }

  const toggleExpanded = (profileId) => {
    const newExpanded = new Set(expandedProfiles)
    if (newExpanded.has(profileId)) {
      newExpanded.delete(profileId)
    } else {
      newExpanded.add(profileId)
    }
    setExpandedProfiles(newExpanded)
  }

  // Test provider connection
  const handleTestProvider = async (profileId, providerIndex, provider) => {
    const testKey = providerTestKey(profileId, providerIndex, provider)
    const requestId = (providerTestRequests.current[testKey] || 0) + 1
    providerTestRequests.current[testKey] = requestId
    setTestingProvider(testKey)
    // Clear previous result for this provider
    setTestResults(prev => ({ ...prev, [testKey]: null }))

    try {
      const res = await fetch('/api/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: provider.provider,
          model: provider.model,
          api_key: provider.api_key || null,  // Direct API key
          api_key_env: provider.api_key_env || null,  // Or env var name
          base_url: provider.base_url || null,
          timeout: provider.timeout || 30,
          profile_id: profileId,
          provider_index: providerIndex,
        })
      })
      const data = await res.json()
      if (providerTestRequests.current[testKey] !== requestId) return
      const result = normalizeLLMTestResponse(res, data)

      setTestResults(prev => ({ ...prev, [testKey]: result }))

      if (result.success) {
        showToast(`Test passed: ${result.response?.substring(0, 50) || 'OK'}`)
      } else if (result.tested === false) {
        showToast(result.error || 'A live test is not available for this provider', 'warning')
      } else {
        showToast(result.error || 'Test failed', 'error')
      }
    } catch (error) {
      if (providerTestRequests.current[testKey] !== requestId) return
      const errorResult = { success: false, error: error.message }
      setTestResults(prev => ({ ...prev, [testKey]: errorResult }))
      showToast(`Test failed: ${error.message}`, 'error')
    } finally {
      if (providerTestRequests.current[testKey] === requestId) {
        setTestingProvider(current => current === testKey ? null : current)
      }
    }
  }

  // Profile operations
  const handleCreateProfile = async (profileData) => {
    try {
      const res = await fetch(`/api/llm/profiles/${profileData.profileId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: profileData.name,
          description: profileData.description,
          providers: []
        })
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        setProfileEditor(null)
        showToast('Profile created successfully')
      } else {
        showToast(apiErrorMessage(data, 'Failed to create profile'), 'error')
      }
    } catch (error) {
      console.error('Failed to create profile:', error)
      showToast('Failed to create profile', 'error')
    }
  }

  const handleUpdateProfile = async (profileId, profileData) => {
    try {
      // Get current profile data
      const currentProfile = profiles.find(p => p.profile_id === profileId)

      const res = await fetch(`/api/llm/profiles/${profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: profileData.name,
          description: profileData.description,
          providers: currentProfile?.providers || []
        })
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        setProfileEditor(null)
        showToast('Profile updated successfully')
      } else {
        showToast(apiErrorMessage(data, 'Failed to update profile'), 'error')
      }
    } catch (error) {
      console.error('Failed to update profile:', error)
      showToast('Failed to update profile', 'error')
    }
  }

  const handleDeleteProfile = async (profileId) => {
    try {
      const res = await fetch(`/api/llm/profiles/${profileId}`, {
        method: 'DELETE'
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        setConfirmDialog(null)
        showToast('Profile deleted successfully')
      } else {
        showToast(apiErrorMessage(data, 'Failed to delete profile'), 'error')
      }
    } catch (error) {
      console.error('Failed to delete profile:', error)
      showToast('Failed to delete profile', 'error')
    }
  }

  const handleSetDefault = async (profileId) => {
    try {
      const res = await fetch(`/api/llm/profiles/default/${profileId}`, {
        method: 'PUT'
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        if (onSelectProfile) {
          onSelectProfile(profileId)
        }
        showToast('Default profile updated')
      } else {
        showToast(apiErrorMessage(data, 'Failed to set default profile'), 'error')
      }
    } catch (error) {
      console.error('Failed to set default:', error)
      showToast('Failed to set default profile', 'error')
    }
  }

  // Provider operations
  const handleAddProvider = async (profileId, providerData) => {
    try {
      const currentProfile = profiles.find(p => p.profile_id === profileId)
      let updatedProviders = [...(currentProfile?.providers || [])]

      // If the new provider is default, unset default on all existing providers
      if (providerData.default) {
        updatedProviders = updatedProviders.map(p => ({ ...p, default: false }))
      }

      updatedProviders.push(providerData)

      const res = await fetch(`/api/llm/profiles/${profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: currentProfile.name,
          description: currentProfile.description,
          providers: updatedProviders
        })
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        setProviderEditor(null)
        showToast('Provider added successfully')
        return true
      } else {
        showToast(apiErrorMessage(data, 'Failed to add provider'), 'error')
        return false
      }
    } catch (error) {
      console.error('Failed to add provider:', error)
      showToast('Failed to add provider', 'error')
      return false
    }
  }

  const handleUpdateProvider = async (profileId, providerIndex, providerData) => {
    try {
      const currentProfile = profiles.find(p => p.profile_id === profileId)
      let updatedProviders = [...currentProfile.providers]

      // If the updated provider is default, unset default on all other providers
      if (providerData.default) {
        updatedProviders = updatedProviders.map((p, idx) =>
          idx === providerIndex ? p : { ...p, default: false }
        )
      }

      updatedProviders[providerIndex] = providerData

      const res = await fetch(`/api/llm/profiles/${profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: currentProfile.name,
          description: currentProfile.description,
          providers: updatedProviders
        })
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        setProviderEditor(null)
        showToast('Provider updated successfully')
      } else {
        showToast(apiErrorMessage(data, 'Failed to update provider'), 'error')
      }
    } catch (error) {
      console.error('Failed to update provider:', error)
      showToast('Failed to update provider', 'error')
    }
  }

  // Set a provider as default (quick action without opening modal)
  const handleSetDefaultProvider = async (profileId, providerIndex) => {
    try {
      const currentProfile = profiles.find(p => p.profile_id === profileId)
      // Set all providers to non-default, except the selected one
      const updatedProviders = currentProfile.providers.map((p, idx) => ({
        ...p,
        default: idx === providerIndex
      }))

      const res = await fetch(`/api/llm/profiles/${profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: currentProfile.name,
          description: currentProfile.description,
          providers: updatedProviders
        })
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        showToast(`${currentProfile.providers[providerIndex].name} set as default`)
      } else {
        showToast(apiErrorMessage(data, 'Failed to set default provider'), 'error')
      }
    } catch (error) {
      console.error('Failed to set default provider:', error)
      showToast('Failed to set default provider', 'error')
    }
  }

  const handleDeleteProvider = async (profileId, providerIndex) => {
    try {
      const currentProfile = profiles.find(p => p.profile_id === profileId)
      const updatedProviders = currentProfile.providers.filter((_, idx) => idx !== providerIndex)

      const res = await fetch(`/api/llm/profiles/${profileId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: currentProfile.name,
          description: currentProfile.description,
          providers: updatedProviders
        })
      })
      const data = await res.json()

      if (data.success) {
        await loadProfiles(true)
        setConfirmDialog(null)
        showToast('Provider removed successfully')
      } else {
        showToast(apiErrorMessage(data, 'Failed to remove provider'), 'error')
      }
    } catch (error) {
      console.error('Failed to remove provider:', error)
      showToast('Failed to remove provider', 'error')
    }
  }

  const createDefaultConfig = async () => {
    try {
      await createDefaultLLMConfig(availableModels)
      await loadProfiles(true)
      showToast('Default configuration created')
    } catch (error) {
      console.error('Failed to create configuration:', error)
      // The profile may have been created before setting it as default failed.
      await loadProfiles(true)
      showToast(error.message || 'Failed to create configuration', 'error')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
          <div className="text-text-secondary">Loading LLM profiles...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      {!hideHeader && (
        <div className="p-4 border-b border-border bg-surface-elevated">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h1 className="text-xl md:text-2xl font-semibold text-text-primary">LLM Profiles</h1>
              <p className="text-text-secondary mt-1 text-base">
                Configure LLM providers for testing and chat
              </p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 w-full lg:w-auto">
              <button
                onClick={loadProfiles}
                className="btn btn-secondary flex items-center justify-center gap-2"
              >
                <RefreshCw size={16} />
                Refresh
              </button>
              <button
                onClick={() => setShowLLMWizard(true)}
                disabled={profiles.length === 0}
                title={profiles.length === 0 ? 'Create a profile before adding a provider' : undefined}
                className="btn btn-primary flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Wand2 size={16} />
                Add Provider (Wizard)
              </button>
              <button
                onClick={() => setProfileEditor({ isNew: true })}
                className="btn btn-secondary flex items-center justify-center gap-2"
              >
                <Plus size={16} />
                Add Profile
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-auto p-4">
        {error && profiles.length === 0 ? (
          <div className="max-w-2xl mx-auto">
            <div className="bg-surface-elevated border border-warning rounded-lg p-4 flex items-start gap-3">
              <AlertCircle size={20} className="text-warning mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <h3 className="font-medium text-warning mb-1">No Configuration Found</h3>
                <p className="text-text-secondary text-sm mb-3">{error}</p>
                <p className="text-text-secondary text-sm mb-4">
                  Create an LLM provider profile to get started with testing and chat features.
                </p>
                <button
                  onClick={createDefaultConfig}
                  className="btn btn-primary"
                >
                  Create Default Configuration
                </button>
              </div>
            </div>
          </div>
        ) : profiles.length === 0 ? (
          <div className="max-w-2xl mx-auto text-center py-12">
            <Cpu size={48} className="text-text-disabled mx-auto mb-4" />
            <h2 className="text-xl font-medium mb-2">No LLM Profiles Found</h2>
            <p className="text-text-secondary mb-4">
              Create an LLM provider profile to configure your AI models
            </p>
            <button
              onClick={() => setProfileEditor({ isNew: true })}
              className="btn btn-primary"
            >
              <Plus size={16} />
              Create Profile
            </button>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto">
            <div className="mb-4 text-sm text-text-secondary">
              Click the star icon to set a profile as default. Add providers to each profile for different use cases.
            </div>

            <div className="grid gap-3">
              {profiles.map((profile) => {
                const isDefault = profile.profile_id === defaultProfile
                const isExpanded = expandedProfiles.has(profile.profile_id)
                const providers = profile.providers || []
                const hasProviders = providers.length > 0
                const defaultProvider = providers.find(p => p.default) || providers[0]

                return (
                  <div
                    key={profile.profile_id}
                    className="border rounded-lg p-3 sm:p-4 transition-all border-border bg-surface-elevated min-w-0"
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between min-w-0">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2 mb-1 min-w-0">
                            <h3 className="font-medium break-words min-w-0">{profile.name}</h3>
                            <code className="text-xs text-text-tertiary bg-surface px-1 rounded break-all">{profile.profile_id}</code>
                            {isDefault && (
                              <span className="px-2 py-0.5 text-xs rounded-full bg-primary/20 text-primary">
                                Default
                              </span>
                            )}
                            {hasProviders && (
                              <span className="px-2 py-0.5 text-xs rounded-full bg-surface border border-border text-text-secondary">
                                {providers.length} provider{providers.length !== 1 ? 's' : ''}
                              </span>
                            )}
                          </div>

                          {profile.description && (
                            <p className="text-sm text-text-secondary mb-2 break-words">
                              {profile.description}
                            </p>
                          )}

                          {hasProviders && !isExpanded && defaultProvider && (
                            <div className="text-xs text-text-tertiary flex flex-wrap items-center gap-2 min-w-0">
                              {getProviderIcon(defaultProvider.provider)}
                              <span>{defaultProvider.name}</span>
                              <span className="text-text-disabled">({defaultProvider.model})</span>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center justify-end gap-1 self-end sm:self-start flex-shrink-0">
                        {/* Profile Actions */}
                        {!isDefault && (
                          <button
                            onClick={() => handleSetDefault(profile.profile_id)}
                            className="p-2 hover:bg-surface-hover rounded transition-colors"
                            title="Set as default"
                          >
                            <Settings size={16} className="text-text-secondary" />
                          </button>
                        )}

                        <button
                          onClick={() => setProfileEditor({ profile, profileId: profile.profile_id })}
                          className="p-2 hover:bg-surface-hover rounded transition-colors"
                          title="Edit profile"
                        >
                          <Edit2 size={16} className="text-text-secondary" />
                        </button>

                        <button
                          onClick={() => setConfirmDialog({
                            title: 'Delete Profile',
                            message: `Are you sure you want to delete "${profile.name}"? This action cannot be undone.`,
                            onConfirm: () => handleDeleteProfile(profile.profile_id)
                          })}
                          className="p-2 hover:bg-surface-hover rounded transition-colors"
                          title="Delete profile"
                        >
                          <Trash2 size={16} className="text-error" />
                        </button>

                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleExpanded(profile.profile_id)
                          }}
                          className="p-2 hover:bg-surface-hover rounded transition-colors ml-1"
                          title={isExpanded ? "Hide providers" : "Show providers"}
                        >
                          {isExpanded ? (
                            <ChevronDown size={18} className="text-text-secondary" />
                          ) : (
                            <ChevronRight size={18} className="text-text-secondary" />
                          )}
                        </button>
                      </div>
                    </div>

                    {/* Expanded Provider Details */}
                    {isExpanded && (
                      <div className="mt-4 space-y-2">
                        {providers.map((provider, idx) => {
                          const modelInfo = availableModels.find(m => m.id === provider.model)
                          const testKey = providerTestKey(profile.profile_id, idx, provider)

                          return (
                            <div
                              key={idx}
                              className={`rounded-lg p-3 space-y-2 transition-all ${
                                provider.default
                                  ? 'bg-primary/10 border-2 border-primary'
                                  : 'bg-surface border-2 border-transparent'
                              }`}
                            >
                              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between min-w-0">
                                <div className="flex flex-wrap items-center gap-2 flex-1 min-w-0">
                                  {provider.default && <Check size={14} className="text-primary flex-shrink-0" />}
                                  {getProviderIcon(provider.provider)}
                                  <span className="font-medium text-sm break-words min-w-0">{provider.name}</span>
                                  <span className="text-xs text-text-tertiary px-1.5 py-0.5 bg-surface-elevated rounded">
                                    {provider.provider}
                                  </span>
                                </div>

                                {/* Provider Actions */}
                                <div className="flex flex-wrap items-center justify-end gap-1 self-end sm:self-start flex-shrink-0">
                                  {/* Set as default button */}
                                  {!provider.default && (
                                    <button
                                      onClick={() => handleSetDefaultProvider(profile.profile_id, idx)}
                                      className="p-1 hover:bg-surface-elevated rounded transition-colors"
                                      title="Set as default provider"
                                    >
                                      <Star size={14} className="text-text-tertiary hover:text-warning" />
                                    </button>
                                  )}
                                  {provider.default && (
                                    <span className="p-1" title="Default provider">
                                      <Star size={14} className="text-warning fill-warning" />
                                    </span>
                                  )}

                                  <button
                                    onClick={() => handleTestProvider(profile.profile_id, idx, provider)}
                                    disabled={testingProvider === testKey}
                                    className="p-1 hover:bg-surface-elevated rounded transition-colors disabled:opacity-50"
                                    title="Test provider connection"
                                  >
                                    {testingProvider === testKey ? (
                                      <Loader2 size={14} className="text-primary animate-spin" />
                                    ) : (
                                      <Play size={14} className="text-success" />
                                    )}
                                  </button>

                                  <button
                                    onClick={() => setProviderEditor({ provider, profileId: profile.profile_id, providerIndex: idx })}
                                    className="p-1 hover:bg-surface-elevated rounded transition-colors"
                                    title="Edit provider"
                                  >
                                    <Edit2 size={14} className="text-text-secondary" />
                                  </button>

                                  <button
                                    onClick={() => setConfirmDialog({
                                      title: 'Remove Provider',
                                      message: `Are you sure you want to remove "${provider.name}"?`,
                                      onConfirm: () => handleDeleteProvider(profile.profile_id, idx)
                                    })}
                                    className="p-1 hover:bg-surface-elevated rounded transition-colors"
                                    title="Remove provider"
                                  >
                                    <Trash2 size={14} className="text-error" />
                                  </button>
                                </div>
                              </div>

                              <div className="space-y-1.5 text-xs">
                                <div className="flex items-start gap-2">
                                  <span className="text-text-disabled min-w-[60px]">Model:</span>
                                  <code className="font-mono bg-surface-elevated px-2 py-0.5 rounded flex-1 min-w-0 break-all">
                                    {provider.model}
                                  </code>
                                </div>

                                {modelInfo && (
                                  <div className="flex flex-wrap items-center gap-3 text-text-tertiary">
                                    <span className="flex items-center gap-1">
                                      <DollarSign size={12} />
                                      ${modelInfo.input_price_per_1m}/1M in
                                    </span>
                                    <span className="flex items-center gap-1">
                                      <DollarSign size={12} />
                                      ${modelInfo.output_price_per_1m}/1M out
                                    </span>
                                    <span className="flex items-center gap-1">
                                      <Zap size={12} />
                                      {(modelInfo.context_window / 1000).toFixed(0)}K ctx
                                    </span>
                                  </div>
                                )}

                                {provider.timeout && (
                                  <div className="text-text-tertiary">
                                    Timeout: {provider.timeout}s
                                  </div>
                                )}

                                {/* Test Result Display */}
                                {testResults[testKey] && (
                                  <LLMTestResult result={testResults[testKey]} />
                                )}
                              </div>
                            </div>
                          )
                        })}

                        {/* Add Provider Button */}
                        <button
                          onClick={() => setProviderEditor({ profileId: profile.profile_id, isNew: true })}
                          className="w-full p-3 border-2 border-dashed border-border rounded-lg hover:border-primary hover:bg-primary/5 transition-all flex items-center justify-center gap-2 text-text-secondary hover:text-primary"
                        >
                          <Plus size={16} />
                          Add Provider
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Modals and Dialogs */}
      {confirmDialog && (
        <ConfirmDialog
          title={confirmDialog.title}
          message={confirmDialog.message}
          onConfirm={confirmDialog.onConfirm}
          onCancel={() => setConfirmDialog(null)}
        />
      )}

      {profileEditor && (
        <ProfileEditorModal
          profile={profileEditor.profile}
          onSave={(data) => {
            if (profileEditor.isNew) {
              handleCreateProfile(data)
            } else {
              handleUpdateProfile(profileEditor.profileId, data)
            }
          }}
          onCancel={() => setProfileEditor(null)}
        />
      )}

      {providerEditor && (
        <ProviderEditorModal
          provider={providerEditor.provider}
          availableModels={availableModels}
          onSave={(data) => {
            if (providerEditor.isNew) {
              handleAddProvider(providerEditor.profileId, data)
            } else {
              handleUpdateProvider(providerEditor.profileId, providerEditor.providerIndex, data)
            }
          }}
          onCancel={() => setProviderEditor(null)}
        />
      )}

      {showLLMWizard && (
        <LLMWizard
          profiles={profiles}
          availableModels={availableModels}
          onComplete={async (profileId, providerData) => {
            const saved = await handleAddProvider(profileId, providerData)
            if (saved) setShowLLMWizard(false)
            return saved
          }}
          onCancel={() => setShowLLMWizard(false)}
        />
      )}
    </div>
  )
}

export default LLMProfiles
