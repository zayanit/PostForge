import { expect, test, type APIRequestContext } from "@playwright/test";

const MAIL_URL = process.env.INBUCKET_URL ?? "http://localhost:54324";

type InboxMessage = { ID: string; To: Array<{ Address: string }> };

async function fetchLatestRecoveryLink(request: APIRequestContext, email: string): Promise<string> {
  // The local mail testing service (Mailpit) needs a moment to receive the
  // outgoing email after the request that triggers it; poll briefly rather
  // than assuming it's already there.
  let match: InboxMessage | undefined;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const listResponse = await request.get(`${MAIL_URL}/api/v1/messages`);
    expect(listResponse.ok()).toBeTruthy();
    const body = await listResponse.json();
    const messages: InboxMessage[] = body.messages ?? [];
    match = messages.find((m) => m.To?.some((to) => to.Address === email));
    if (match) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  expect(match, `no email received for ${email}`).toBeDefined();

  const messageResponse = await request.get(`${MAIL_URL}/api/v1/message/${match!.ID}`);
  expect(messageResponse.ok()).toBeTruthy();
  const message = await messageResponse.json();
  const content: string = message.HTML || message.Text || "";

  // Supabase's recovery email links to GoTrue's /auth/v1/verify, which
  // redirects to our app's redirectTo — this is the real link a user
  // clicks, not our app's URL directly.
  const linkMatch = content.match(/https?:\/\/[^\s"'<>]*\/auth\/v1\/verify[^\s"'<>]*/);
  expect(linkMatch, `no verification link found in email to ${email}`).not.toBeNull();

  return linkMatch![0].replace(/&amp;/g, "&");
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

  // Request the unregistered-email case FIRST: resetPasswordForEmail()
  // stores its PKCE code verifier in a single, unparameterized cookie, so a
  // later request would overwrite the verifier the real email's link needs
  // — requesting this one first means it's the one that gets overwritten,
  // not the one we actually follow below.
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(`missing-${Date.now()}@example.com`);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/If an account exists/i)).toBeVisible();

  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(unique);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/If an account exists/i)).toBeVisible();

  const recoveryLink = await fetchLatestRecoveryLink(request, unique);

  // Follow the real link: GoTrue verifies the token server-side, then
  // redirects the browser to /reset-password in our app (with the session
  // token attached, either as a #hash fragment or a ?code= param depending
  // on project configuration — the page handles both).
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
