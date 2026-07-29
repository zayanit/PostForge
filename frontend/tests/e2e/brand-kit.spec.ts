import { expect, test } from "@playwright/test";


const BRAND_ID = "22222222-2222-2222-2222-222222222222";
const BRAND_KIT_PATH = `/brands/${BRAND_ID}/kit`;

type CompleteKitPayload = {
  name: string;
  answers: {
    tagline: string | null;
    tone: string;
    audience: string;
    colors: string[];
    avoid_words: string | null;
  };
};

test.setTimeout(300_000);

test("completes and reloads a brand kit within five minutes", async ({ page }) => {
  const startedAt = Date.now();
  let savedPayload: CompleteKitPayload | null = null;
  const summary = [
    "Brand: My Brand",
    "Tagline: Innovation for everyone",
    "Tone: professional",
    "Audience: Small business owners aged 25-45",
    "Colors: #FF5733, #3498DB",
    "Avoid words: cheap, discount",
  ].join("\n");

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname !== `/api/v1/brands/${BRAND_ID}/kit`) {
      await route.continue();
      return;
    }

    if (request.method() === "GET") {
      const current = savedPayload;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          brand_id: BRAND_ID,
          brand_name: current?.name ?? "My Brand",
          answers: current
            ? current.answers
            : { tagline: null, tone: null, audience: null, colors: [], avoid_words: null },
          summary: current ? summary : null,
          status: current ? "complete" : "not_started",
          completed_at: current ? "2026-07-29T00:00:00Z" : null,
          updated_at: current ? "2026-07-29T00:00:00Z" : null,
        }),
      });
      return;
    }

    if (request.method() === "PUT") {
      const body = request.postDataJSON() as CompleteKitPayload;
      expect(body).toEqual({
        name: "My Brand",
        answers: {
          tagline: "Innovation for everyone",
          tone: "professional",
          audience: "Small business owners aged 25-45",
          colors: ["#FF5733", "#3498DB"],
          avoid_words: "cheap, discount",
        },
      });
      savedPayload = body;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          brand_id: BRAND_ID,
          brand_name: body.name,
          answers: body.answers,
          summary,
          status: "complete",
          completed_at: "2026-07-29T00:00:00Z",
          updated_at: "2026-07-29T00:00:00Z",
        }),
      });
    }
  });

  await page.goto("/signup");
  await page.getByLabel("Email").fill(`brand-kit-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByText(/Account created/i)).toBeVisible();

  await page.goto(BRAND_KIT_PATH);
  await expect(page.getByLabel("Brand name")).toHaveValue("My Brand");
  await page.getByLabel("Brand name").fill("My Brand");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: /Tagline/ }).fill("Innovation for everyone");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("combobox", { name: "Tone" }).selectOption("professional");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: "Audience" }).fill("Small business owners aged 25-45");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: "Colors" }).fill("#FF5733, #3498DB");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: /Avoid words/ }).fill("cheap, discount");
  await page.getByRole("button", { name: "Complete kit" }).click();

  await expect(page.getByRole("heading", { name: "Complete", exact: true })).toBeVisible();
  await expect(page.getByText(/Brand: My Brand/)).toBeVisible();
  expect(Date.now() - startedAt).toBeLessThan(300_000);

  await page.reload();
  await expect(page.getByRole("heading", { name: "Complete", exact: true })).toBeVisible();
  await expect(page.getByText(/Innovation for everyone/)).toBeVisible();
});

test.describe.skip("Brand Kit wizard with the local app stack", () => {
  test("completes the six ordered interview steps", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await expect(page.getByRole("heading", { name: "Name", exact: true })).toBeVisible();
    await page.getByLabel("Brand name").fill("My Brand");
  await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Tagline", exact: true })).toBeVisible();

    await page.getByLabel("Tagline").fill("Innovation for everyone");
  await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Tone", exact: true })).toBeVisible();

    await page.getByLabel("Tone").selectOption("professional");
  await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Audience", exact: true })).toBeVisible();

    await page.getByLabel("Audience").fill("Small business owners aged 25-45");
  await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Colors", exact: true })).toBeVisible();

    await page.getByLabel("Colors").fill("#FF5733, #3498DB");
  await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Avoid words", exact: true })).toBeVisible();

    await page.getByLabel("Avoid words").fill("cheap, discount");
    await page.getByRole("button", { name: "Complete kit" }).click();
    await expect(page.getByText("Complete", { exact: true })).toBeVisible();
    await expect(page.getByText(/Brand: My Brand/)).toBeVisible();
  });

  test("resumes partially saved answers after reload", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await page.getByLabel("Brand name").fill("My Brand");
  await page.getByRole("button", { name: "Next", exact: true }).click();
    await page.getByLabel("Tagline").fill("");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Tone").selectOption("");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Audience").fill("");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Colors").fill("");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Avoid words").fill("");
    await page.getByRole("button", { name: "Save progress" }).click();
    await page.reload();

    await expect(page.getByText("In progress", { exact: true })).toBeVisible();
  });

  test("shows the deterministic summary after completion", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await page.getByLabel("Brand name").fill("My Brand");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Tagline").fill("Innovation for everyone");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Tone").selectOption("professional");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Audience").fill("Small business owners aged 25-45");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Colors").fill("#FF5733, #3498DB");
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Avoid words").fill("cheap, discount");
    await page.getByRole("button", { name: "Complete kit" }).click();
    await page.reload();

    await expect(page.getByText("Complete", { exact: true })).toBeVisible();
    await expect(page.getByText(/Brand: My Brand/)).toBeVisible();
  });

  test("redirects unauthorized visitors to login", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await expect(page).toHaveURL(/\/login$/);
  });
});
