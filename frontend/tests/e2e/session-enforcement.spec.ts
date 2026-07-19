import { expect, test } from "@playwright/test";

test("unauthenticated access redirects to login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  await page.goto("/account");
  await expect(page).toHaveURL(/\/login$/);
});
