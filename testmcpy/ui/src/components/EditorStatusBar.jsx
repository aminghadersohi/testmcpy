import React from 'react'
import { Lock, Pencil, WrapText, Map } from 'lucide-react'

function ToggleChip({ active, onClick, title, icon, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide transition-colors ${
        active
          ? 'bg-primary/15 text-primary'
          : 'bg-surface text-text-disabled hover:text-text-secondary'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

/**
 * IDE-style status bar that sits flush under the Monaco editor.
 *
 * Shows cursor position, language, edit/read-only mode, an
 * unsaved-changes dot, and view toggles (word-wrap, minimap).
 */
export default function EditorStatusBar({
  line = 1,
  column = 1,
  language = 'YAML',
  editMode = false,
  dirty = false,
  wordWrap = false,
  onToggleWordWrap,
  minimap = false,
  onToggleMinimap,
  rightSlot = null,
}) {
  return (
    <div className="flex-shrink-0 h-6 px-3 flex items-center gap-3 text-[11px] bg-surface-elevated border-t border-border text-text-tertiary select-none">
      {/* Mode badge */}
      <span
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded uppercase tracking-wide font-semibold text-[10px] ${
          editMode
            ? 'bg-warning/15 text-warning-light'
            : 'bg-surface text-text-disabled'
        }`}
        title={editMode ? 'Editor is editable' : 'Editor is read-only'}
      >
        {editMode ? <Pencil size={10} /> : <Lock size={10} />}
        {editMode ? 'Edit' : 'Read-only'}
      </span>

      {/* Dirty dot — only meaningful while editing */}
      {editMode && dirty && (
        <span
          className="inline-flex items-center gap-1 text-warning-light"
          title="Unsaved changes"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-warning" />
          Unsaved
        </span>
      )}

      <span className="flex-1" />

      {onToggleWordWrap && (
        <ToggleChip
          active={wordWrap}
          onClick={onToggleWordWrap}
          title={wordWrap ? 'Disable word wrap' : 'Enable word wrap'}
          icon={<WrapText size={10} />}
          label="Wrap"
        />
      )}
      {onToggleMinimap && (
        <ToggleChip
          active={minimap}
          onClick={onToggleMinimap}
          title={minimap ? 'Hide minimap' : 'Show minimap'}
          icon={<Map size={10} />}
          label="Map"
        />
      )}

      {rightSlot}

      <span className="font-mono">
        Ln {line}, Col {column}
      </span>
      <span className="font-mono uppercase text-text-disabled">{language}</span>
    </div>
  )
}
