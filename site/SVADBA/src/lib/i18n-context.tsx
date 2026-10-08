"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { translations, type Lang, type TranslationKey } from "@/lib/i18n";

type I18nContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggle: () => void;
  t: (key: TranslationKey) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);
const STORAGE_KEY = "wedding-lang";

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ru");

  useEffect(() => {
    // Read stored preference inside rAF to stay lint-safe (no sync setState
    // in effect body) and to avoid SSR/CSR hydration mismatch.
    const raf = requestAnimationFrame(() => {
      try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        if (stored === "en" || stored === "ru") {
          setLangState(stored);
        }
      } catch {
        /* ignore */
      }
      document.documentElement.lang = lang;
    });
    return () => cancelAnimationFrame(raf);
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
    if (typeof document !== "undefined") {
      document.documentElement.lang = l;
    }
  }, []);

  const toggle = useCallback(() => {
    setLang(lang === "ru" ? "en" : "ru");
  }, [lang, setLang]);

  const t = useCallback(
    (key: TranslationKey) => {
      const dict = translations[lang] ?? translations.ru;
      return dict[key] ?? translations.ru[key] ?? key;
    },
    [lang]
  );

  const value = useMemo(
    () => ({ lang, setLang, toggle, t }),
    [lang, setLang, toggle, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    // Fallback (e.g. if a component is rendered outside the provider in tests)
    return {
      lang: "ru" as Lang,
      setLang: () => {},
      toggle: () => {},
      t: (key: TranslationKey) => translations.ru[key] ?? key,
    };
  }
  return ctx;
}
