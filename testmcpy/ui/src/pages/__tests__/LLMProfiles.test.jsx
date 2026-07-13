import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import {
  LLMTestResult,
  LLMWizard,
  ProfileEditorModal,
  ProviderEditorModal,
  apiErrorMessage,
  assistantConfigError,
  createDefaultLLMConfig,
  normalizeLLMTestResponse,
  normalizeProviderPayload,
  profileStateFromResponse,
  providerTestKey,
  switchProvider,
} from '../LLMProfiles'

describe('LLMTestResult', () => {
  it('rejects unusable Assistant URLs and endpoint paths', () => {
    const valid = {
      provider: 'assistant',
      workspace_hash: 'workspace',
      domain: 'example.com',
      api_url: 'https://auth.example.com/token',
      api_token: 'token',
      api_secret: 'secret',
      conversations_path: '/conversations',
      completions_path: '/completions',
    }

    expect(assistantConfigError(valid)).toBeNull()
    expect(assistantConfigError({ ...valid, api_url: 'not-a-url' })).toMatch(/absolute HTTP/)
    expect(assistantConfigError({ ...valid, conversations_path: 'conversations' })).toMatch(/same-origin/)
    expect(assistantConfigError({ ...valid, completions_path: '//attacker.example/x' })).toMatch(/same-origin/)
  })

  it('normalizes FastAPI validation arrays into renderable text', () => {
    expect(apiErrorMessage(
      { detail: [{ msg: 'Profile ID is too long' }, { msg: 'Name is required' }] },
      'Fallback',
    )).toBe('Profile ID is too long; Name is required')
  })

  it('distinguishes unsupported live checks from failed checks', () => {
    render(
      <LLMTestResult
        result={{
          success: false,
          tested: false,
          duration: 0,
          error: 'Authentication must be tested during an agent run',
        }}
      />,
    )

    expect(screen.getByText('Live test unavailable')).toBeInTheDocument()
    expect(screen.getByText(/Reason: Authentication must be tested/)).toBeInTheDocument()
    expect(screen.queryByText('Test failed')).not.toBeInTheDocument()
  })

  it('shows FastAPI validation details for rejected live tests', () => {
    const result = normalizeLLMTestResponse(
      { ok: false, status: 400 },
      { detail: "Environment variable 'DATABASE_PASSWORD' is not allowed for openai" },
    )

    render(<LLMTestResult result={result} />)
    expect(screen.getByText('Test failed')).toBeInTheDocument()
    expect(screen.getByText(/DATABASE_PASSWORD/)).toBeInTheDocument()
  })

  it('clears stale test state when the provider changes', () => {
    const changed = switchProvider(
      {
        provider: 'openai',
        model: 'gpt-test',
        api_key: 'configured',
        testLoading: true,
        testResult: { success: true },
      },
      'anthropic',
    )

    expect(changed.provider).toBe('anthropic')
    expect(changed.model).toBe('')
    expect(changed.api_key).toBeNull()
    expect(changed.api_key_env).toBeNull()
    expect(changed.testLoading).toBe(false)
    expect(changed.testResult).toBeNull()
  })

  it('does not reuse a deleted provider test result for the row shifted into its index', () => {
    const priorResultKey = providerTestKey('prod', 0, { _config_token: 'provider-a' })
    const results = { [priorResultKey]: { success: true } }
    const shiftedProviderKey = providerTestKey('prod', 0, { _config_token: 'provider-b' })

    expect(results[shiftedProviderKey]).toBeUndefined()
  })

  it('clears stale cards and the default when the final profile is deleted', () => {
    expect(profileStateFromResponse({
      profiles: [],
      default: 'deleted',
      message: 'No .llm_providers.yaml file found',
    })).toEqual({
      profiles: [],
      defaultProfile: null,
      error: 'No .llm_providers.yaml file found',
    })
  })
})

describe('ProfileEditorModal', () => {
  it('allows editing a legacy profile whose ID is not valid for new profiles', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(
      <ProfileEditorModal
        profile={{ profile_id: 'Production_1.0', name: 'Legacy', description: '' }}
        onSave={onSave}
        onCancel={() => {}}
      />,
    )

    const name = screen.getByLabelText('Profile Name')
    await user.clear(name)
    await user.type(name, 'Legacy Renamed')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(onSave).toHaveBeenCalledWith({
      profileId: 'Production_1.0',
      name: 'Legacy Renamed',
      description: '',
    })
    expect(screen.queryByText(/lowercase letters/)).not.toBeInTheDocument()
  })

  it('limits new profile IDs to the API maximum', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<ProfileEditorModal onSave={onSave} onCancel={() => {}} />)

    await user.type(screen.getByLabelText('Profile ID'), 'a'.repeat(65))
    await user.type(screen.getByLabelText('Profile Name'), 'Long ID')
    await user.click(screen.getByRole('button', { name: 'Create Profile' }))

    expect(screen.getByLabelText('Profile ID')).toHaveValue('a'.repeat(64))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ profileId: 'a'.repeat(64) }))
  })

  it('preserves every profile ID character accepted by the API', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<ProfileEditorModal onSave={onSave} onCancel={() => {}} />)

    await user.type(screen.getByLabelText('Profile ID'), 'Prod_1.0~Canary-blue')
    await user.type(screen.getByLabelText('Profile Name'), 'Production Canary')
    await user.click(screen.getByRole('button', { name: 'Create Profile' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      profileId: 'Prod_1.0~Canary-blue',
    }))
  })

  it('rejects IDs outside the API grammar without rewriting them', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<ProfileEditorModal onSave={onSave} onCancel={() => {}} />)

    await user.type(screen.getByLabelText('Profile ID'), '.invalid/id')
    await user.type(screen.getByLabelText('Profile Name'), 'Invalid ID')
    await user.click(screen.getByRole('button', { name: 'Create Profile' }))

    expect(screen.getByLabelText('Profile ID')).toHaveValue('.invalid/id')
    expect(screen.getByText(/Start with a letter or number/)).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('limits profile names to the API maximum', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(<ProfileEditorModal onSave={onSave} onCancel={() => {}} />)

    await user.type(screen.getByLabelText('Profile ID'), 'long-name')
    await user.type(screen.getByLabelText('Profile Name'), 'n'.repeat(256))
    await user.click(screen.getByRole('button', { name: 'Create Profile' }))

    expect(screen.getByLabelText('Profile Name')).toHaveValue('n'.repeat(255))
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ name: 'n'.repeat(255) }))
  })
})

describe('ProviderEditorModal', () => {
  it('submits a cleared direct key as absent while retaining its environment key', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(
      <ProviderEditorModal
        provider={{
          name: 'OpenAI',
          provider: 'openai',
          model: 'gpt-test',
          api_key_env: 'OPENAI_API_KEY',
        }}
        availableModels={[]}
        onSave={onSave}
        onCancel={() => {}}
      />,
    )

    const directKey = screen.getByLabelText('API Key (direct)')
    await user.type(directKey, 'temporary-key')
    await user.clear(directKey)
    await user.click(screen.getByRole('button', { name: 'Save Provider' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      api_key: null,
      api_key_env: 'OPENAI_API_KEY',
    }))
  })

  it('normalizes only blank optional fields in provider payloads', () => {
    expect(normalizeProviderPayload({
      api_key: '***',
      api_key_env: '${OPENAI_API_KEY}',
      base_url: '  ',
    })).toEqual({
      api_key: '***',
      api_key_env: '${OPENAI_API_KEY}',
      base_url: null,
    })
  })

  it('preserves absent destinations and row binding on a no-op direct-key edit', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(
      <ProviderEditorModal
        provider={{
          name: 'OpenAI',
          provider: 'openai',
          model: 'gpt-test',
          api_key: '***',
          timeout: 60,
          default: true,
          custom_option: 'keep-me',
          _config_index: 0,
          _config_token: 'row-revision-token',
        }}
        availableModels={[]}
        onSave={onSave}
        onCancel={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Save Provider' }))

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      api_key: '***',
      api_key_env: null,
      base_url: null,
      custom_option: 'keep-me',
      _config_index: 0,
      _config_token: 'row-revision-token',
    }))
  })

  it('does not persist an incomplete Assistant configuration', async () => {
    const onSave = vi.fn()
    const user = userEvent.setup()
    render(
      <ProviderEditorModal
        availableModels={[]}
        onSave={onSave}
        onCancel={() => {}}
      />,
    )

    await user.selectOptions(screen.getByLabelText('Provider'), 'assistant')
    await user.type(screen.getByLabelText('Model'), 'assistant-model')
    await user.type(screen.getByLabelText('Display Name'), 'Assistant')
    await user.click(screen.getByRole('button', { name: 'Save Provider' }))

    expect(await screen.findByText('Workspace hash is required for Assistant')).toBeInTheDocument()
    expect(onSave).not.toHaveBeenCalled()
  })
})

describe('createDefaultLLMConfig', () => {
  const models = [{ id: 'claude-test', name: 'Claude Test', provider: 'anthropic', is_default: true }]

  it('creates the profile and then makes it the profile default', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) })

    await createDefaultLLMConfig(models, fetcher)

    expect(fetcher).toHaveBeenNthCalledWith(1, '/api/llm/profiles/prod', expect.objectContaining({ method: 'POST' }))
    expect(fetcher).toHaveBeenNthCalledWith(2, '/api/llm/profiles/default/prod', { method: 'PUT' })
  })

  it('surfaces a normalized error when setting the default fails', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) })
      .mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: [{ msg: 'Default profile rejected' }] }),
      })

    await expect(createDefaultLLMConfig(models, fetcher)).rejects.toThrow('Default profile rejected')
  })
})

describe('LLMWizard', () => {
  it('collects every required Assistant connection field before saving', async () => {
    const onComplete = vi.fn().mockResolvedValue(true)
    const user = userEvent.setup()
    render(
      <LLMWizard
        profiles={[{ profile_id: 'local', name: 'Local' }]}
        availableModels={[]}
        onComplete={onComplete}
        onCancel={() => {}}
      />,
    )

    await user.click(screen.getByRole('button', { name: /Assistant/ }))
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByRole('heading', { name: /Step 2: Model/ })

    await user.type(screen.getByLabelText('Model'), 'assistant-model')
    await user.type(screen.getByLabelText('Display Name'), 'Workspace Assistant')
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByRole('heading', { name: /Step 3: Credentials/ })

    expect(screen.queryByRole('button', { name: 'Skip' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText('Workspace hash is required for Assistant')).toBeInTheDocument()

    const fields = {
      'Workspace Hash': 'acme',
      Domain: 'example.com',
      'Auth API URL': 'https://auth.example.com/token',
      'API Token': 'assistant-token',
      'API Secret': 'assistant-secret',
      'Conversations Path': '/api/conversations',
      'Completions Path': '/api/completions',
    }
    for (const [label, value] of Object.entries(fields)) {
      await user.type(screen.getByLabelText(label), value)
    }

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await screen.findByRole('heading', { name: /Step 4: Save/ })
    await user.click(screen.getByRole('button', { name: 'Finish' }))

    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledWith('local', expect.objectContaining({
        provider: 'assistant',
        model: 'assistant-model',
        name: 'Workspace Assistant',
        workspace_hash: 'acme',
        domain: 'example.com',
        api_url: 'https://auth.example.com/token',
        api_token: 'assistant-token',
        api_secret: 'assistant-secret',
        conversations_path: '/api/conversations',
        completions_path: '/api/completions',
      }))
    })
  })
})
