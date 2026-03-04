import { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import Sidebar from "@/components/layout/Sidebar";
import Chat from "@/pages/Chat";
import Settings from "@/pages/Settings";
import Login from "@/pages/Login";
import { useAppStore } from "@/stores/app";

// -- App shell (authenticated) -----------------------------------------------

function AppShell() {
  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Chat />} />
          <Route path="/c/:id" element={<Chat />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

// -- Root --------------------------------------------------------------------

export default function App() {
  const { theme, authToken } = useAppStore();

  // Sync theme to <html> class
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
  }, [theme]);

  return (
    <TooltipProvider>
      {authToken ? (
        <AppShell />
      ) : (
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      )}
    </TooltipProvider>
  );
}
