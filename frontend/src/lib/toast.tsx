"use client"

import type { ReactNode } from "react"
import { toast as sonnerToast } from "sonner"

/**
 * Drop-in replacement for sonner's `toast`. Every notification renders as the
 * same card — a solid accent icon disc, a bold title and an optional muted
 * subtitle — auto dismissing after 3s (no close button). Import `toast` from
 * here instead of from "sonner"; the `toast.success / error / info(message)`
 * API is unchanged. Card styling lives in the `.toast-*` classes in globals.css.
 */

type Variant = "success" | "error" | "info"
type Opts = { description?: ReactNode; duration?: number }

function VariantIcon({ variant }: { variant: Variant }) {
  if (variant === "success") {
    return (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="toast-icon"
        aria-hidden="true"
      >
        <path d="M5 12.5l4.4 4.4L19 7.6" />
      </svg>
    )
  }
  if (variant === "error") {
    return (
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.6}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="toast-icon"
        aria-hidden="true"
      >
        <path d="M7 7l10 10M17 7L7 17" />
      </svg>
    )
  }
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="toast-icon"
      aria-hidden="true"
    >
      <path d="M12 11.4v5" />
      <path d="M12 7.4h.01" />
    </svg>
  )
}

function ToastCard({
  variant,
  title,
  description,
}: {
  variant: Variant
  title: ReactNode
  description?: ReactNode
}) {
  return (
    <div
      className={`toast-card toast-card--${variant}`}
      role={variant === "error" ? "alert" : "status"}
    >
      <span className="toast-icon-container">
        <VariantIcon variant={variant} />
      </span>
      <div className="toast-text">
        <p className="toast-title">{title}</p>
        {description ? <p className="toast-sub">{description}</p> : null}
      </div>
    </div>
  )
}

function show(variant: Variant, title: ReactNode, opts?: Opts) {
  return sonnerToast.custom(
    () => (
      <ToastCard variant={variant} title={title} description={opts?.description} />
    ),
    { duration: opts?.duration ?? 3000, unstyled: true }
  )
}

export const toast = {
  success: (title: ReactNode, opts?: Opts) => show("success", title, opts),
  error: (title: ReactNode, opts?: Opts) => show("error", title, opts),
  info: (title: ReactNode, opts?: Opts) => show("info", title, opts),
  dismiss: sonnerToast.dismiss,
}
