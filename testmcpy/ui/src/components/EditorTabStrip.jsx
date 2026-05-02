import React from 'react'
import { FileText, X } from 'lucide-react'

/**
 * Chrome-style tab strip that sits above the editor.
 *
 * For now this hosts a single tab driven by `selectedFile`. It exists as
 * its own component so multi-file tabs can slot in later without touching
 * TestManager's layout.
 */
export default function EditorTabStrip({
  filename,
  pathSubtitle,
  testCount = 0,
  dirty = false,
  onClose,
  rightSlot = null,
}) {
  return (
    <div className="flex-shrink-0 flex items-stretch border-b border-border bg-surface">
      <div
        className="group relative flex items-center gap-2 px-3 h-9 bg-surface-elevated border-r border-border max-w-md"
        title={pathSubtitle || filename}
      >
        {/* Active-tab underline */}
        <span className="absolute inset-x-0 top-0 h-0.5 bg-primary" />

        <FileText size={14} className="text-primary flex-shrink-0" />
        <span className="text-sm font-medium text-text-primary truncate">{filename}</span>
        {dirty && (
          <span
            className="w-1.5 h-1.5 rounded-full bg-warning flex-shrink-0"
            title="Unsaved changes"
          />
        )}
        {testCount > 0 && (
          <span className="px-1.5 py-0.5 text-[10px] rounded bg-surface text-text-tertiary border border-border flex-shrink-0">
            {testCount}
          </span>
        )}
        {onClose && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onClose()
            }}
            className="p-0.5 rounded text-text-disabled opacity-0 group-hover:opacity-100 hover:text-text-primary hover:bg-surface-hover transition"
            title="Close file"
          >
            <X size={12} />
          </button>
        )}
      </div>

      <div className="flex-1" />

      {rightSlot && <div className="flex items-center gap-2 px-3">{rightSlot}</div>}
    </div>
  )
}
