import { Page, expect } from "@playwright/test";

export async function login(page: Page) {
  const email = process.env.TEST_EMAIL;
  const password = process.env.TEST_PASSWORD;

  if (!email || !password) {
    throw new Error(
      "TEST_EMAIL and TEST_PASSWORD must be defined."
    );
  }

  await page.goto("/login");

  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);

  await page.getByRole("button", {
    name: "Sign In",
  }).click();

  await expect(page).not.toHaveURL(/login/);
}