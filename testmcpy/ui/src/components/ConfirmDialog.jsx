import React, { useState, useCallback } from 'react'

// Styled replacement for window.confirm(). Render directly with
// onConfirm/onCancel callbacks, or use the useConfirm() hook below for a
// promise-based `if (!(await confirmAction({...}))) return` flow.
export default function ConfirmDialog({ title, message, confirmLabel = 'Delete', onConfirm, onCancel }) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-0 md:p-4">
      <div className="bg-surface-elevated border border-border rounded-none md:rounded-lg p-6 md:max-w-md w-full h-full md:h-auto max-h-full md:max-h-[90vh] mx-0 md:mx-4 shadow-xl">
        <h3 className="text-lg font-bold mb-2">{title}</h3>
        <p className="text-text-secondary mb-6">{message}</p>
        <div className="flex justify-end gap-3">
          <button onClick={onCancel} className="btn btn-secondary">
            Cancel
          </button>
          <button onClick={onConfirm} className="btn btn-primary bg-error hover:bg-error/80">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

export function useConfirm() {
  const [dialog, setDialog] = useState(null)

  const confirm = useCallback(
    ({ title, message, confirmLabel = 'Delete' }) =>
      new Promise(resolve => {
        setDialog({
          title,
          message,
          confirmLabel,
          onConfirm: () => { setDialog(null); resolve(true) },
          onCancel: () => { setDialog(null); resolve(false) },
        })
      }),
    []
  )

  const confirmElement = dialog ? <ConfirmDialog {...dialog} /> : null
  return [confirm, confirmElement]
}
