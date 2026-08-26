import { DEFAULT_LOCALE, SUPPORTED_LOCALES, ui, type Locale, type TranslationKey } from "./ui";

// Astro.currentLocale is already computed from the URL's locale prefix by
// Astro's own i18n routing (astro.config.mjs), given a supported locale
// list — this just narrows its type and covers the (never actually
// possible, given that config, but TypeScript doesn't know that) case
// where it's undefined or unrecognized.
export function resolveLocale(currentLocale: string | undefined): Locale {
  if (currentLocale && (SUPPORTED_LOCALES as readonly string[]).includes(currentLocale)) {
    return currentLocale as Locale;
  }
  return DEFAULT_LOCALE;
}

export function useTranslations(locale: Locale) {
  const dict = ui[locale];
  const fallback = ui[DEFAULT_LOCALE];
  return function t(key: TranslationKey, params?: Record<string, string | number>): string {
    let text = dict[key] ?? fallback[key] ?? key;
    if (params) {
      for (const [name, value] of Object.entries(params)) {
        text = text.replaceAll(`{${name}}`, String(value));
      }
    }
    return text;
  };
}
