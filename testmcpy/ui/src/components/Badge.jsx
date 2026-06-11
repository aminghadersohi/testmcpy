import React from 'react'

const VARIANTS = {
  primary: 'bg-primary/10 text-primary border-primary/20',
  success: 'bg-success/10 text-success border-success/20',
  warning: 'bg-warning/10 text-warning border-warning/20',
  error: 'bg-error/10 text-error border-error/20',
  neutral: 'bg-surface text-text-tertiary border-border',
}

const SIZES = {
  xs: 'text-[10px] px-1.5 py-0.5',
  sm: 'text-xs px-2 py-0.5',
}

/**
 * Small chip/badge for counts, statuses, and labels.
 * Replaces the repeated `bg-{color}/10 text-{color} px-2 py-0.5 rounded border border-{color}/20` pattern.
 */
function Badge({ variant = 'neutral', size = 'sm', className = '', children, ...rest }) {
  const variantClasses = VARIANTS[variant] || VARIANTS.neutral
  const sizeClasses = SIZES[size] || SIZES.sm
  return (
    <span
      className={`inline-flex items-center gap-1 rounded border ${variantClasses} ${sizeClasses}${className ? ` ${className}` : ''}`}
      {...rest}
    >
      {children}
    </span>
  )
}

export default Badge
