import { useEffect, useState } from "react";
import { Routes, Route } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Sidebar from "@/components/layout/Sidebar";
import Chat from "@/pages/Chat";
import Settings from "@/pages/Settings";
import { useAppStore } from "@/stores/app";
import { setAuthToken, api, ApiError } from "@/api/client";

// -- Auth gate ---------------------------------------------------------------

function AuthGate({ onAuth }: { onAuth: (token: string) => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    try {
      setAuthToken(value.trim());
      // Validate token against a protected endpoint (health is auth-exempt)
      await api.get("/api/presets/list");
      onAuth(value.trim());
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setError("Invalid token. Please try again.");
      } else {
        setError("Could not reach the server.");
      }
      setAuthToken(null);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 p-8 rounded-lg border border-border bg-card shadow-sm">
        <div className="space-y-1">
          <h1 className="text-xl font-semibold text-foreground">Netherbrain</h1>
          <p className="text-sm text-muted-foreground">Enter your API token to continue.</p>
        </div>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
          <Input
            type="password"
            placeholder="Bearer token"
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              setError("");
            }}
            autoFocus
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={!value.trim()}>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}

// -- App shell ---------------------------------------------------------------

function AppShell() {
  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Chat />} />
          <Route path="/c/:id" element={<Chat />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

// -- Root --------------------------------------------------------------------

export default function App() {
  const { theme, authToken, setAuthToken: storeSetAuthToken } = useAppStore();

  // Sync theme to <html> class
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  const handleAuth = (token: string) => {
    storeSetAuthToken(token);
  };

  return (
    <TooltipProvider>{authToken ? <AppShell /> : <AuthGate onAuth={handleAuth} />}</TooltipProvider>
  );
}
