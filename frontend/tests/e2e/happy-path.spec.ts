import { expect, test } from "@playwright/test";

/**
 * Happy path, end to end through the real backend: landing page -> Strong borrower persona ->
 * phone + OTP -> details -> PAN -> e-KYC -> bank data -> decision -> KFS offer -> accept ->
 * e-sign -> disbursal. Figures are deterministic for this persona (₹5,00,000, 36 months,
 * score 781 -> 12.99%, 2% fee).
 */
test("strong borrower goes from landing page to disbursal", async ({ page }) => {
  const step = (name: string | RegExp) => page.getByRole("heading", { level: 1, name });
  const click = (name: string | RegExp) => page.getByRole("button", { name }).click();

  await page.goto("/");
  await expect(page.getByRole("note", { name: "Demo disclaimer" })).toContainText(
    "Not affiliated with any bank or lender",
  );
  await click("Start as Asha");

  // Phone + simulated OTP
  await expect(step("Verify your mobile number")).toBeVisible();
  await click("Send code");
  await expect(page.getByText("Simulated. No SMS was sent.")).toBeVisible();
  await click("Fill in the code");
  await click("Verify and continue");

  // Details are prefilled by the persona
  await expect(step("About you and your loan")).toBeVisible();
  await expect(page.getByLabel("Full name")).toHaveValue("Asha Verma");
  await click("Save and continue");

  // PAN, e-KYC, bank-data consent
  await expect(step("Verify your PAN")).toBeVisible();
  await click("Verify PAN");
  await expect(step("Complete e-KYC")).toBeVisible();
  await click("Send e-KYC code");
  await click("Fill in the code");
  await click("Complete e-KYC");
  await expect(step(/Share your bank data/)).toBeVisible();
  await click("Share bank data");

  // Decision
  await expect(step("Ready for your decision")).toBeVisible();
  await click("Get my decision");
  await expect(step("You're approved")).toBeVisible();
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();
  await click("Review your offer");

  // KFS-style offer: acceptance needs the acknowledgement tick
  await expect(step("Your loan offer")).toBeVisible();
  const kfs = page.getByRole("article", { name: "Key Fact Statement" });
  await expect(kfs).toContainText("₹5,00,000");
  await expect(kfs).toContainText("12.99%");
  await expect(kfs).toContainText("14.41%");
  await expect(kfs).toContainText("₹16,845");
  await expect(kfs).toContainText("not a legally compliant disclosure");
  const accept = page.getByRole("button", { name: "Accept offer" });
  await expect(accept).toBeDisabled();
  await page.getByRole("checkbox").click();
  await accept.click();

  // Separate e-sign and disbursal steps
  await expect(step("Sign your loan agreement")).toBeVisible();
  await click("Sign agreement");
  await expect(step("Agreement signed")).toBeVisible();
  await click(/Receive ₹4,90,000/);
  await expect(step("₹4,90,000 is on its way")).toBeVisible();
  await expect(page.getByText("All 8 steps complete")).toBeVisible();
});
