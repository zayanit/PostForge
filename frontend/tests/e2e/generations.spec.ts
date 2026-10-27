import { expect, test, type Page } from "@playwright/test";
import { createServer, type Server } from "node:http";

const BRAND = "22222222-2222-2222-2222-222222222222";
const USER = "11111111-1111-1111-1111-111111111111";
const ID = "33333333-3333-3333-3333-333333333333";
const user = {
  id: USER,
  aud: "authenticated",
  role: "authenticated",
  email: "generation@example.test",
  app_metadata: { provider: "email", providers: ["email"] },
  user_metadata: {},
  identities: [],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};
let auth: Server;
test.beforeAll(async () => {
  auth = createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    if (
      request.url === "/auth/v1/user" &&
      request.headers.authorization?.startsWith("Bearer ")
    ) {
      response.end(JSON.stringify(user));
    } else {
      response.statusCode = 401;
      response.end(JSON.stringify({ message: "Sign in required" }));
    }
  });
  await new Promise<void>((resolve) =>
    auth.listen(54329, "127.0.0.1", resolve)
  );
});
test.afterAll(async () => {
  await new Promise<void>((resolve, reject) => {
    auth.close((error) => (error ? reject(error) : resolve()));
    auth.closeAllConnections();
  });
});

type ImageRecord = {
  id: string;
  brand_id: string;
  prompt: string;
  provider: string;
  model: string;
  platform_preset: string;
  width: number;
  height: number;
  status: string;
  image_url: string | null;
  error_code: string | null;
  cleanup_required: boolean;
  created_at: string;
  completed_at: string | null;
};

async function fixture(page: Page, kitStatus = "not_started") {
  const expires = Math.floor(Date.now() / 1000) + 3600;
  const jwt = [
    Buffer.from(JSON.stringify({ alg: "HS256", typ: "JWT" })).toString(
      "base64url"
    ),
    Buffer.from(
      JSON.stringify({ sub: USER, aud: "authenticated", exp: expires })
    ).toString("base64url"),
    "test-signature",
  ].join(".");
  const session = {
    access_token: jwt,
    refresh_token: "test-refresh",
    expires_at: expires,
    expires_in: 3600,
    token_type: "bearer",
    user,
  };
  await page.context().addCookies([
    {
      name: "sb-127-auth-token",
      value: `base64-${Buffer.from(JSON.stringify(session)).toString("base64url")}`,
      url: "http://127.0.0.1:3011",
      sameSite: "Lax",
    },
  ]);
  const state = {
    generation: null as ImageRecord | null,
    requests: [] as string[],
    missingKey: false,
    failOnce: false,
    deletes: 0,
    failDelete: false,
  };
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64"
  );
  await page.route("**/fixture-image.png*", (route) =>
    route.fulfill({ contentType: "image/png", body: png })
  );
  const brand = {
    id: BRAND,
    name: "Garden Studio",
    kit_status: kitStatus,
    cleanup_state: "normal",
    logo_url: null,
    created_at: "2026-01-01T00:00:00Z",
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const fulfill = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path === "/api/v1/brands") return fulfill({ brands: [brand] });
    if (path === `/api/v1/brands/${BRAND}`) return fulfill(brand);
    if (path === "/api/v1/brands/generation-presets")
      return fulfill({
        presets: [
          {
            id: "instagram_post",
            label: "Instagram Post",
            width: 1080,
            height: 1080,
          },
          {
            id: "youtube_thumbnail",
            label: "YouTube Thumbnail",
            width: 1280,
            height: 720,
          },
        ],
      });
    if (path.endsWith("/generate")) {
      state.requests.push(request.headers()["idempotency-key"]);
      if (state.missingKey)
        return fulfill({ error: { code: "OPENAI_KEY_REQUIRED" } }, 409);
      if (state.failOnce) {
        state.failOnce = false;
        return route.abort("failed");
      }
      state.generation = {
        id: ID,
        brand_id: BRAND,
        prompt: request.postDataJSON().prompt,
        provider: "openai",
        model: "gpt-image-2",
        platform_preset: request.postDataJSON().platform_preset,
        width: 1080,
        height: 1080,
        status: "pending",
        image_url: null,
        error_code: null,
        cleanup_required: false,
        created_at: "2026-10-27T00:00:00Z",
        completed_at: null,
      };
      return fulfill(state.generation, 202);
    }
    if (path.endsWith(`/generations/${ID}`)) {
      if (request.method() === "DELETE") {
        if (state.failDelete)
          return fulfill({ error: { code: "STORAGE_UNAVAILABLE" } }, 503);
        state.generation = null;
        state.deletes++;
        return route.fulfill({ status: 204 });
      }
      return state.generation
        ? fulfill(state.generation)
        : fulfill({ error: { code: "GENERATION_NOT_FOUND" } }, 404);
    }
    if (path.endsWith("/generations"))
      return fulfill({
        generations: state.generation ? [state.generation] : [],
        page: 1,
        per_page: 20,
        total: state.generation ? 1 : 0,
      });
    return fulfill({ error: { code: "GENERATION_NOT_FOUND" } }, 404);
  });
  return state;
}

async function submit(page: Page) {
  await page
    .getByLabel("Image prompt", { exact: true })
    .fill("A bright garden product launch");
  await page
    .getByRole("combobox", { name: "Platform preset", exact: true })
    .selectOption("instagram_post");
  await page
    .getByRole("button", { name: "Generate image", exact: true })
    .click();
}

test("empty kit can generate, reload, complete, download, and delete", async ({
  page,
}, testInfo) => {
  const state = await fixture(page);
  await page.goto(`/brands/${BRAND}/generate`);
  await expect(
    page.getByRole("combobox", { name: "Platform preset", exact: true })
  ).toHaveValue("");
  await expect(
    page.getByRole("link", { name: "Complete your Brand Kit" })
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Generate image", exact: true })
  ).toBeDisabled();
  await page.screenshot({
    path: testInfo.outputPath("generator-desktop.png"),
    fullPage: true,
  });
  await submit(page);
  await expect(
    page
      .getByRole("status", { name: "", exact: true })
      .filter({ hasText: "Queued" })
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  state.generation!.status = "processing";
  await expect(page.getByText("Processing", { exact: true })).toBeVisible();
  state.generation!.status = "succeeded";
  state.generation!.image_url =
    "http://127.0.0.1:3011/fixture-image.png?token=temporary";
  await expect(
    page.getByRole("button", { name: "Download PNG" })
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download PNG" }).click();
  expect((await download).suggestedFilename()).toContain(".png");
  await page.getByRole("link", { name: "History", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Image history" })
  ).toBeVisible();
  await page.getByRole("button", { name: "Delete image", exact: true }).click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(state.deletes).toBe(0);
  await page.getByRole("button", { name: "Delete image", exact: true }).click();
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.getByText(/No images yet/)).toBeVisible();
  expect(state.deletes).toBe(1);
  expect(state.requests).toHaveLength(1);
});

test("partial kit can submit and missing key links to setup", async ({
  page,
}) => {
  const state = await fixture(page, "in_progress");
  state.missingKey = true;
  await page.goto(`/brands/${BRAND}/generate`);
  await submit(page);
  await expect(
    page.getByRole("alert").filter({ hasText: "Add or activate" })
  ).toContainText("Add or activate an OpenAI key");
  await expect(
    page.getByRole("link", { name: "Manage provider keys" })
  ).toHaveAttribute("href", `/brands/${BRAND}/keys`);
});

test("uncertain submissions reuse their idempotency key on explicit retry", async ({
  page,
}) => {
  const state = await fixture(page);
  state.failOnce = true;
  await page.goto(`/brands/${BRAND}/generate`);
  await submit(page);
  await expect(
    page.getByRole("alert").filter({
      hasText: "Submitting again is safe: it won’t create a duplicate image.",
    })
  ).toBeVisible();
  // The browser's raw fetch error text is never shown.
  await expect(
    page.getByText(/failed to fetch|load failed|networkerror/i)
  ).toHaveCount(0);
  expect(state.requests).toHaveLength(1);
  await page
    .getByRole("button", { name: "Generate image", exact: true })
    .click();
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  expect(state.requests[0]).toBe(state.requests[1]);
});

test("failure history is actionable and deletion can be retried", async ({
  page,
}) => {
  const state = await fixture(page);
  await page.goto(`/brands/${BRAND}/generate`);
  await submit(page);
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  state.generation!.status = "failed";
  state.generation!.error_code = "PROVIDER_TIMEOUT";
  await page.goto(`/brands/${BRAND}/history`);
  await expect(page.getByText(/OpenAI did not respond in time/)).toBeVisible();
  await page
    .getByRole("combobox", { name: "Status", exact: true })
    .selectOption("failed");
  await page.getByRole("button", { name: "Delete image", exact: true }).click();
  state.failDelete = true;
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "storage is unavailable"
  );
  expect(state.deletes).toBe(0);
  state.failDelete = false;
  await page
    .getByRole("button", { name: "Delete permanently", exact: true })
    .click();
  await expect(page.getByText(/No images yet/)).toBeVisible();
});

test("mobile generation form fits without horizontal overflow", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await fixture(page);
  await page.goto(`/brands/${BRAND}/generate`);
  await expect(
    page.getByRole("combobox", { name: "Platform preset", exact: true })
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth
    )
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("generator-mobile.png"),
    fullPage: true,
  });
});

test("completed image links refresh before their signed URL expires", async ({
  page,
}) => {
  await page.clock.install();
  const state = await fixture(page);
  await page.goto(`/brands/${BRAND}/generate`);
  await submit(page);
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  state.generation!.status = "succeeded";
  state.generation!.image_url =
    "http://127.0.0.1:3011/fixture-image.png?token=first";
  await page.clock.fastForward(2100);
  await expect(
    page.getByRole("img", {
      name: "A bright garden product launch",
      exact: true,
    })
  ).toHaveAttribute("src", /token=first/);
  state.generation!.image_url =
    "http://127.0.0.1:3011/fixture-image.png?token=refreshed";
  await page.clock.fastForward(240100);
  await expect(
    page.getByRole("img", {
      name: "A bright garden product launch",
      exact: true,
    })
  ).toHaveAttribute("src", /token=refreshed/);
});

test("history polls only in-progress items and reloads once when they finish", async ({
  page,
}) => {
  await page.clock.install();
  const state = await fixture(page);
  await page.goto(`/brands/${BRAND}/generate`);
  await submit(page);
  await expect(page.getByText("Queued", { exact: true })).toBeVisible();
  let listRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.endsWith("/generations"))
      listRequests += 1;
  });
  await page.goto(`/brands/${BRAND}/history`);
  await expect(
    page.getByRole("article").getByText("Queued", { exact: true })
  ).toBeVisible();
  const initial = listRequests;
  await page.clock.fastForward(2100);
  await page.clock.fastForward(2100);
  await page.clock.fastForward(2100);
  expect(listRequests).toBe(initial);
  state.generation!.status = "succeeded";
  state.generation!.image_url =
    "http://127.0.0.1:3011/fixture-image.png?token=done";
  await page.clock.fastForward(2100);
  await expect(
    page.getByRole("img", {
      name: "A bright garden product launch",
      exact: true,
    })
  ).toHaveAttribute("src", /token=done/);
  expect(listRequests).toBe(initial + 1);
});

test("unauthenticated generation access redirects to login", async ({
  page,
}) => {
  await page.goto(`/brands/${BRAND}/generate`);
  await expect(page).toHaveURL(/\/login$/);
  await page.goto(`/brands/${BRAND}/history`);
  await expect(page).toHaveURL(/\/login$/);
});
