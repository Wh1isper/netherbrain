/**
 * TerminalPanel -- interactive shell via xterm.js + WebSocket.
 *
 * Connects to `WS /api/shell/{projectId}/connect?token=...` and provides
 * a full PTY session. Dark background regardless of theme.
 *
 * Protocol:
 *   Binary frames: raw PTY I/O (keystrokes in, terminal output out).
 *   Text frames (JSON): control messages (resize out, exit in).
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { RotateCw, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getAuthToken } from "@/api/client";
import "@xterm/xterm/css/xterm.css";

// ---------------------------------------------------------------------------
// Terminal theme (always dark, matching standard terminal aesthetics)
// ---------------------------------------------------------------------------

const TERMINAL_THEME = {
  background: "#1e1e1e",
  foreground: "#d4d4d4",
  cursor: "#d4d4d4",
  cursorAccent: "#1e1e1e",
  selectionBackground: "#264f78",
  selectionForeground: "#ffffff",
  black: "#1e1e1e",
  red: "#f44747",
  green: "#6a9955",
  yellow: "#d7ba7d",
  blue: "#569cd6",
  magenta: "#c586c0",
  cyan: "#4ec9b0",
  white: "#d4d4d4",
  brightBlack: "#808080",
  brightRed: "#f44747",
  brightGreen: "#6a9955",
  brightYellow: "#d7ba7d",
  brightBlue: "#569cd6",
  brightMagenta: "#c586c0",
  brightCyan: "#4ec9b0",
  brightWhite: "#ffffff",
};

// ---------------------------------------------------------------------------
// Connection states
// ---------------------------------------------------------------------------

type ConnectionStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

interface TerminalPanelProps {
  projectId: string;
  visible: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TerminalPanel({ projectId, visible }: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("idle");

  // Build WebSocket URL based on current location.
  const getWsUrl = useCallback(() => {
    const token = getAuthToken();
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    return `${proto}//${host}/api/shell/${projectId}/connect?token=${token ?? ""}`;
  }, [projectId]);

  // Send resize control frame.
  const sendResize = useCallback((cols: number, rows: number) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "resize", cols, rows }));
    }
  }, []);

  // Connect to the shell WebSocket.
  const connect = useCallback(() => {
    const term = terminalRef.current;
    if (!term) return;

    // Close any existing connection.
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setStatus("connecting");
    term.clear();
    term.writeln("\x1b[2m--- Connecting... ---\x1b[0m");

    const ws = new WebSocket(getWsUrl());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      term.clear();
      // Send initial size.
      const fit = fitAddonRef.current;
      if (fit) {
        fit.fit();
        sendResize(term.cols, term.rows);
      }
    };

    ws.onmessage = (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer) {
        // Binary frame: PTY output.
        term.write(new Uint8Array(event.data));
      } else if (typeof event.data === "string") {
        // Text frame: control message.
        try {
          const msg = JSON.parse(event.data) as { type: string; code?: number; error?: string };
          if (msg.type === "exit") {
            const code = msg.code ?? -1;
            term.writeln("");
            term.writeln(`\x1b[2m--- Process exited (code ${code}) ---\x1b[0m`);
            setStatus("disconnected");
          }
        } catch {
          // Ignore malformed JSON.
        }
      }
    };

    ws.onclose = () => {
      if (status !== "disconnected") {
        setStatus("disconnected");
      }
    };

    ws.onerror = () => {
      setStatus("error");
    };
  }, [getWsUrl, sendResize, status]);

  // Initialize terminal instance (once).
  useEffect(() => {
    if (!containerRef.current || terminalRef.current) return;

    const term = new Terminal({
      theme: TERMINAL_THEME,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 1000,
      allowProposedApi: true,
    });

    const fitAddon = new FitAddon();
    const webLinksAddon = new WebLinksAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(webLinksAddon);
    term.open(containerRef.current);

    terminalRef.current = term;
    fitAddonRef.current = fitAddon;

    // Forward user input to WebSocket as binary.
    term.onData((data: string) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    });

    // Handle binary input (paste).
    term.onBinary((data: string) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        const bytes = new Uint8Array(data.length);
        for (let i = 0; i < data.length; i++) {
          bytes[i] = data.charCodeAt(i);
        }
        ws.send(bytes);
      }
    });

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
      term.dispose();
      terminalRef.current = null;
      fitAddonRef.current = null;
    };
  }, []);

  // Auto-connect on first visible.
  useEffect(() => {
    if (visible && terminalRef.current && status === "idle") {
      connect();
    }
  }, [visible, status, connect]);

  // Fit terminal when visibility or container size changes.
  useEffect(() => {
    if (!visible) return;

    const fit = fitAddonRef.current;
    const term = terminalRef.current;
    if (!fit || !term) return;

    // Defer fit to next frame (container must have dimensions).
    const raf = requestAnimationFrame(() => {
      fit.fit();
      sendResize(term.cols, term.rows);
    });

    // ResizeObserver for ongoing resize (drag handle, window resize).
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(() => {
      fit.fit();
      sendResize(term.cols, term.rows);
    });
    observer.observe(container);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [visible, sendResize]);

  const isDisconnected = status === "disconnected" || status === "error";

  return (
    <div className="relative flex flex-col h-full w-full bg-[#1e1e1e] overflow-hidden">
      {/* Terminal container */}
      <div
        ref={containerRef}
        className="flex-1 min-h-0 px-1 py-1"
        style={{ display: visible ? "block" : "none" }}
      />

      {/* Connection status overlay */}
      {isDisconnected && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
          <div className="flex flex-col items-center gap-3">
            <WifiOff className="h-8 w-8 text-zinc-400" />
            <p className="text-sm text-zinc-400">
              {status === "error" ? "Connection failed" : "Disconnected"}
            </p>
            <Button
              size="sm"
              variant="outline"
              className="rounded-xl border-zinc-600 text-zinc-300 hover:text-white hover:bg-zinc-700"
              onClick={connect}
            >
              <RotateCw className="h-3.5 w-3.5 mr-1.5" />
              Reconnect
            </Button>
          </div>
        </div>
      )}

      {status === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#1e1e1e] z-10">
          <p className="text-sm text-zinc-500 animate-pulse">Connecting...</p>
        </div>
      )}
    </div>
  );
}
