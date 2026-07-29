import { Page } from "@playwright/test";

export async function navigateToKbChat(page: Page) {
  await page.goto("/kb-chat");
  await page
    .getByPlaceholder(
      "Ask a question about your knowledge base… (Enter to send)"
    )
    .waitFor({ state: "visible" });
}

export async function askKbQuestion(page: Page, question: string) {
  const input = page.getByPlaceholder(
    "Ask a question about your knowledge base… (Enter to send)"
  );

  await input.click();
  await input.pressSequentially(question);
  await input.press("Enter");
}

export async function waitForAssistantResponse(page: Page) {
  await page.waitForResponse(
    (response) =>
      response.url().includes("/api/kb-chat") &&
      response.request().method() === "POST",
    { timeout: 60000 }
  );

  const assistantMessage = page.locator('[data-role="assistant"]').last();
  await assistantMessage.waitFor({ state: "visible" });
}