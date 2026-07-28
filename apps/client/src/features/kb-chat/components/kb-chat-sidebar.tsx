import { useCallback, useMemo } from "react";
import {
  ActionIcon,
  Text,
  Tabs,
  Tooltip,
  Stack,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import {
  IconPlus,
  IconMessageCircle,
  IconFileText,
  IconTrash,
} from "@tabler/icons-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useKbChatStoreContext } from "../context/kb-chat-store-context";
import type { KbConversation } from "../hooks/use-kb-chat-store";
import { buildPageUrl } from "@/features/page/page.utils";
import type { KbSource } from "../services/kb-chat-service";
import classes from "../styles/kb-chat-sidebar.module.css";

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const ts = date.getTime();

  if (ts >= startOfToday) {
    return date.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  }
  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** Collect unique sources (by pageId) across all assistant messages in a conversation. */
function getConversationSources(conv: KbConversation): KbSource[] {
  const seen = new Set<string>();
  const result: KbSource[] = [];
  for (const msg of conv.messages) {
    if (msg.role !== "assistant") continue;
    for (const src of msg.sources) {
      if (!seen.has(src.pageId)) {
        seen.add(src.pageId);
        result.push(src);
      }
    }
  }
  return result;
}

// ── Conversation list item ─────────────────────────────────────────────────────

function ConversationItem({
  conv,
  isActive,
  onSelect,
  onDelete,
}: {
  conv: KbConversation;
  isActive: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const firstUserMsg = conv.messages.find((m) => m.role === "user");
  const preview = firstUserMsg?.content ?? "";

  return (
    <button
      type="button"
      className={classes.chatItem}
      data-active={isActive || undefined}
      onClick={() => onSelect(conv.id)}
      aria-pressed={isActive}
      aria-label={conv.title}
    >
      <IconMessageCircle size={14} className={classes.chatItemIcon} />
      <div className={classes.chatItemBody}>
        <Text
          size="sm"
          fw={isActive ? 600 : 500}
          lineClamp={1}
          className={classes.chatItemTitle}
        >
          {conv.title || t("New conversation")}
        </Text>
        {preview && (
          <Text size="xs" c="dimmed" lineClamp={1} className={classes.chatItemPreview}>
            {preview}
          </Text>
        )}
      </div>
      <Text size="xs" c="dimmed" className={classes.chatItemDate}>
        {formatDate(conv.updatedAt)}
      </Text>
      <div className={classes.chatItemActions}>
        <Tooltip label={t("Delete")} withArrow position="right">
          <ActionIcon
            variant="subtle"
            size="xs"
            color="red"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(conv.id);
            }}
            aria-label={t("Delete conversation")}
          >
            <IconTrash size={13} />
          </ActionIcon>
        </Tooltip>
      </div>
    </button>
  );
}

// ── Source list item ───────────────────────────────────────────────────────────

function SourceItem({ src }: { src: KbSource }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      className={classes.sourceItem}
      onClick={() => {
        const url = buildPageUrl(src.spaceSlug ?? "", src.slugId, src.title);
        navigate(url);
      }}
      aria-label={`Navigate to ${src.title}`}
    >
      <IconFileText size={14} className={classes.sourceItemIcon} />
      <Text size="sm" lineClamp={2} className={classes.sourceItemTitle}>
        {src.title}
      </Text>
    </button>
  );
}

// ── Main sidebar ───────────────────────────────────────────────────────────────

export default function KbChatSidebar() {
  const { t } = useTranslation();
  const {
    conversations,
    activeConversationId,
    activeConversation,
    setActiveConversationId,
    createConversation,
    deleteConversation,
  } = useKbChatStoreContext();

  const sources = useMemo(
    () => (activeConversation ? getConversationSources(activeConversation) : []),
    [activeConversation],
  );

  const handleNewChat = useCallback(() => {
    createConversation();
  }, [createConversation]);

  const handleSelect = useCallback(
    (id: string) => setActiveConversationId(id),
    [setActiveConversationId],
  );

  const handleDelete = useCallback(
    (id: string) => {
      const conv = conversations.find((c) => c.id === id);
      const title = conv?.title || t("New conversation");
      modals.openConfirmModal({
        title: t("Delete conversation"),
        centered: true,
        children: (
          <Text size="sm">
            {t(
              'Are you sure you want to delete "{{title}}"? This cannot be undone.',
              { title },
            )}
          </Text>
        ),
        labels: { confirm: t("Delete"), cancel: t("Cancel") },
        confirmProps: { color: "red" },
        onConfirm: () => deleteConversation(id),
      });
    },
    [conversations, deleteConversation, t],
  );

  return (
    <div className={classes.sidebar}>
      {/* Header */}
      <div className={classes.header}>
        <h2 className={classes.title}>{t("KB Chat")}</h2>
        <Tooltip label={t("New chat")} openDelay={250} withArrow>
          <ActionIcon
            variant="subtle"
            color="gray"
            size="sm"
            onClick={handleNewChat}
            aria-label={t("New chat")}
          >
            <IconPlus size={16} />
          </ActionIcon>
        </Tooltip>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="chats" className={classes.tabs}>
        <Tabs.List>
          <Tabs.Tab value="chats" className={classes.tab}>
            {t("Chats")}
          </Tabs.Tab>
          <Tabs.Tab value="sources" className={classes.tab}>
            {t("Sources")}
          </Tabs.Tab>
        </Tabs.List>

        {/* Chats tab */}
        <Tabs.Panel value="chats" className={classes.tabPanel}>
          {conversations.length === 0 ? (
            <div className={classes.empty}>
              <IconMessageCircle
                size={28}
                stroke={1.5}
                className={classes.emptyIcon}
              />
              <Text size="sm" fw={600} className={classes.emptyTitle}>
                {t("No conversations yet")}
              </Text>
              <Text size="xs" c="dimmed" className={classes.emptyHint}>
                {t("Start a new chat above.")}
              </Text>
            </div>
          ) : (
            <Stack gap={2} className={classes.chatList}>
              {conversations.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conv={conv}
                  isActive={conv.id === activeConversationId}
                  onSelect={handleSelect}
                  onDelete={handleDelete}
                />
              ))}
            </Stack>
          )}
        </Tabs.Panel>

        {/* Sources tab */}
        <Tabs.Panel value="sources" className={classes.tabPanel}>
          {!activeConversation ? (
            <div className={classes.empty}>
              <IconFileText
                size={28}
                stroke={1.5}
                className={classes.emptyIcon}
              />
              <Text size="sm" fw={600} className={classes.emptyTitle}>
                {t("No conversation selected")}
              </Text>
              <Text size="xs" c="dimmed" className={classes.emptyHint}>
                {t("Select a chat to see its sources.")}
              </Text>
            </div>
          ) : sources.length === 0 ? (
            <div className={classes.empty}>
              <IconFileText
                size={28}
                stroke={1.5}
                className={classes.emptyIcon}
              />
              <Text size="sm" fw={600} className={classes.emptyTitle}>
                {t("No sources")}
              </Text>
              <Text size="xs" c="dimmed" className={classes.emptyHint}>
                {t("Sources from KB answers appear here.")}
              </Text>
            </div>
          ) : (
            <Stack gap={2} className={classes.chatList}>
              {sources.map((src) => (
                <SourceItem key={src.pageId} src={src} />
              ))}
            </Stack>
          )}
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
