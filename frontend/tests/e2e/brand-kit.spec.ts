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
      savedPayload = {
        name: body.name,
        answers: {
          tagline: body.answers.tagline ?? savedPayload?.answers.tagline ?? null,
          tone: body.answers.tone || savedPayload?.answers.tone || "",
          audience: body.answers.audience || savedPayload?.answers.audience || "",
          colors: body.answers.colors.length
            ? body.answers.colors
            : savedPayload?.answers.colors ?? [],
          avoid_words: body.answers.avoid_words ?? savedPayload?.answers.avoid_words ?? null,
        },
      };
      const complete = Boolean(
        savedPayload.answers.tone &&
          savedPayload.answers.audience &&
          savedPayload.answers.colors.length
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          brand_id: BRAND_ID,
          brand_name: savedPayload.name,
          answers: savedPayload.answers,
          summary: complete ? summary : null,
          status: complete ? "complete" : "in_progress",
          completed_at: complete ? "2026-07-29T00:00:00Z" : null,
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

test("saves one answer, resumes it, and completes without optional answers", async ({ page }) => {
  let saved: CompleteKitPayload | null = null;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/brands" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          brands: [
            {
              id: BRAND_ID,
              name: saved?.name ?? "Resume Brand",
              logo_url: null,
              cleanup_state: "normal",
              kit_status: saved?.answers.tone && saved.answers.audience && saved.answers.colors.length
                ? "complete"
                : saved
                  ? "in_progress"
                  : "not_started",
              created_at: "2026-07-29T00:00:00Z",
            },
          ],
        }),
      });
      return;
    }
    if (url.pathname !== `/api/v1/brands/${BRAND_ID}/kit`) {
      await route.continue();
      return;
    }
    if (request.method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          brand_id: BRAND_ID,
          brand_name: "Resume Brand",
          answers: saved?.answers ?? { tagline: null, tone: null, audience: null, colors: [], avoid_words: null },
          summary: null,
          status: saved ? "in_progress" : "not_started",
          completed_at: null,
          updated_at: "2026-07-29T00:00:00Z",
        }),
      });
      return;
    }
    const body = request.postDataJSON() as CompleteKitPayload;
    saved = { name: body.name, answers: { ...body.answers } };
    const complete = Boolean(saved.answers.tone && saved.answers.audience && saved.answers.colors.length);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        brand_id: BRAND_ID,
        brand_name: saved.name,
        answers: saved.answers,
        summary: complete ? "Brand: Resume Brand\nTagline: Saved tagline" : null,
        status: complete ? "complete" : "in_progress",
        completed_at: complete ? "2026-07-29T00:00:00Z" : null,
        updated_at: "2026-07-29T00:00:00Z",
      }),
    });
  });

  await page.goto("/signup");
  await page.getByLabel("Email").fill(`brand-kit-resume-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign up" }).click();
  await expect(page.getByText(/Account created/i)).toBeVisible();
  await page.goto(BRAND_KIT_PATH);
  await page.getByLabel("Brand name").fill("Resume Brand");
  await expect(
    page.getByRole("option", { name: "Resume Brand (Not started)", exact: true })
  ).toBeAttached();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: /Tagline/ }).fill("Saved tagline");
  await page.getByRole("button", { name: "Save progress" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("option", { name: "Resume Brand (In progress)", exact: true })
  ).toBeAttached();
  await page.reload();
  await expect(page.getByText("In progress", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Previous", exact: true }).click();
  await expect(page.getByRole("textbox", { name: /Tagline/ })).toHaveValue("Saved tagline");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("combobox", { name: "Tone" }).selectOption("professional");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: "Audience" }).fill("Growing teams");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("textbox", { name: "Colors" }).fill("#123456");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Avoid words", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Complete kit" }).click();
  await expect(page.getByRole("heading", { name: "Complete", exact: true })).toBeVisible();
  await expect(
    page.getByRole("option", { name: "Resume Brand (Complete)", exact: true })
  ).toBeAttached();
  await page.goto("/brands");
  await expect(page.getByText("Complete", { exact: true })).toBeVisible();
});

test("redirects an unauthenticated visitor away from a brand kit", async ({ page }) => {
  await page.goto(BRAND_KIT_PATH);
  await expect(page).toHaveURL(/\/login$/);
});
