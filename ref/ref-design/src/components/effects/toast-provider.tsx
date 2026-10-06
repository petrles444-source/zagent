"use client"

import * as React from "react"
import { Check, Info, AlertCircle, X } from "lucide-react"
import { cn } from "@/lib/utils"

type ToastVariant = "success" | "info" | "error"

interface ToastItem {
  id: number
  message: string
  variant: ToastVariant
}

interface ToastContextValue {
  show: (message: string, variant?: ToastVariant) => void
}

const ToastContext = React.createContext<ToastContextValue | null>(null)

let counter = 0

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([])

  const show = React.useCallback((message: string, variant: ToastVariant = "success") => {
    const id = ++counter
    setToasts((prev) => [...prev, { id, message, variant }])
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 2200)
  }, [])

  const dismiss = React.useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[100] flex flex-col items-center gap-2 px-4 sm:bottom-6">
        {toasts.map((t) => {
          const Icon =
            t.variant === "success" ? Check : t.variant === "error" ? AlertCircle : Info
          return (
            <div
              key={t.id}
              role="status"
              className="fx-toast-in pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-lg border border-border bg-card/95 px-4 py-3 shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/90"
            >
              <span
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                  t.variant === "success" && "bg-emerald-500/15 text-emerald-500",
                  t.variant === "info" && "bg-primary/15 text-primary",
                  t.variant === "error" && "bg-destructive/15 text-destructive"
                )}
              >
                <Icon className="h-3.5 w-3.5" />
              </span>
              <p className="flex-1 text-sm font-medium text-foreground">
                {t.message}
              </p>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
                className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useFxToast() {
  const ctx = React.useContext(ToastContext)
  if (!ctx) {
    // Provide a no-op fallback so components render during SSR / if missing provider.
    return {
      show: () => {
        // no-op
      },
    }
  }
  return ctx
}
