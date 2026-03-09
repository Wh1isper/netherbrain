/**
 * Lazy-loaded Shiki highlighter singleton (optimized bundle).
 *
 * Uses `shiki/core` with explicit engine + language/theme imports
 * to avoid bundling all 330+ grammars and 65 themes.
 * Only critical languages are loaded eagerly; others load on demand
 * from `bundledLanguages`.
 */

import { createHighlighterCore, type HighlighterCore } from "shiki/core";
import { createOnigurumaEngine } from "shiki/engine/oniguruma";
import { bundledLanguages } from "shiki/langs";
import { bundledThemes } from "shiki/themes";

let instance: HighlighterCore | null = null;
let loading: Promise<HighlighterCore> | null = null;

/**
 * Languages loaded eagerly at init time.
 * Keep this list minimal -- others are loaded on demand.
 */
const EAGER_LANGS: (keyof typeof bundledLanguages)[] = [
  "typescript",
  "javascript",
  "python",
  "json",
  "bash",
];

const THEMES: (keyof typeof bundledThemes)[] = ["vitesse-dark", "vitesse-light"];

export async function getHighlighter(): Promise<HighlighterCore> {
  if (instance) return instance;
  if (loading) return loading;

  loading = createHighlighterCore({
    engine: createOnigurumaEngine(import("shiki/wasm")),
    themes: THEMES.map((t) => bundledThemes[t]),
    langs: EAGER_LANGS.map((l) => bundledLanguages[l]),
  }).then((h) => {
    instance = h;
    return h;
  });

  return loading;
}

/**
 * Highlight code to HTML. Returns raw HTML string.
 *
 * Falls back to plain `<pre>` if the language is not supported
 * or if the highlighter has not loaded yet.
 */
export async function highlightCode(
  code: string,
  lang: string,
  theme: "dark" | "light" = "dark",
): Promise<string> {
  try {
    const highlighter = await getHighlighter();
    const shikiTheme = theme === "dark" ? "vitesse-dark" : "vitesse-light";

    // Check if language is loaded; if not, try loading it dynamically
    const loadedLangs = highlighter.getLoadedLanguages();
    if (!loadedLangs.includes(lang as never)) {
      const langKey = lang as keyof typeof bundledLanguages;
      if (langKey in bundledLanguages) {
        try {
          await highlighter.loadLanguage(bundledLanguages[langKey]);
        } catch {
          // Language grammar load failed -- fall back to plaintext
          return highlighter.codeToHtml(code, { lang: "text", theme: shikiTheme });
        }
      } else {
        // Unknown language -- render as plaintext
        return highlighter.codeToHtml(code, { lang: "text", theme: shikiTheme });
      }
    }

    return highlighter.codeToHtml(code, { lang, theme: shikiTheme });
  } catch {
    // Highlighter not ready -- return escaped plaintext
    const escaped = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<pre><code>${escaped}</code></pre>`;
  }
}
