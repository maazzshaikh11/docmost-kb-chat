import { useState, useRef, useEffect, useCallback } from "react";
import {
  Text,
  Textarea,
  ActionIcon,
  Alert,
  Loader,
  Stack,
} from "@mantine/core";
import {
  IconSend,
  IconAlertCircle,
  IconSparkles,
  IconRobotFace,
  IconUser,
  IconFileText,
} from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { sendKbChatMessage } from "../services/kb-chat-service";
import { buildPageUrl } from "@/features/page/page.utils";
import type { KbMessage } from "../hooks/use-kb-chat-store";
import type { KbSource } from "../services/kb-chat-service";
import { useKbChatStoreContext } from "../context/kb-chat-store-context";
import classes from "../styles/kb-chat.module.css";

// ── Constants ──────────────────────────────────────────────────────────────────

const NO_INFO_PHRASES = [
  "don't have enough information",
  "not have enough information",
  "cannot find",
  "no information",
  "don't know",
  "outside my knowledge",
  "i don't have",
  "i do not have",
];

// ── Helpers ────────────────────────────────────────────────────────────────────

function hasNoInfo(answer: string): boolean {
  const lower = answer.toLowerCase();
  return NO_INFO_PHRASES.some((p) => lower.includes(p));
}

/** Very light markdown renderer: bold, italic, inline-code, line breaks, and inline citations. */
function renderMarkdown(text: string, classesObj: Record<string, string>): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\[(\d+)\]/g, `<span class="${classesObj.inlineCitation}" data-citation="$1">[$1]</span>`)
    .replace(/\n/g, "<br/>");
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SourceList({ sources }: { sources: KbSource[] }) {
  const navigate = useNavigate();
  if (sources.length === 0) return null;

  return (
    <div className={classes.sourceList}>
      <Text
        size="xs"
        c="dimmed"
        fw={600}
        tt="uppercase"
        mb={4}
        style={{ letterSpacing: "0.4px" }}
      >
        Sources
      </Text>
      <Stack gap={4}>
        {sources.map((src, idx) => (
          <button
            key={src.pageId}
            type="button"
            className={classes.sourceChip}
            onClick={() => {
              const url = buildPageUrl(src.spaceSlug ?? "", src.slugId, src.title);
              navigate(url);
            }}
            aria-label={`Go to ${src.title}`}
          >
            <span className={classes.citationBadge}>{idx + 1}</span>
            <IconFileText size={13} style={{ flexShrink: 0 }} />
            <span className={classes.sourceChipTitle}>{src.title}</span>
          </button>
        ))}
      </Stack>
    </div>
  );
}

function UserMessage({ msg }: { msg: KbMessage }) {
  return (
    <div className={classes.messageRow} data-role="user">
      <div className={classes.messageBubble}>
        <Text size="sm" style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
          {msg.content}
        </Text>
      </div>
      <div className={classes.messageAvatar}>
        <IconUser size={14} />
      </div>
    </div>
  );
}

function AssistantMessage({ msg }: { msg: KbMessage }) {
  const navigate = useNavigate();

  const handleCitationClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    const citationBadge = target.closest("[data-citation]") as HTMLElement;
    
    if (citationBadge && citationBadge.dataset.citation) {
      const idx = parseInt(citationBadge.dataset.citation, 10) - 1;
      const src = msg.sources[idx];
      if (src) {
        const url = buildPageUrl(src.spaceSlug ?? "", src.slugId, src.title);
        navigate(url);
      }
    }
  };

  return (
    <div className={classes.messageRow} data-role="assistant">
      <div className={classes.messageAvatar}>
        <IconRobotFace size={14} />
      </div>
      <div className={classes.messageBubble} onClick={handleCitationClick}>
        <Text
          size="sm"
          className={classes.answerText}
          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content, classes) }}
        />
        <SourceList sources={msg.sources} />
      </div>
    </div>
  );
}

function StreamingBubble({ content }: { content: string }) {
  return (
    <div className={classes.messageRow} data-role="assistant">
      <div className={classes.messageAvatar}>
        <IconRobotFace size={14} />
      </div>
      <div className={classes.messageBubble}>
        {content ? (
          <Text
            size="sm"
            className={classes.answerText}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(content, classes) }}
          />
        ) : (
          <Loader size="xs" />
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className={classes.emptyState}>
      <IconSparkles size={44} stroke={1.5} className={classes.emptyStateIcon} />
      <div className={classes.emptyStateBrand}>KB Chat</div>
      <h1 className={classes.emptyStateTitle}>What would you like to know?</h1>
      <Text size="sm" c="dimmed" ta="center" maw={400}>
        Ask questions about your knowledge base and get answers with cited
        sources.
      </Text>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function KbChatPage() {
  const store = useKbChatStoreContext();
  const {
    activeConversation,
    activeConversationId,
    createConversation,
    appendUserMessage,
    appendAssistantMessage,
  } = store;

  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const messages = activeConversation?.messages ?? [];

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streamingContent]);

  // Focus textarea when conversation changes
  useEffect(() => {
    textareaRef.current?.focus();
  }, [activeConversationId]);

  const handleSubmit = useCallback(async () => {
    const question = input.trim();
    if (!question || isLoading) return;

    setInput("");
    setError(null);
    setStreamingContent("");
    setIsLoading(true);

    let targetId = activeConversationId;
    // Ensure we have an active conversation
    if (!targetId) {
      targetId = createConversation();
    }

    // Append user message immediately
    appendUserMessage(question, targetId);

    try {
      const response = await sendKbChatMessage({ query: question });

      // Preserve existing "no info" detection — show no sources if the answer
      // indicates the KB does not have relevant information.
      const noInfo = hasNoInfo(response.answer);
      const sources = noInfo ? [] : (response.sources ?? []);

      appendAssistantMessage(response.answer, sources, targetId);
    } catch (err: unknown) {
      const e = err as {
        response?: { data?: { message?: string } };
        message?: string;
      };
      const msg =
        e?.response?.data?.message ??
        e?.message ??
        "Failed to get an answer. Please try again.";
      setError(msg);
    } finally {
      setIsLoading(false);
      setStreamingContent("");
    }
  }, [
    input,
    isLoading,
    activeConversationId,
    createConversation,
    appendUserMessage,
    appendAssistantMessage,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const hasMessages = messages.length > 0;

  return (
    <div className={classes.page}>
      {/* Message area */}
      <div className={classes.messageList}>
        {!hasMessages && !isLoading ? (
          <EmptyState />
        ) : (
          <div className={classes.messageStack}>
            {messages.map((msg) =>
              msg.role === "user" ? (
                <UserMessage key={msg.id} msg={msg} />
              ) : (
                <AssistantMessage key={msg.id} msg={msg} />
              ),
            )}
            {isLoading && <StreamingBubble content={streamingContent} />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className={classes.errorWrapper}>
          <Alert
            icon={<IconAlertCircle size={16} />}
            color="red"
            variant="light"
            withCloseButton
            onClose={() => setError(null)}
          >
            {error}
          </Alert>
        </div>
      )}

      {/* Input area */}
      <div className={classes.inputArea}>
        <div className={classes.inputBox}>
          <Textarea
            ref={textareaRef}
            placeholder="Ask a question about your knowledge base… (Enter to send)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            minRows={1}
            maxRows={6}
            autosize
            disabled={isLoading}
            className={classes.textarea}
            aria-label="Ask a question"
          />
          <ActionIcon
            className={classes.sendButton}
            onClick={handleSubmit}
            disabled={!input.trim() || isLoading}
            variant="filled"
            color="blue"
            size="lg"
            radius="md"
            aria-label="Send message"
          >
            {isLoading ? (
              <Loader size={14} color="white" />
            ) : (
              <IconSend size={16} />
            )}
          </ActionIcon>
        </div>
        <Text size="xs" c="dimmed" ta="center" mt={6}>
          KB Chat uses your imported knowledge base. Answers may not reflect
          real-time data.
        </Text>
      </div>
    </div>
  );
}
