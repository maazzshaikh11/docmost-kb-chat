import React, { createContext, useContext } from "react";
import {
  useKbChatStore,
  type UseKbChatStore,
} from "../hooks/use-kb-chat-store";

// ── Context ────────────────────────────────────────────────────────────────────

const KbChatStoreContext = createContext<UseKbChatStore | null>(null);

export function KbChatStoreProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const store = useKbChatStore();
  return (
    <KbChatStoreContext.Provider value={store}>
      {children}
    </KbChatStoreContext.Provider>
  );
}

export function useKbChatStoreContext(): UseKbChatStore {
  const ctx = useContext(KbChatStoreContext);
  if (!ctx) {
    throw new Error(
      "useKbChatStoreContext must be used within KbChatStoreProvider",
    );
  }
  return ctx;
}
