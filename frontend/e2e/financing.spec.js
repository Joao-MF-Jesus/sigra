import { expect, test } from "playwright/test";


async function openFinancing(page) {
  await page.goto("/");
  await page.getByTestId("nav-financing").click();
  await expect(page.getByTestId("financing-page")).toBeVisible();
  await expect.poll(
    () => page.getByTestId("financing-vehicle-id").locator("option").count(),
  ).toBeGreaterThan(1);
}


async function calculateScenario(page, {
  name,
  budget = "3000",
  vehicleCost = "620",
  term = "36",
} = {}) {
  await page.getByTestId("financing-vehicle-id").selectOption({ index: 1 });
  await page.getByTestId("financing-term-months").fill(term);
  await page.getByTestId("financing-monthly-rate").fill("1.5");
  await page.getByTestId("financing-available_monthly_budget").fill(budget);
  await page.getByTestId("financing-estimated_monthly_vehicle_cost").fill(vehicleCost);
  await page.getByTestId("financing-offer-name").fill(name);
  await page.getByTestId("financing-submit").click();
  await expect(page.getByTestId("financing-result")).toBeVisible();
}


async function saveCurrentScenario(page) {
  const addButton = page.getByTestId("add-financing-comparison");
  await expect(addButton).toBeEnabled();
  await addButton.click();
}


test("navega entre financiamento, automoveis e motocicletas sem recomendar motos", async ({ page }) => {
  await openFinancing(page);
  await page.getByTestId("nav-recommendations").click();
  await page.getByTestId("recommendation-vehicle-type").selectOption("motorcycle");
  await expect(page.getByTestId("motorcycle-recommender-unavailable")).toBeVisible();
  await expect(page.getByTestId("motorcycle-development-page")).toBeVisible();
});


test("simulacao direta mostra parcela, total e aviso de credito", async ({ page }) => {
  await openFinancing(page);
  await calculateScenario(page, { name: "Proposta direta" });
  await expect(page.getByTestId("financing-regular-installment")).toContainText("R$");
  await expect(page.getByTestId("financing-total-acquisition")).toContainText("R$");
  await expect(page.getByTestId("financing-credit-disclaimer")).toContainText(
    "não representa proposta ou aprovação",
  );
});


test("alteracao posterior marca resultado stale e bloqueia comparacao", async ({ page }) => {
  await openFinancing(page);
  await calculateScenario(page, { name: "Cenário stale" });
  await page.getByTestId("financing-down_payment").fill("12000");
  await expect(page.getByTestId("financing-stale-warning")).toBeVisible();
  await expect(page.getByTestId("add-financing-comparison")).toBeDisabled();
});


test("contexto equivalente compara comprometimento uma unica vez", async ({ page }) => {
  await openFinancing(page);
  await calculateScenario(page, { name: "A", budget: "3000", vehicleCost: "620", term: "36" });
  await saveCurrentScenario(page);
  await calculateScenario(page, { name: "B", budget: "3000", vehicleCost: "620", term: "48" });
  await saveCurrentScenario(page);
  await page.getByTestId("compare-financing-scenarios").click();
  await expect(page.getByTestId("highlight-lowest_budget_commitment")).toBeVisible();
  await expect(page.getByTestId("suppressed-lowest_budget_commitment")).toHaveCount(0);
  await expect(page.getByTestId("highlight-lowest_budget_commitment")).toHaveCount(1);
});


test("orcamentos diferentes suprimem vencedor de comprometimento", async ({ page }) => {
  await openFinancing(page);
  await calculateScenario(page, { name: "A", budget: "3000", vehicleCost: "620" });
  await saveCurrentScenario(page);
  await calculateScenario(page, { name: "B", budget: "4000", vehicleCost: "620" });
  await saveCurrentScenario(page);
  await page.getByTestId("compare-financing-scenarios").click();
  await expect(page.getByTestId("highlight-lowest_budget_commitment")).toHaveCount(0);
  await expect(page.getByTestId("suppressed-lowest_budget_commitment")).toBeVisible();
  await expect(page.getByTestId("suppressed-lowest_budget_commitment")).toContainText(
    "Orçamentos mensais diferentes",
  );
});
