/**
 * Shared utilities for the Files feature.
 *
 * Centralises file-type detection, language mapping, and formatting
 * so that the store, tree panel, and preview panel stay in sync.
 */

// ---------------------------------------------------------------------------
// File type detection
// ---------------------------------------------------------------------------

const TEXT_EXTENSIONS = new Set([
  ".txt",
  ".md",
  ".py",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
  ".json",
  ".yaml",
  ".yml",
  ".toml",
  ".sh",
  ".css",
  ".scss",
  ".less",
  ".html",
  ".xml",
  ".sql",
  ".rs",
  ".go",
  ".java",
  ".c",
  ".cpp",
  ".h",
  ".hpp",
  ".rb",
  ".php",
  ".swift",
  ".kt",
  ".env",
  ".cfg",
  ".ini",
  ".log",
  ".csv",
  ".gitignore",
  ".dockerignore",
  ".editorconfig",
  ".prettierrc",
]);

const IMAGE_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".svg",
  ".webp",
  ".ico",
  ".bmp",
]);

const SPECIAL_FILENAMES = new Set(["Makefile", "Dockerfile", "Containerfile"]);

export function isTextFile(name: string): boolean {
  if (SPECIAL_FILENAMES.has(name)) return true;
  const dot = name.lastIndexOf(".");
  if (dot === -1) return false;
  return TEXT_EXTENSIONS.has(name.slice(dot).toLowerCase());
}

export function isImageFile(name: string): boolean {
  const dot = name.lastIndexOf(".");
  if (dot === -1) return false;
  return IMAGE_EXTENSIONS.has(name.slice(dot).toLowerCase());
}

/** Whether the file content should be fetched via readFile (text-based). */
export function shouldReadContent(filePath: string): boolean {
  const name = filePath.split("/").pop() ?? filePath;
  return isTextFile(name);
}

// ---------------------------------------------------------------------------
// Shiki language mapping
// ---------------------------------------------------------------------------

const EXT_TO_LANG: Record<string, string> = {
  ".py": "python",
  ".js": "javascript",
  ".ts": "typescript",
  ".tsx": "tsx",
  ".jsx": "jsx",
  ".json": "json",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".toml": "toml",
  ".sh": "bash",
  ".bash": "bash",
  ".zsh": "bash",
  ".css": "css",
  ".scss": "scss",
  ".less": "less",
  ".html": "html",
  ".xml": "xml",
  ".sql": "sql",
  ".rs": "rust",
  ".go": "go",
  ".java": "java",
  ".c": "c",
  ".cpp": "cpp",
  ".h": "c",
  ".hpp": "cpp",
  ".rb": "ruby",
  ".php": "php",
  ".swift": "swift",
  ".kt": "kotlin",
  ".md": "markdown",
  ".txt": "text",
  ".log": "text",
  ".csv": "csv",
  ".env": "shell",
  ".cfg": "ini",
  ".ini": "ini",
  ".gitignore": "text",
  ".dockerignore": "text",
  ".editorconfig": "ini",
  ".prettierrc": "json",
};

const SPECIAL_FILENAME_LANG: Record<string, string> = {
  Makefile: "makefile",
  Dockerfile: "dockerfile",
  Containerfile: "dockerfile",
};

/** Detect Shiki language identifier for a given filename. */
export function detectLanguage(name: string): string {
  const special = SPECIAL_FILENAME_LANG[name];
  if (special) return special;
  const dot = name.lastIndexOf(".");
  if (dot === -1) return "text";
  return EXT_TO_LANG[name.slice(dot).toLowerCase()] ?? "text";
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
