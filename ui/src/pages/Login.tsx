import { useState } from "react";
import { Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAppStore } from "@/stores/app";
import { login } from "@/api/auth";
import { ApiError } from "@/api/client";

export default function Login() {
  const setAuth = useAppStore((s) => s.setAuth);
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId.trim() || !password) return;

    setLoading(true);
    setError("");

    try {
      const res = await login({ user_id: userId.trim(), password });
      setAuth(res.token, res.user);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) {
          setError("Invalid credentials.");
        } else if (err.status === 403) {
          setError("Account deactivated.");
        } else {
          setError(err.detail || "Login failed.");
        }
      } else {
        setError("Could not reach the server.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 p-8 rounded-2xl border border-border bg-card shadow-md">
        <div className="space-y-2 text-center">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 mx-auto">
            <Bot className="h-5 w-5 text-primary" />
          </div>
          <h1 className="text-xl font-semibold text-foreground">Welcome back</h1>
          <p className="text-sm text-muted-foreground">Sign in to continue.</p>
        </div>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="user-id">User ID</Label>
            <Input
              id="user-id"
              type="text"
              placeholder="alice"
              value={userId}
              onChange={(e) => {
                setUserId(e.target.value);
                setError("");
              }}
              autoFocus
              autoComplete="username"
              className="rounded-xl"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setError("");
              }}
              autoComplete="current-password"
              className="rounded-xl"
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button
            type="submit"
            className="w-full rounded-xl"
            disabled={loading || !userId.trim() || !password}
          >
            {loading ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
