import { Routes, Route, NavLink } from "react-router-dom";
import Chat from "./pages/Chat";
import Config from "./pages/Config";

export default function App() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <nav
        style={{
          display: "flex",
          gap: "1rem",
          padding: "0.75rem 1.5rem",
          borderBottom: "1px solid var(--color-border)",
          backgroundColor: "var(--color-surface)",
        }}
      >
        <strong style={{ marginRight: "auto" }}>Netherbrain</strong>
        <NavLink to="/">Chat</NavLink>
        <NavLink to="/config">Config</NavLink>
      </nav>

      <main style={{ flex: 1, overflow: "auto" }}>
        <Routes>
          <Route path="/" element={<Chat />} />
          <Route path="/config" element={<Config />} />
        </Routes>
      </main>
    </div>
  );
}
