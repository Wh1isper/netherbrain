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
  conversationsHasMore: boolean;
  conversationsLoading: boolean;
  setConversations: (convs: ConversationResponse[], hasMore?: boolean) => void;
  appendConversations: (convs: ConversationResponse[], hasMore: boolean) => void;
  updateConversationInList: (id: string, patch: Partial<ConversationResponse>) => void;
  removeConversationFromList: (id: string) => void;

  // Presets (global)
  presets: PresetResponse[];
  setPresets: (presets: PresetResponse[]) => void;

  // Sidebar collapse (desktop)
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;

  // Mobile sidebar sheet
  mobileSidebarOpen: boolean;
  setMobileSidebarOpen: (open: boolean) => void;
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
      conversationsHasMore: false,
      conversationsLoading: false,
      setConversations: (convs, hasMore) =>
        set({ conversations: convs, conversationsHasMore: hasMore ?? false }),
      appendConversations: (convs, hasMore) =>
        set((state) => ({
          conversations: [...state.conversations, ...convs],
          conversationsHasMore: hasMore,
        })),
      updateConversationInList: (id, patch) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.conversation_id === id ? { ...c, ...patch } : c,
          ),
        })),
      removeConversationFromList: (id) =>
        set((state) => ({
          conversations: state.conversations.filter((c) => c.conversation_id !== id),
        })),

      // Presets
      presets: [],
      setPresets: (presets) => set({ presets }),

      // Sidebar
      sidebarOpen: true,
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),

      // Mobile sidebar
      mobileSidebarOpen: false,
      setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
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
