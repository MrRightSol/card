
import { test, expect } from '@playwright/test';

test('happy path demo flow', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Generate Data')).toBeVisible();
  await page.getByRole('button', { name: /Generate Data/i }).click();
  await expect(page.getByText(/generated/i)).toBeVisible();

  await page.getByRole('button', { name: /Upload Policy/i }).click();
  // In CI, use a pre-loaded JSON fallback instead of actual file
  await expect(page.getByText(/Rules JSON/i)).toBeVisible();

  await page.getByRole('button', { name: /Train Model/i }).click();
  await expect(page.getByText(/Training complete/i)).toBeVisible();

  await page.getByRole('button', { name: /Run Scoring/i }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await page.getByRole('row', { name: /Fraudulent|Suspicious|Clear/ }).first().click();
  await expect(page.getByText(/why flagged/i)).toBeVisible();
});
