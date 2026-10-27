import { expect, test } from "playwright/test";


const externalEnvironment = process.env.E2E_EXTERNAL_ENVIRONMENT === "true";
const apiUrl = (process.env.E2E_API_URL || "").replace(/\/+$/, "");


async function calculateRecommendation(page) {
  await page.goto("/");
  await page.getByTestId("recommendation-use-case").selectOption("cidade");
  await page.getByTestId("recommendation-next-need").click();
  await page.getByTestId("recommendation-budget").fill("200000");
  await page.getByTestId("recommendation-monthly-limit").fill("3500");
  await page.getByTestId("recommendation-next-budget").click();
  await page.getByTestId("recommendation-strategy").selectOption("best_within_budget");
  await page.getByTestId("recommendation-monthly-mileage").fill("1000");
  await page.getByTestId("recommendation-fuel-price").fill("6");
  await page.getByTestId("recommendation-next-priorities").click();
  await page.getByTestId("recommendation-next-advanced").click();
  await page.getByTestId("recommendation-submit").click();
  await expect(page.getByTestId("recommendation-results")).toBeVisible();
}


async function openFinancing(page) {
  await page.goto("/");
  await page.getByTestId("nav-financing").click();
  await expect(page.getByTestId("financing-page")).toBeVisible();
  await expect.poll(
    () => page.getByTestId("financing-vehicle-id").locator("option").count(),
  ).toBeGreaterThan(1);
}


async function calculateFinancing(page, name, term) {
  await page.getByTestId("financing-vehicle-id").selectOption({ index: 1 });
  await page.getByTestId("financing-term-months").fill(String(term));
  await page.getByTestId("financing-monthly-rate").fill("1.5");
  await page.getByTestId("financing-available_monthly_budget").fill("3000");
  await page.getByTestId("financing-estimated_monthly_vehicle_cost").fill("620");
  await page.getByTestId("financing-offer-name").fill(name);
  await page.getByTestId("financing-submit").click();
  await expect(page.getByTestId("financing-result")).toBeVisible();
}


if (externalEnvironment) {
  test("homologacao navega sem expor login e identifica o modo demonstrativo", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("public-demo-banner")).toBeVisible();
    await expect(page.getByText("Entrar como administrador")).toHaveCount(0);
    await page.getByTestId("nav-financing").click();
    await expect(page.getByTestId("financing-page")).toBeVisible();
    await page.getByTestId("nav-recommendations").click();
    await expect(page.getByTestId("recommendation-form")).toBeVisible();
  });

  test("homologacao calcula recomendacao sem persistir dados", async ({ page }) => {
    await calculateRecommendation(page);
    await expect(
      page.getByTestId("recommendation-results").locator("article").first(),
    ).toBeVisible();
  });

  test("homologacao calcula financiamento direto", async ({ page }) => {
    await openFinancing(page);
    await calculateFinancing(page, "Homologacao A", 36);
    await expect(page.getByTestId("financing-regular-installment")).toContainText("R$");
  });

  test("homologacao marca resultado alterado como desatualizado", async ({ page }) => {
    await calculateRecommendation(page);
    await page.getByTestId("recommendation-back-review").click();
    await page.getByTestId("recommendation-back-advanced").click();
    await page.getByTestId("recommendation-back-priorities").click();
    await page.getByTestId("recommendation-budget").fill("210000");
    await expect(page.getByTestId("recommendation-stale-warning")).toBeVisible();
  });

  test("homologacao compara dois cenarios financeiros", async ({ page }) => {
    await openFinancing(page);
    await calculateFinancing(page, "Homologacao A", 36);
    await page.getByTestId("add-financing-comparison").click();
    await calculateFinancing(page, "Homologacao B", 48);
    await page.getByTestId("add-financing-comparison").click();
    await page.getByTestId("compare-financing-scenarios").click();
    await expect(page.getByTestId("financing-comparison")).toBeVisible();
  });

  test("homologacao bloqueia escrita persistente e mantem calculos sem estado", async ({ request }) => {
    const health = await request.get(`${apiUrl}/health`);
    expect(health.status()).toBe(200);
    expect((await health.json()).public_demo_mode).toBe(true);

    const blocked = await request.post(`${apiUrl}/users`, {
      data: {
        name: "Teste descartavel",
        email: "blocked@example.test",
      },
    });
    expect(blocked.status()).toBe(403);
    expect((await blocked.json()).detail.code).toBe("demo_read_only");

    const recommendation = await request.post(`${apiUrl}/recommendations`, {
      data: {
        budget: 200000,
        monthly_limit: 3500,
        use_case: "cidade",
        recommendation_strategy: "best_within_budget",
      },
    });
    expect(recommendation.status()).toBe(200);
  });
}
