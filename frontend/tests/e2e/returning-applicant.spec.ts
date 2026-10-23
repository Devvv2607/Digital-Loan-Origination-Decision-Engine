import { expect, test, type Page } from "@playwright/test";

/**
 * US-09 enhancement (D-47), through the real backend: an applicant whose first loan was
 * disbursed opens "My applications", sees it with its status, starts a new application with
 * the same PAN, and skips e-KYC ("KYC already verified").
 */
async function firstLoanToDisbursal(page: Page) {
  const step = (name: string | RegExp) => page.getByRole("heading", { level: 1, name });
  const click = (name: string | RegExp) => page.getByRole("button", { name }).click();

  await page.goto("/");
  await expect(page.getByText("Fictional person · synthetic data")).toHaveCount(5);
  await click("Try a sample applicant: Asha Verma");
  await click("Send code");
  await click("Fill in the code");
  await click("Verify and continue");
  await expect(step("About you and your loan")).toBeVisible();
  await click("Save and continue");
  await expect(step("Verify your PAN")).toBeVisible();
  await click("Verify PAN");
  await expect(step("Complete e-KYC")).toBeVisible();
  await click("Send e-KYC code");
  await click("Fill in the code");
  await click("Complete e-KYC");
  await click("Share bank data");
  await click("Get my decision");
  await click("Review your offer");
  await page.getByRole("checkbox").click();
  await click("Accept offer");
  await click("Sign agreement");
  await click(/Receive ₹4,90,000/);
  await expect(step("₹4,90,000 is on its way")).toBeVisible();
}

test("returning applicant sees their applications and reuses e-KYC", async ({ page }) => {
  const step = (name: string | RegExp) => page.getByRole("heading", { level: 1, name });
  const click = (name: string | RegExp) => page.getByRole("button", { name }).click();

  await firstLoanToDisbursal(page);

  // My applications: the disbursed loan, its status and next step
  await click("My applications");
  await expect(step("My applications")).toBeVisible();
  const items = page.getByRole("listitem");
  await expect(items).toHaveCount(1);
  await expect(items.first()).toContainText("₹5,00,000");
  await expect(items.first()).toContainText("Disbursed");
  await expect(items.first()).toContainText("Your loan has been disbursed");
  await expect(page.getByText("KYC already verified")).toBeVisible();

  // A new application with the same PAN skips e-KYC
  await click("Start a new application");
  await expect(step("About you and your loan")).toBeVisible();
  await click("Save and continue");
  await expect(step("Verify your PAN")).toBeVisible();
  await click("Verify PAN");
  await expect(step(/Share your bank data/)).toBeVisible();
  await expect(page.getByRole("status").getByText("KYC already verified")).toBeVisible();
  await expect(page.getByText("Step 5 of 8")).toBeVisible();

  // Both applications are listed, the new one first
  await click("My applications");
  await expect(page.getByRole("listitem")).toHaveCount(2);
  await expect(page.getByRole("listitem").first()).toContainText("Verification in progress");
  await expect(page.getByRole("listitem").first()).toContainText("KYC already verified");
});
