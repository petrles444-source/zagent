"use client"

import * as React from "react"
import { Check, Copy } from "lucide-react"
import { cn } from "@/lib/utils"

interface CodeBlockProps {
  code: string
  language?: string
  className?: string
  /** Code color theme; defaults to dark. */
  theme?: "dark" | "light"
}

/** Very small, dependency-free CSS/HTML syntax highlighter. */
function highlight(source: string, language: string) {
  // Escape HTML first
  let html = source
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")

  if (language === "css") {
    // Comments
    html = html.replace(/(\/\*[\s\S]*?\*\/)/g, '<span class="tok-comment">$1</span>')
    // At-rules / keyframes names
    html = html.replace(/(@[\w-]+)/g, '<span class="tok-atrule">$1</span>')
    // Selectors before {
    html = html.replace(
      /^([^{}\n]*?)(\s*\{)/gm,
      '<span class="tok-selector">$1</span>$2'
    )
    // Properties: value;
    html = html.replace(
      /([\w-]+)(\s*:\s*)([^;{}\n]+)(;?)/g,
      '<span class="tok-prop">$1</span>$2<span class="tok-value">$3</span>$4'
    )
    // Keyframe percentages
    html = html.replace(
      /(\b\d+%|from|to)(\s*\{)/g,
      '<span class="tok-keyword">$1</span>$2'
    )
  } else if (language === "html") {
    // Tags
    html = html.replace(
      /(&lt;\/?)([\w-]+)/g,
      '$1<span class="tok-tag">$2</span>'
    )
    // Attributes
    html = html.replace(
      /([\w-]+)(=)(&quot;|")/g,
      '<span class="tok-attr">$1</span>$2$3'
    )
  }
  return html
}

export function CodeBlock({ code, language = "css", className, theme = "dark" }: CodeBlockProps) {
  const [copied, setCopied] = React.useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      // ignore
    }
  }

  const highlighted = React.useMemo(
    () => highlight(code, language),
    [code, language]
  )

  const isLight = theme === "light"

  return (
    <div className={cn("group relative", className)}>
      <button
        type="button"
        onClick={handleCopy}
        className="absolute right-2 top-2 z-10 inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-background/80 px-2.5 py-1.5 text-xs font-medium text-foreground/80 opacity-0 backdrop-blur transition hover:bg-background hover:text-foreground group-hover:opacity-100 focus:opacity-100"
        aria-label="Copy code"
      >
        {copied ? (
          <>
            <Check className="h-3.5 w-3.5 text-emerald-500" />
            Copied
          </>
        ) : (
          <>
            <Copy className="h-3.5 w-3.5" />
            Copy
          </>
        )}
      </button>
      <pre
        className={cn(
          "overflow-x-auto rounded-lg p-4 text-[12.5px] leading-relaxed",
          isLight ? "code-light" : "bg-[#0d1117]"
        )}
      >
        <code
          className={cn("font-mono", isLight ? "" : "text-[#e6edf3]")}
          dangerouslySetInnerHTML={{ __html: highlighted }}
        />
      </pre>
    </div>
  )
}
