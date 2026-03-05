/**
 * Lazy-loaded Shiki highlighter singleton.
 *
 * Creates a single shared highlighter instance with commonly used
 * languages and themes. Dynamically loads additional languages on demand.
 */

import { createHighlighter, type Highlighter } from "shiki";

let instance: Highlighter | null = null;
let loading: Promise<Highlighter> | null = null;

const PRELOADED_LANGS = [
  "typescript",
  "javascript",
  "python",
  "bash",
  "json",
  "yaml",
  "html",
  "css",
  "markdown",
  "tsx",
  "jsx",
  "sql",
  "shell",
];

/* Warm themes that complement the earthy design system */
const THEMES = ["vitesse-dark", "vitesse-light"] as const;

export async function getHighlighter(): Promise<Highlighter> {
  if (instance) return instance;
  if (loading) return loading;

  loading = createHighlighter({
    themes: [...THEMES],
    langs: PRELOADED_LANGS,
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
      try {
        await highlighter.loadLanguage(lang as never);
      } catch {
        // Language not available in Shiki -- fall back to plaintext
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
