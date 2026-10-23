import { expect, test } from "@playwright/test";

/**
 * Cold start on the free API host: while the server is still waking (gateway answers 503),
 * the page shows a friendly notice instead of an error, retries, and clears the notice once
 * the server answers. The API is intercepted, so this runs without timing a real cold start.
 */
test("slow first API call shows the waking-up notice, then recovers", async ({ page }) => {
  const wakesAt = Date.now() + 6_000;
  await page.route(/localhost:8000\//, async (route) => {
    if (Date.now() < wakesAt) {
      await route.fulfill({ status: 503, body: "Service waking up" });
    } else {
      await route.continue();
    }
  });

  await page.goto("/");
  const notice = page.getByRole("status").getByText("Waking up the demo server, this can take up to a minute.");
  await expect(notice).toBeVisible({ timeout: 10_000 });
  await expect(notice).toBeHidden({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Try a sample applicant: Asha Verma" })).toBeVisible();
  await expect(page.getByText(/couldn't reach/i)).toHaveCount(0);
});
