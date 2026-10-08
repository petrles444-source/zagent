"use client";

import { I18nProvider } from "@/lib/i18n-context";

/**
 * Client-side wrapper so the I18nProvider (which uses useState/useContext)
 * can wrap the Server-Component layout's children.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return <I18nProvider>{children}</I18nProvider>;
}
