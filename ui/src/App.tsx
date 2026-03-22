import { useEffect, useState, lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Sidebar from "@/components/layout/Sidebar";
import ErrorBoundary from "@/components/ErrorBoundary";
import Chat from "@/pages/Chat";
const Settings = lazy(() => import("@/pages/Settings"));
const Files = lazy(() => import("@/pages/Files"));
import Login from "@/pages/Login";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useAppStore } from "@/stores/app";
import { useIsMobile } from "@/lib/hooks";
import { useNotifications } from "@/lib/useNotifications";
import { changePassword, getMe } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Bot, Loader2 } from "lucide-react";

function PageFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}

// -- Force change password (first login) ------------------------------------

function ForceChangePassword() {
  const { user, setAuth, authToken } = useAppStore();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const mismatch = confirmPassword !== "" && newPassword !== confirmPassword;
  const canSubmit =
    oldPassword.length > 0 &&
    newPassword.length >= 8 &&
    newPassword === confirmPassword &&
    !loading;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit || !authToken || !user) return;
    setLoading(true);
    setError("");

    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword });
      setAuth(authToken, { ...user, must_change_password: false });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Current password is incorrect.");
      } else {
        setError("Failed to change password.");
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
          <h1 className="text-xl font-semibold text-foreground">Change Password</h1>
          <p className="text-sm text-muted-foreground">
            Welcome, {user?.display_name}. Please set a new password to continue.
          </p>
        </div>
        <form onSubmit={(e) => void handleSubmit(e)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="current-pw">Current password</Label>
            <Input
              id="current-pw"
              type="password"
              value={oldPassword}
              onChange={(e) => {
                setOldPassword(e.target.value);
                setError("");
              }}
              autoFocus
              autoComplete="current-password"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-pw">New password</Label>
            <Input
              id="new-pw"
              type="password"
              value={newPassword}
              onChange={(e) => {
                setNewPassword(e.target.value);
                setError("");
              }}
              placeholder="At least 8 characters"
              autoComplete="new-password"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm-pw">Confirm new password</Label>
            <Input
              id="confirm-pw"
              type="password"
              value={confirmPassword}
              onChange={(e) => {
                setConfirmPassword(e.target.value);
                setError("");
              }}
              autoComplete="new-password"
            />
            {mismatch && <p className="text-xs text-destructive">Passwords do not match.</p>}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full rounded-xl" disabled={!canSubmit}>
            {loading ? "Saving..." : "Set new password"}
          </Button>
        </form>
      </div>
    </div>
  );
}

// -- App shell (authenticated) -----------------------------------------------

function AppShell() {
  const isMobile = useIsMobile();
  const mobileSidebarOpen = useAppStore((s) => s.mobileSidebarOpen);
  const setMobileSidebarOpen = useAppStore((s) => s.setMobileSidebarOpen);

  // Connect to WebSocket notification channel for real-time updates
  useNotifications();

  const mainContent = (
    <main className="flex-1 overflow-hidden">
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Chat />} />
          <Route path="/c/:id" element={<Chat />} />
          <Route
            path="/settings"
            element={
              <Suspense fallback={<PageFallback />}>
                <Settings />
              </Suspense>
            }
          />
          <Route
            path="/files/:projectId"
            element={
              <Suspense fallback={<PageFallback />}>
                <Files />
              </Suspense>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </main>
  );

  if (isMobile) {
    return (
      <div className="flex h-full overflow-hidden">
        <Sheet open={mobileSidebarOpen} onOpenChange={setMobileSidebarOpen}>
          <SheetContent side="left" className="w-[280px] p-0 gap-0" showCloseButton={false}>
            <Sidebar onNavigate={() => setMobileSidebarOpen(false)} />
          </SheetContent>
        </Sheet>
        {mainContent}
      </div>
    );
  }

  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      {mainContent}
    </div>
  );
}

// -- Root --------------------------------------------------------------------

export default function App() {
  const { theme, authToken, user, setUser } = useAppStore();
  const [verifying, setVerifying] = useState(true);

  // Sync theme to <html> class
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  // Verify token and refresh user data on app load
  useEffect(() => {
    if (!authToken) {
      setVerifying(false);
      return;
    }

    let cancelled = false;
    getMe()
      .then((freshUser) => {
        if (!cancelled) setUser(freshUser);
      })
      .catch(() => {
        // 401 is handled by the global handler (triggers logout).
        // For other errors, keep existing user data and proceed.
      })
      .finally(() => {
        if (!cancelled) setVerifying(false);
      });

    return () => {
      cancelled = true;
    };
  }, [authToken]); // eslint-disable-line react-hooks/exhaustive-deps

  const needsPasswordChange = authToken && user?.must_change_password;

  // Show nothing while verifying token on initial load
  if (verifying && authToken) {
    return null;
  }

  return (
    <TooltipProvider>
      <Toaster theme={theme} position="bottom-right" toastOptions={{ className: "rounded-xl" }} />
      {authToken ? (
        needsPasswordChange ? (
          <ForceChangePassword />
        ) : (
          <AppShell />
        )
      ) : (
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      )}
    </TooltipProvider>
  );
}
