import { useState, useEffect, useCallback } from "react";

/** Tailwind `md` breakpoint (768px). Below this is considered mobile. */
const MOBILE_BREAKPOINT = 768;

/**
 * Reactive hook that returns true when viewport is below the `md` breakpoint.
 * Uses `matchMedia` for efficient, debounce-free updates.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT,
  );

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}

/**
 * Global keyboard shortcuts hook.
 *
 * Registers document-level keydown handlers for common shortcuts:
 * - Cmd/Ctrl+K: Focus chat input
 * - Cmd/Ctrl+Shift+N: New chat
 * - Escape: Close panels (handled by individual components)
 */
export function useGlobalShortcuts({
  onNewChat,
  onFocusInput,
}: {
  onNewChat?: () => void;
  onFocusInput?: () => void;
}) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;

      // Don't capture when typing in input/textarea
      const tag = (e.target as HTMLElement)?.tagName;
      const isEditable =
        tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable;

      // Cmd/Ctrl+K: focus input (always, even in editable)
      if (mod && e.key === "k") {
        e.preventDefault();
        onFocusInput?.();
        return;
      }

      if (isEditable) return;

      // Cmd/Ctrl+Shift+N: new chat
      if (mod && e.shiftKey && e.key === "N") {
        e.preventDefault();
        onNewChat?.();
      }
    },
    [onNewChat, onFocusInput],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);
}
