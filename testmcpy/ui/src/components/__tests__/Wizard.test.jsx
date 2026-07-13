import React from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import Wizard from '../Wizard'

describe('Wizard', () => {
  it('locks navigation while asynchronous completion is pending', async () => {
    let finishSave
    const save = new Promise(resolve => {
      finishSave = resolve
    })
    const onCancel = vi.fn()

    render(
      <Wizard
        title="Async setup"
        steps={[{ label: 'Save', component: <div>Review</div> }]}
        data={{}}
        setData={vi.fn()}
        onComplete={() => save}
        onCancel={onCancel}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Finish/ }))

    expect(await screen.findByRole('button', { name: /Saving/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByText('Review').closest('[aria-busy]')).toHaveAttribute('aria-busy', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).not.toHaveBeenCalled()

    await act(async () => finishSave(true))
    expect(screen.getByRole('button', { name: /Finish/ })).toBeEnabled()
  })
})
