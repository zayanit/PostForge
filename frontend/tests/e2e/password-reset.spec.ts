import { expect, test, type APIRequestContext } from "@playwright/test";

const INBUCKET_URL = process.env.INBUCKET_URL ?? "http://localhost:54324";

type InboxMessage = { id: string };

async function fetchLatestRecoveryLink(request: APIRequestContext, email: string): Promise<string> {
  const mailbox = email.split("@")[0];

  // Inbucket needs a moment to receive the outgoing email after the request
  // that triggers it; poll briefly rather than assuming it's already there.
  let messages: InboxMessage[] = [];
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const listResponse = await request.get(`${INBUCKET_URL}/api/v1/mailbox/${mailbox}`);
    expect(listResponse.ok()).toBeTruthy();
    messages = await listResponse.json();
    if (messages.length > 0) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  expect(messages.length, `no email received for ${email}`).toBeGreaterThan(0);
  const latest = messages[messages.length - 1];

  const messageResponse = await request.get(`${INBUCKET_URL}/api/v1/mailbox/${mailbox}/${latest.id}`);
  expect(messageResponse.ok()).toBeTruthy();
  const body = await messageResponse.json();
  const content: string = body.body?.html || body.body?.text || "";

  // Supabase's recovery email links to GoTrue's /auth/v1/verify, which
  // redirects to our app's redirectTo with the PKCE code attached — this is
  // the real link a user clicks, not our app's URL directly.
  const match = content.match(/https?:\/\/[^\s"'<>]*\/auth\/v1\/verify[^\s"'<>]*/);
  expect(match, `no verification link found in email to ${email}`).not.toBeNull();

  return match![0].replace(/&amp;/g, "&");
}

test("password reset request and confirm flow works via a real emailed link", async ({ page, request }) => {
  const unique = `reset-${Date.now()}@example.com`;
  const initialPassword = "password123";
  const newPassword = "newpassword123";

  await page.goto("/signup");
  await page.getByLabel("Email").fill(unique);
  await page.getByLabel("Password").fill(initialPassword);
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByText(/Account created/i)).toBeVisible();

  // Log out so the reset flow below is exercised as an unauthenticated
  // visitor, not riding on the session signUp() just established.
  await page.goto("/");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(unique);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/If an account exists/i)).toBeVisible();

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(`missing-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/If an account exists/i)).toBeVisible();

  const recoveryLink = await fetchLatestRecoveryLink(request, unique);

  // Follow the real link: GoTrue verifies the token server-side, then
  // redirects the browser to /reset-password?code=... in our app.
  await page.goto(recoveryLink);
  await expect(page).toHaveURL(/\/reset-password/);

  await page.getByLabel("New password").fill(newPassword);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText(/Password updated/i)).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Email").fill(unique);
  await page.getByLabel("Password").fill(newPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/$/);

  await page.getByRole("button", { name: "Log out" }).click();
  await page.goto("/login");
  await page.getByLabel("Email").fill(unique);
  await page.getByLabel("Password").fill(initialPassword);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/incorrect/i)).toBeVisible();
});
