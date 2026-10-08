"use client";

import { contentByLang } from "@/lib/wedding-content";
import { useI18n } from "@/lib/i18n-context";

/**
 * Returns the bilingual narrative content (love-story chapters, schedule,
 * FAQ, venue description, couple quotes, closing quote) for the currently
 * selected language.
 */
export function useWeddingContent() {
  const { lang } = useI18n();
  return contentByLang[lang];
}
