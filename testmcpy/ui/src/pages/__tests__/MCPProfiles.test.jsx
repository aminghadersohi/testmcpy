import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { buildMCPTestAuth, MCPEditorModal } from '../MCPProfiles'

describe('buildMCPTestAuth', () => {
  it('forwards Skip SSL verification to OAuth auto-discovery tests', () => {
    expect(buildMCPTestAuth({
      auth_type: 'oauth',
      oauth_auto_discover: true,
      insecure: true,
    })).toEqual({
      type: 'oauth',
      oauth_auto_discover: true,
      insecure: true,
    })
  })

  it('treats Skip SSL verification as transport-wide', () => {
    expect(buildMCPTestAuth({ auth_type: 'none', insecure: true })).toEqual({
      type: 'none',
      insecure: true,
    })
  })
})

describe('MCPEditorModal', () => {
  it('reloads persisted OAuth and TLS flags explicitly', () => {
    render(
      <MCPEditorModal
        mcp={{
          name: 'Gateway',
          mcp_url: 'https://mcp.example.test/mcp',
          auth: {
            type: 'oauth',
            client_id: 'previous-registration',
            oauth_auto_discover: true,
            insecure: true,
          },
        }}
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />,
    )

    expect(screen.getByLabelText(/Auto-discover OAuth configuration/)).toBeChecked()
    expect(screen.getByLabelText(/Skip SSL verification/)).toBeChecked()
  })
})
