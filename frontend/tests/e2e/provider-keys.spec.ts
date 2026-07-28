import { expect, test } from "@playwright/test";

type SafeKey = {
  id: string;
  provider: "openai" | "gemini";
  label: string | null;
  key_hint: string;
  is_active: boolean;
  is_valid: null;
  last_validated_at: null;
  last_validation_error: null;
  cleanup_state: "normal";
  created_at: string;
};

test("adds, groups, and reloads safe provider-key metadata", async ({ page }) => {
  const brandId = crypto.randomUUID();
  const rawKeys = {
    openai: `dummy-${crypto.randomUUID()}-A1B2`,
    gemini: `dummy-${crypto.randomUUID()}-G3D4`,
  };
  const savedKeys: SafeKey[] = [];
  let submittedKeyBodies = 0;
  let requestWasOpaque = true;
  let responseWasOpaque = true;

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const requestText = `${request.url()} ${JSON.stringify(request.headers())}`;
    requestWasOpaque &&= !Object.values(rawKeys).some((key) => requestText.includes(key));

    if (url.pathname === "/api/v1/brands" && request.method() === "GET") {
      const body = JSON.stringify({
        brands: [
          {
            id: brandId,
            name: "Provider Key Test Brand",
            logo_url: null,
            cleanup_state: "normal",
            created_at: "2026-07-28T10:00:00Z",
          },
        ],
      });
      responseWasOpaque &&= !Object.values(rawKeys).some((key) => body.includes(key));
      await route.fulfill({ status: 200, contentType: "application/json", body });
      return;
    }

    if (url.pathname === `/api/v1/brands/${brandId}` && request.method() === "GET") {
      const body = JSON.stringify({
        id: brandId,
        name: "Provider Key Test Brand",
        logo_url: null,
        cleanup_state: "normal",
        created_at: "2026-07-28T10:00:00Z",
      });
      responseWasOpaque &&= !Object.values(rawKeys).some((key) => body.includes(key));
      await route.fulfill({ status: 200, contentType: "application/json", body });
      return;
    }

    if (url.pathname === `/api/v1/brands/${brandId}/keys` && request.method() === "GET") {
      const body = JSON.stringify({ keys: savedKeys });
      responseWasOpaque &&= !Object.values(rawKeys).some((key) => body.includes(key));
      await route.fulfill({ status: 200, contentType: "application/json", body });
      return;
    }

    if (url.pathname === `/api/v1/brands/${brandId}/keys` && request.method() === "POST") {
      const payload = request.postDataJSON() as {
        provider: "openai" | "gemini";
        key: string;
        label: string | null;
        make_active: boolean;
      };
      const expectedKey = rawKeys[payload.provider];
      if (payload.key === expectedKey) submittedKeyBodies += 1;
      requestWasOpaque &&=
        Boolean(request.headers()["idempotency-key"]?.match(/^[0-9a-f-]{36}$/i)) &&
        Object.values(rawKeys).filter((key) => request.postData()?.includes(key)).length === 1;

      if (payload.make_active) {
        savedKeys.forEach((key) => {
          if (key.provider === payload.provider) key.is_active = false;
        });
      }
      const added: SafeKey = {
        id: crypto.randomUUID(),
        provider: payload.provider,
        label: payload.label,
        key_hint: `***${payload.key.slice(-4)}`,
        is_active: payload.make_active,
        is_valid: null,
        last_validated_at: null,
        last_validation_error: null,
        cleanup_state: "normal",
        created_at: new Date().toISOString(),
      };
      savedKeys.unshift(added);
      const body = JSON.stringify(added);
      responseWasOpaque &&= !Object.values(rawKeys).some((key) => body.includes(key));
      await route.fulfill({ status: 201, contentType: "application/json", body });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "NOT_FOUND", message: "Not found." } }),
    });
  });

  const email = `provider-keys-${Date.now()}@example.com`;
  await page.goto("/signup");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByText(/Account created/i)).toBeVisible();

  await page.goto(`/brands/${brandId}/keys`);
  await expect(page.getByRole("heading", { name: "Provider keys" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "OpenAI" })).toHaveAttribute("aria-selected", "true");

  await page.getByLabel(/Label/).fill("Inactive OpenAI");
  await page.getByLabel("API key").fill(rawKeys.openai);
  await page.getByLabel("Make active").uncheck();
  await page.getByRole("button", { name: "Add OpenAI key" }).click();
  await expect(page.getByText("***A1B2")).toBeVisible();
  await expect(page.getByText("Inactive", { exact: true })).toBeVisible();
  await expect(page.getByText("Unvalidated", { exact: true })).toBeVisible();
  await expect(page.getByLabel("API key")).toHaveValue("");

  await page.getByRole("tab", { name: "Gemini" }).click();
  await page.getByLabel(/Label/).fill("Active Gemini");
  await page.getByLabel("API key").fill(rawKeys.gemini);
  await page.getByRole("button", { name: "Add Gemini key" }).click();
  await expect(page.getByText("***G3D4")).toBeVisible();
  await expect(page.getByText("Active", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByText("***A1B2")).toBeVisible();
  await page.getByRole("tab", { name: "Gemini" }).click();
  await expect(page.getByText("***G3D4")).toBeVisible();
  const visibleText = (await page.locator("body").textContent()) ?? "";
  const rawKeyIsVisible = Object.values(rawKeys).some((key) => visibleText.includes(key));

  expect(submittedKeyBodies === 2).toBeTruthy();
  expect(requestWasOpaque).toBeTruthy();
  expect(responseWasOpaque).toBeTruthy();
  expect(rawKeyIsVisible).toBeFalsy();
});
