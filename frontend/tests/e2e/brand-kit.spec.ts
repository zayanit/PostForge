import { expect, test } from "@playwright/test";


const BRAND_ID = "22222222-2222-2222-2222-222222222222";
const BRAND_KIT_PATH = `/brands/${BRAND_ID}/kit`;

test.describe.skip("Brand Kit wizard with the local app stack", () => {
  test("completes the six ordered interview steps", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    for (const step of ["Name", "Tagline", "Tone", "Audience", "Colors", "Avoid words"]) {
      await expect(page.getByText(step, { exact: true })).toBeVisible();
    }
  });

  test("resumes partially saved answers after reload", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);
    await page.reload();

    await expect(page.getByText("In progress", { exact: true })).toBeVisible();
  });

  test("shows the deterministic summary after completion", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await expect(page.getByText("Complete", { exact: true })).toBeVisible();
    await expect(page.getByText(/Brand: My Brand/)).toBeVisible();
  });

  test("redirects unauthorized visitors to login", async ({ page }) => {
    await page.goto(BRAND_KIT_PATH);

    await expect(page).toHaveURL(/\/login$/);
  });
});
