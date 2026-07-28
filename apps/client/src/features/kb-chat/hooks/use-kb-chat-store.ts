import { useState, useCallback, useEffect, useRef } from "react";
import type { KbSource } from "../services/kb-chat-service";

// ── Types ──────────────────────────────────────────────────────────────────────

export interface KbMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Sources returned by the backend for this assistant turn; empty for user messages. */
  sources: KbSource[];
}

export interface KbConversation {
  id: string;
  /** First user message, truncated to 80 chars. */
  title: string;
  /** ISO date string of creation. */
  createdAt: string;
  /** ISO date string of last message. */
  updatedAt: string;
  messages: KbMessage[];
}

// ── Constants ──────────────────────────────────────────────────────────────────

const STORAGE_KEY = "kb-chat-conversations";
const MAX_CONVERSATIONS = 100;

// ── Utilities ──────────────────────────────────────────────────────────────────

function generateId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function loadFromStorage(): KbConversation[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as KbConversation[];
  } catch {
    return [];
  }
}

function saveToStorage(conversations: KbConversation[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
  } catch {
    // localStorage quota exceeded — silently ignore
  }
}

// ── Hook ───────────────────────────────────────────────────────────────────────

export interface UseKbChatStore {
  conversations: KbConversation[];
  activeConversationId: string | null;
  activeConversation: KbConversation | undefined;
  setActiveConversationId: (id: string | null) => void;
  /** Creates a new empty conversation, sets it active, and returns its id. */
  createConversation: () => string;
  /** Appends a user message to the active conversation. */
  appendUserMessage: (content: string) => string;
  /** Appends an assistant message (with sources) to the active conversation. */
  appendAssistantMessage: (content: string, sources: KbSource[]) => string;
  /** Deletes a conversation by id. */
  deleteConversation: (id: string) => void;
}

export function useKbChatStore(): UseKbChatStore {
  const [conversations, setConversations] = useState<KbConversation[]>(
    () => loadFromStorage(),
  );
  const [activeConversationId, setActiveConversationId] = useState<
    string | null
  >(null);

  // Persist whenever conversations change (skip initial mount duplication)
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    saveToStorage(conversations);
  }, [conversations]);

  const createConversation = useCallback((): string => {
    const id = generateId();
    const now = new Date().toISOString();
    const newConversation: KbConversation = {
      id,
      title: "New conversation",
      createdAt: now,
      updatedAt: now,
      messages: [],
    };
    setConversations((prev) => {
      const updated = [newConversation, ...prev];
      // Trim to max
      return updated.slice(0, MAX_CONVERSATIONS);
    });
    setActiveConversationId(id);
    return id;
  }, []);

  const appendUserMessage = useCallback(
    (content: string): string => {
      const msgId = generateId();
      const now = new Date().toISOString();
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== activeConversationId) return conv;
          const isFirst = conv.messages.length === 0;
          const title = isFirst ? content.slice(0, 80) : conv.title;
          return {
            ...conv,
            title,
            updatedAt: now,
            messages: [
              ...conv.messages,
              { id: msgId, role: "user" as const, content, sources: [] },
            ],
          };
        }),
      );
      return msgId;
    },
    [activeConversationId],
  );

  const appendAssistantMessage = useCallback(
    (content: string, sources: KbSource[]): string => {
      const msgId = generateId();
      const now = new Date().toISOString();
      setConversations((prev) =>
        prev.map((conv) => {
          if (conv.id !== activeConversationId) return conv;
          return {
            ...conv,
            updatedAt: now,
            messages: [
              ...conv.messages,
              {
                id: msgId,
                role: "assistant" as const,
                content,
                sources,
              },
            ],
          };
        }),
      );
      return msgId;
    },
    [activeConversationId],
  );

  const deleteConversation = useCallback(
    (id: string): void => {
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeConversationId === id) {
        setActiveConversationId(null);
      }
    },
    [activeConversationId],
  );

  const activeConversation = conversations.find(
    (c) => c.id === activeConversationId,
  );

  return {
    conversations,
    activeConversationId,
    activeConversation,
    setActiveConversationId,
    createConversation,
    appendUserMessage,
    appendAssistantMessage,
    deleteConversation,
  };
}
