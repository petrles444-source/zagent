"use client"

import * as React from "react"
import { Keyboard } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

interface ShortcutHelpProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface Shortcut {
  keys: string[]
  action: string
  group: string
}

const SHORTCUTS: Shortcut[] = [
  { keys: ["/"], action: "Focus the search box", group: "Search" },
  { keys: ["Esc"], action: "Clear search / close dialog", group: "Search" },
  { keys: ["→", "↓"], action: "Move focus to the next effect", group: "Navigate" },
  { keys: ["←", "↑"], action: "Move focus to the previous effect", group: "Navigate" },
  { keys: ["Enter"], action: "Open the focused effect", group: "Navigate" },
  { keys: ["←", "→"], action: "Previous / next effect (inside dialog)", group: "Dialog" },
  { keys: ["Esc"], action: "Close the detail dialog", group: "Dialog" },
  { keys: ["?"], action: "Open this shortcut cheatsheet", group: "Help" },
]

export function ShortcutHelp({ open, onOpenChange }: ShortcutHelpProps) {
  // Group shortcuts by their group field.
  const groups = React.useMemo(() => {
    const map = new Map<string, Shortcut[]>()
    for (const s of SHORTCUTS) {
      if (!map.has(s.group)) map.set(s.group, [])
      map.get(s.group)!.push(s)
    }
    return Array.from(map.entries())
  }, [])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md gap-0 overflow-hidden p-0 sm:max-w-md">
        <DialogHeader className="border-b border-border px-6 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Keyboard className="h-4 w-4" />
            </span>
            <div>
              <DialogTitle className="text-lg">Keyboard Shortcuts</DialogTitle>
              <DialogDescription className="text-xs">
                Press <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px]">?</kbd> anywhere to open this.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto scroll-thin px-6 py-4">
          {groups.map(([group, items]) => (
            <div key={group} className="mb-5 last:mb-0">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                {group}
              </h3>
              <ul className="space-y-1.5">
                {items.map((s, i) => (
                  <li
                    key={`${s.action}-${i}`}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span className="text-foreground/90">{s.action}</span>
                    <span className="flex shrink-0 items-center gap-1">
                      {s.keys.map((k, j) => (
                        <kbd
                          key={`${k}-${j}`}
                          className="min-w-6 rounded border border-border bg-muted px-1.5 py-0.5 text-center font-mono text-[11px] font-medium text-foreground"
                        >
                          {k}
                        </kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
