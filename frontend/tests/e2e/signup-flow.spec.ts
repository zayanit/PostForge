import { expect, test } from "@playwright/test";

test("visitors can navigate between login and signup", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign up" }).click();
  await expect(page).toHaveURL(/\/signup$/);

  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/login$/);
});

test("signup validates the password before submitting", async ({ page }) => {
  await page.goto("/signup");
  await page.getByLabel("Email").fill("new-user@example.com");
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Sign up" }).click();

  await expect(page.getByText("Password must be at least 8 characters.")).toBeVisible();
});
