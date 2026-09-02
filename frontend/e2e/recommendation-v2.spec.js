import { expect, test } from "playwright/test";

async function reachReview(page, { budget = "90000", monthlyLimit = "1800" } = {}) {
  await page.getByTestId("recommendation-next-need").click();
  await page.getByTestId("recommendation-budget").fill(budget);
  await page.getByTestId("recommendation-monthly-limit").fill(monthlyLimit);
  await page.getByTestId("recommendation-next-budget").click();
  await page.getByTestId("recommendation-strategy").selectOption("cost_benefit");
  await page.getByTestId("recommendation-monthly-mileage").fill("1000");
  await page.getByTestId("recommendation-fuel-price").fill("6");
  await page.getByTestId("recommendation-next-priorities").click();
  await page.getByTestId("recommendation-next-advanced").click();
}

test("fluxo guiado volta sem perder respostas e calcula uma recomendação válida", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("recommendation-next-need").click();
  await page.getByTestId("recommendation-budget").fill("84500");
  await page.getByTestId("recommendation-next-budget").click();
  await page.getByTestId("recommendation-back-priorities").click();
  await expect(page.getByTestId("recommendation-budget")).toHaveValue("84500");
  await page.getByTestId("recommendation-next-budget").click();
  await page.getByTestId("recommendation-next-priorities").click();
  await page.getByTestId("recommendation-next-advanced").click();
  await expect(page.getByText("Seu perfil está pronto")).toBeVisible();
  await page.getByTestId("recommendation-submit").click();
  await expect(page.getByTestId("recommendation-results")).toBeVisible();
  await page.getByRole("button", { name: "Detalhes" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("validação final retorna à etapa que precisa de correção", async ({ page }) => {
  await page.goto("/");
  await reachReview(page, { budget: "" });
  await page.getByTestId("recommendation-submit").click();
  await expect(page.getByText("Quanto cabe na sua decisão?")).toBeVisible();
  await expect(page.getByText("Orçamento é obrigatório.")).toBeVisible();
});

test("loading preserva contexto e usa skeleton até o backend responder", async ({ page }) => {
  await page.route("**/recommendations?envelope=true", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 300));
    await route.continue();
  });
  await page.goto("/");
  await reachReview(page);
  await page.getByTestId("recommendation-submit").click();
  await expect(page.getByTestId("recommendation-state-loading")).toBeVisible();
  await expect(page.locator(".recommendation-skeleton")).toHaveCount(3);
  await expect(page.getByTestId("recommendation-results")).toBeVisible();
});

test("layout essencial não gera overflow em desktop, tablet ou celular", async ({ page }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 768, height: 1024 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow).toBe(false);
    await expect(page.getByRole("heading", { name: /Um carro que faz sentido/ })).toBeVisible();
  }
});

test("menu móvel expõe navegação e mantém alvo de toque acessível", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const menu = page.locator('button[aria-controls="primary-navigation"]');
  await expect(menu).toHaveAccessibleName("Menu");
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  const collapsedBox = await menu.boundingBox();
  expect(collapsedBox).not.toBeNull();
  expect(collapsedBox.width).toBeGreaterThanOrEqual(44);
  expect(collapsedBox.height).toBeGreaterThanOrEqual(44);
  await menu.click();
  await expect(menu).toHaveAccessibleName("Fechar");
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("nav-financing")).toBeVisible();
  const expandedBox = await menu.boundingBox();
  expect(expandedBox).not.toBeNull();
  expect(expandedBox.width).toBeGreaterThanOrEqual(44);
  expect(expandedBox.height).toBeGreaterThanOrEqual(44);
});
