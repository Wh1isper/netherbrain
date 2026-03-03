import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { WorkspaceResponse, ConversationResponse } from "../api/types";
import { setAuthToken } from "../api/client";

interface AppState {
  // Auth
  authToken: string | null;
  setAuthToken: (token: string | null) => void;

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
      setAuthToken: (token) => {
        setAuthToken(token);
        set({ authToken: token });
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

      // Sidebar
      sidebarOpen: true,
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
    }),
    {
      name: "netherbrain-app",
      partialize: (state) => ({
        authToken: state.authToken,
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
