import { render } from '@testing-library/react'
import { describe, it } from 'vitest'
import OutputDiff from '../OutputDiff'

describe('OutputDiff', () => {
  it('renders without crashing', () => {
    render(<OutputDiff textA="hello" textB="world" />)
  })

  it('handles identical strings', () => {
    render(<OutputDiff textA="same" textB="same" />)
  })

  it('handles empty strings', () => {
    render(<OutputDiff textA="" textB="" />)
  })
})
