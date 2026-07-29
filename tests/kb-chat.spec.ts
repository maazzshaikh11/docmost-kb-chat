import { test, expect } from "@playwright/test";
import { login } from "./helpers/auth";
import {
  navigateToKbChat,
  askKbQuestion,
  waitForAssistantResponse,
} from "./helpers/kb-chat";

const KNOWN_KB_QUESTION =
  process.env.TEST_KB_QUESTION ?? "What is Docmost?";

const QUESTION_WITH_SOURCES =
  process.env.TEST_KB_QUESTION_WITH_SOURCES ??
  "How to sync contacts?";

const LONG_KB_QUESTION =
  process.env.TEST_KB_LONG_QUESTION ??
  "Can you explain how Docmost handles real-time collaboration, " +
  "including how multiple users can edit the same document simultaneously, " +
  "how conflicts are resolved, what happens when a user goes offline and reconnects, " +
  "and how the version history feature interacts with live edits?";

test.describe("KB Chat E2E Tests", () => {
  test("User can login", async ({ page }) => {
    await login(page);
    await expect(page).toHaveURL(/home|kb-chat/);
  });

  test("KB Chat page loads", async ({ page }) => {
    await login(page);
    await navigateToKbChat(page);

    await expect(
      page.getByPlaceholder(
        "Ask a question about your knowledge base… (Enter to send)"
      )
    ).toBeVisible();

    await expect(
      page.getByText("What would you like to know?")
    ).toBeVisible();
  });

  test("User can ask a KB question", async ({ page }) => {
    await login(page);
    await navigateToKbChat(page);

    await askKbQuestion(page, KNOWN_KB_QUESTION);
    await waitForAssistantResponse(page);

    const userMsg = page.locator('[data-role="user"]').last();
    await expect(userMsg).toBeVisible();
    await expect(userMsg).toContainText(KNOWN_KB_QUESTION);

    const assistantMsg = page.locator('[data-role="assistant"]').last();
    await expect(assistantMsg).toBeVisible();
    await expect(assistantMsg).toContainText(/[a-zA-Z]{5,}/);
  });

  test("Sources are displayed after a successful response", async ({
    page,
  }) => {
    await login(page);
    await navigateToKbChat(page);

    await askKbQuestion(page, QUESTION_WITH_SOURCES);
    await waitForAssistantResponse(page);

    const assistantMsg = page.locator('[data-role="assistant"]').last();
    await expect(assistantMsg).toBeVisible();

    const sourcesHeading = assistantMsg.getByText("Sources", {
      exact: true,
    });
    await expect(sourcesHeading).toBeVisible();

    const sourceChip = assistantMsg.getByRole("button").first();
    await expect(sourceChip).toBeVisible();
  });

  test("User can ask multiple questions in the same conversation", async ({
    page,
  }) => {
    await login(page);
    await navigateToKbChat(page);

    const firstQuestion = "First question";
    await askKbQuestion(page, firstQuestion);
    await waitForAssistantResponse(page);

    let userMsg = page.locator('[data-role="user"]').last();
    await expect(userMsg).toContainText(firstQuestion);

    const secondQuestion = "Second question";
    await askKbQuestion(page, secondQuestion);
    await waitForAssistantResponse(page);

    userMsg = page.locator('[data-role="user"]').last();
    await expect(userMsg).toContainText(secondQuestion);

    const assistantMsg = page.locator('[data-role="assistant"]').last();
    await expect(assistantMsg).toBeVisible();
    await expect(assistantMsg).toContainText(/[a-zA-Z]{5,}/);
  });

  test("Empty input should not send a message", async ({ page }) => {
    await login(page);
    await navigateToKbChat(page);

    const input = page.getByPlaceholder(
      "Ask a question about your knowledge base… (Enter to send)"
    );

    await input.fill("   ");

    const sendButton = page.getByLabel("Send message");
    await expect(sendButton).toBeDisabled();

    await input.press("Enter");

    await expect(page.locator('[data-role="user"]')).toHaveCount(0);
  });

  test("Long question is handled without crashing", async ({ page }) => {
    await login(page);
    await navigateToKbChat(page);

    await askKbQuestion(page, LONG_KB_QUESTION);
    await waitForAssistantResponse(page);

    const userMsg = page.locator('[data-role="user"]').last();
    await expect(userMsg).toBeVisible();

    const assistantMsg = page.locator('[data-role="assistant"]').last();
    await expect(assistantMsg).toBeVisible();
    await expect(assistantMsg).toContainText(/[a-zA-Z]{5,}/);

    await expect(page.getByRole("alert")).toHaveCount(0);
  });

  test("User can navigate via inline citations", async ({ page }) => {
    await login(page);
    await navigateToKbChat(page);

    await askKbQuestion(page, QUESTION_WITH_SOURCES);
    await waitForAssistantResponse(page);

    const assistantMsg = page.locator('[data-role="assistant"]').last();
    await expect(assistantMsg).toBeVisible();

    const citation = assistantMsg.locator('[data-citation="1"]').first();
    await expect(citation).toBeVisible();

    await citation.click();

    await expect(page).not.toHaveURL(/\/kb-chat/);
    await expect(page.locator("h1")).toBeVisible();
  });

  test("User can navigate via source chips", async ({ page }) => {
    await login(page);
    await navigateToKbChat(page);

    await askKbQuestion(page, QUESTION_WITH_SOURCES);
    await waitForAssistantResponse(page);

    const assistantMsg = page.locator('[data-role="assistant"]').last();
    await expect(assistantMsg).toBeVisible();

    const sourceChip = assistantMsg.getByRole("button").first();
    await expect(sourceChip).toBeVisible();

    await sourceChip.click();

    await expect(page).not.toHaveURL(/\/kb-chat/);
    await expect(page.locator("h1")).toBeVisible();
  });
});