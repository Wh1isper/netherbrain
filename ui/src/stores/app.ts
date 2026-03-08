import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  WorkspaceResponse,
  ConversationResponse,
  UserResponse,
  PresetResponse,
} from "../api/types";
import { setAuthToken, setOnUnauthorized } from "../api/client";

interface AppState {
  // Auth
  authToken: string | null;
  user: UserResponse | null;
  setAuth: (token: string, user: UserResponse) => void;
  setUser: (user: UserResponse) => void;
  logout: () => void;

  // Theme
  theme: "light" | "dark";
  toggleTheme: () => void;

  // Current workspace
  currentWorkspaceId: string | null;
  workspaces: WorkspaceResponse[];
  setCurrentWorkspace: (id: string) => void;
  setWorkspaces: (ws: WorkspaceResponse[]) => void;

  // Conversations for the current workspace
  conversations: ConversationResponse[];
  setConversations: (convs: ConversationResponse[]) => void;
  updateConversationInList: (id: string, patch: Partial<ConversationResponse>) => void;

  // Presets (global)
  presets: PresetResponse[];
  setPresets: (presets: PresetResponse[]) => void;

  // Sidebar collapse
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // Auth
      authToken: null,
      user: null,
      setAuth: (token, user) => {
        setAuthToken(token);
        set({ authToken: token, user });
      },
      setUser: (user) => set({ user }),
      logout: () => {
        setAuthToken(null);
        set({ authToken: null, user: null });
      },

      // Theme
      theme: "dark",
      toggleTheme: () => set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" })),

      // Workspace
      currentWorkspaceId: null,
      workspaces: [],
      setCurrentWorkspace: (id) => set({ currentWorkspaceId: id }),
      setWorkspaces: (ws) => set({ workspaces: ws }),

      // Conversations
      conversations: [],
      setConversations: (convs) => set({ conversations: convs }),
      updateConversationInList: (id, patch) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.conversation_id === id ? { ...c, ...patch } : c,
          ),
        })),

      // Presets
      presets: [],
      setPresets: (presets) => set({ presets }),

      // Sidebar
      sidebarOpen: true,
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
    }),
    {
      name: "netherbrain-app",
      partialize: (state) => ({
        authToken: state.authToken,
        user: state.user,
        theme: state.theme,
        currentWorkspaceId: state.currentWorkspaceId,
        sidebarOpen: state.sidebarOpen,
      }),
      onRehydrateStorage: () => (state) => {
        // Sync persisted token into the API client on rehydration
        if (state?.authToken) {
          setAuthToken(state.authToken);
        }
      },
    },
  ),
);

// Wire up the global 401 handler to logout.
setOnUnauthorized(() => {
  useAppStore.getState().logout();
});
