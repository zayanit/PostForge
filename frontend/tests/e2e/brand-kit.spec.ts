import { expect, test } from "@playwright/test";


const BRAND_ID = "22222222-2222-2222-2222-222222222222";
const BRAND_KIT_PATH = `/brands/${BRAND_ID}/kit`;

test.describe.skip("Brand Kit wizard with the local app stack", () => {
  test("completes the six ordered interview steps", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await expect(page.getByRole("heading", { name: "Name", exact: true })).toBeVisible();
    await page.getByLabel("Brand name").fill("My Brand");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Tagline", exact: true })).toBeVisible();

    await page.getByLabel("Tagline").fill("Innovation for everyone");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Tone", exact: true })).toBeVisible();

    await page.getByLabel("Tone").selectOption("professional");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Audience", exact: true })).toBeVisible();

    await page.getByLabel("Audience").fill("Small business owners aged 25-45");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Colors", exact: true })).toBeVisible();

    await page.getByLabel("Colors").fill("#FF5733, #3498DB");
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Avoid words", exact: true })).toBeVisible();

    await page.getByLabel("Avoid words").fill("cheap, discount");
    await page.getByRole("button", { name: "Complete kit" }).click();
    await expect(page.getByText("Complete", { exact: true })).toBeVisible();
    await expect(page.getByText(/Brand: My Brand/)).toBeVisible();
  });

  test("resumes partially saved answers after reload", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await page.getByLabel("Brand name").fill("My Brand");
    await page.getByRole("button", { name: "Next" }).click();
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
