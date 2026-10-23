import { expect, test } from "playwright/test";
import { expandTransport } from "../src/api/compactTransport.js";

const RESPONSIVE_VIEWPORTS = [
  { width: 320, height: 568 },
  { width: 360, height: 800 },
  { width: 390, height: 844 },
  { width: 412, height: 915 },
  { width: 600, height: 960 },
  { width: 768, height: 1024 },
  { width: 1024, height: 768 },
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
];

async function responsiveAudit(page) {
  return page.evaluate(() => {
    const visible = (element) => element instanceof HTMLElement && !element.hidden && element.getClientRects().length > 0;
    const columns = (selector) => {
      const element = [...document.querySelectorAll(selector)].find(visible);
      if (!element) return null;
      const value = getComputedStyle(element).gridTemplateColumns;
      return value === "none" ? 1 : value.split(" ").filter(Boolean).length;
    };
    const buttons = [...document.querySelectorAll(".recommendation-builder button")].filter(visible);
    const formControls = [...document.querySelectorAll(".recommendation-builder input:not([type='hidden']), .recommendation-builder select")].filter(visible);
    const box = (element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, left: rect.left, right: rect.right, width: rect.width, height: rect.height };
    };
    const horizontalCss = (element) => {
      const style = getComputedStyle(element);
      return Object.fromEntries([
        "width", "min-width", "max-width", "height", "min-height", "box-sizing",
        "margin-left", "margin-right", "padding-left", "padding-right",
        "border-left-width", "border-right-width", "font-family", "font-size",
        "font-weight", "line-height", "appearance", "overflow-x", "overflow-y",
        "white-space", "text-overflow", "display", "grid-template-columns", "scrollbar-gutter",
      ].map((property) => [property, style.getPropertyValue(property)]));
    };
    const widthLayers = [
      "html", "body", ".app-shell", ".workspace-v2", ".content", ".recommendation-workbench",
      ".recommendation-builder", ".recommendation-wizard", ".wizard-step:not([hidden])",
      ".multifactor-profile", ".multifactor-grid", 'label[for="multifactor_price_mode"]', "#multifactor_price_mode",
    ].flatMap((selector) => {
      const element = [...document.querySelectorAll(selector)].find(visible);
      return element ? [{
        selector, box: box(element), clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth, offsetWidth: element.offsetWidth, css: horizontalCss(element),
      }] : [];
    });
    const controlMetrics = formControls.map((control) => {
      const container = control.closest("label") || control.parentElement;
      return {
        locator: control.id ? `#${control.id}` : `[data-testid="${control.dataset.testid}"]`,
        tag: control.tagName,
        type: control.type,
        id: control.id || null,
        name: control.getAttribute("name"),
        label: control.closest("label")?.querySelector(".field-label")?.textContent.trim() || null,
        value: control.value,
        selectedText: control instanceof HTMLSelectElement ? control.selectedOptions[0]?.textContent.trim() : null,
        box: box(control),
        containerBox: box(container),
        clientWidth: control.clientWidth,
        scrollWidth: control.scrollWidth,
        offsetWidth: control.offsetWidth,
        fits: control.scrollWidth <= control.clientWidth + 1,
        fitsHeight: !(control instanceof HTMLSelectElement) || control.scrollHeight <= control.clientHeight + 1,
        css: horizontalCss(control),
        containerCss: {
          width: getComputedStyle(container).width,
          display: getComputedStyle(container).display,
          gridTemplateColumns: getComputedStyle(container).gridTemplateColumns,
        },
      };
    });
    const internalScrollers = [...document.querySelectorAll(".recommendation-builder, .recommendation-wizard, .wizard-step:not([hidden]), .multifactor-profile")]
      .filter(visible)
      .filter((element) => {
        const overflow = getComputedStyle(element).overflowY;
        return ["auto", "scroll"].includes(overflow) && element.scrollHeight > element.clientHeight + 1;
      })
      .map((element) => element.className || element.tagName);
    const ellipsized = [...document.querySelectorAll(".recommendation-builder *")]
      .filter(visible)
      .filter((element) => getComputedStyle(element).textOverflow === "ellipsis")
      .map((element) => element.className || element.tagName);
    const brokenButtons = buttons.filter((button) => {
      const style = getComputedStyle(button);
      return style.wordBreak === "break-all" || style.overflowWrap === "anywhere";
    }).map((button) => button.textContent.trim());
    const builder = document.querySelector(".recommendation-builder")?.getBoundingClientRect();
    const workbench = document.querySelector(".recommendation-workbench")?.getBoundingClientRect();
    const checkbox = document.querySelector(".multifactor-toggle");
    const checkboxBox = visible(checkbox) ? checkbox.getBoundingClientRect() : null;
    const currentStep = document.querySelector(".wizard-progress-copy strong")?.textContent.trim();
    const stepLabels = [...document.querySelectorAll(".wizard-step-name")].map((item) => item.textContent.trim());
    const multifactor = document.querySelector(".multifactor-profile");
    const multifactorStyle = multifactor && getComputedStyle(multifactor);
    const multifactorContentWidth = visible(multifactor) ? multifactor.clientWidth - parseFloat(multifactorStyle.paddingLeft) - parseFloat(multifactorStyle.paddingRight) : null;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    const unreadableSelects = formControls.filter((control) => control instanceof HTMLSelectElement).filter((control) => {
      const style = getComputedStyle(control);
      context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const label = control.selectedOptions[0]?.textContent.trim() || "";
      const usableWidth = control.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - 20;
      const summary = control.closest("label")?.querySelector(".selected-option");
      return context.measureText(label).width > usableWidth && !(visible(summary) && summary.textContent.trim() === label);
    }).map((control) => control.id);
    const buttonsOutsideContainer = buttons.filter((button) => {
      const box = button.getBoundingClientRect();
      const parent = button.parentElement.getBoundingClientRect();
      return box.left < parent.left - 1 || box.right > parent.right + 1 || button.scrollWidth > button.clientWidth;
    }).map((button) => button.textContent.trim());
    const misalignedControls = [...document.querySelectorAll(".wizard-field-grid, .multifactor-grid")].filter(visible).flatMap((grid) => {
      const fields = [...grid.querySelectorAll(":scope > label")];
      return fields.slice(1).filter((field, index) => {
        const previous = fields[index];
        const a = previous.getBoundingClientRect();
        const b = field.getBoundingClientRect();
        return Math.abs(a.top - b.top) < 1 && Math.abs(previous.querySelector("input,select").getBoundingClientRect().top - field.querySelector("input,select").getBoundingClientRect().top) > 1;
      }).map((field) => field.htmlFor);
    });
    return {
      viewportClientWidth: document.documentElement.clientWidth,
      viewport: { innerWidth, innerHeight, clientWidth: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth, visualWidth: visualViewport?.width, visualScale: visualViewport?.scale, devicePixelRatio },
      builderWidth: builder?.width ?? null,
      widthLayers,
      documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      workbenchCentered: workbench ? Math.abs((workbench.left + workbench.right) / 2 - document.documentElement.clientWidth / 2) <= 2 : false,
      builderOverflow: builder ? Math.max(0, builder.right - document.documentElement.clientWidth, -builder.left) : -1,
      internalScrollers,
      ellipsized,
      brokenButtons,
      buttonsOutsideContainer,
      unreadableSelects,
      misalignedControls,
      multifactorContentWidth,
      controlMetrics,
      buttonTargetsValid: buttons.every((button) => {
        const box = button.getBoundingClientRect();
        return box.width >= 44 && box.height >= 44;
      }),
      buttonPresentationValid: buttons.every((button) => button.getBoundingClientRect().height >= 48 && parseFloat(getComputedStyle(button).fontSize) >= 14),
      controlsFit: controlMetrics.every((control) => control.fits),
      selectTextFitsHeight: controlMetrics.every((control) => control.fitsHeight),
      controlsAssociated: formControls.every((control) => control.closest("label") || (control.id && document.querySelector(`label[for="${CSS.escape(control.id)}"]`))),
      checkboxTargetValid: !checkboxBox || (checkboxBox.width >= 44 && checkboxBox.height >= 44),
      fieldColumns: columns(".wizard-field-grid"),
      multifactorColumns: columns(".multifactor-grid"),
      reviewColumns: columns(".review-grid"),
      actionColumns: columns(".wizard-actions"),
      actionWidths: [...document.querySelectorAll(".wizard-step:not([hidden]) .wizard-actions button")].map((button) => button.getBoundingClientRect().width),
      currentStep,
      stepLabels,
    };
  });
}

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

async function reachResults(page) {
  await page.goto("/");
  await reachReview(page);
  await page.getByTestId("recommendation-submit").click();
  await expect(page.getByTestId("recommendation-results")).toBeVisible();
}

async function openFirstRecommendationDetails(page) {
  await reachResults(page);
  await page.getByRole("button", { name: "Detalhes" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
}

test("fluxo guiado volta sem perder respostas e calcula uma recomendação válida", async ({ page }) => {
  const personalSummaryRequests = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/reports/financial-summary") {
      personalSummaryRequests.push(request.url());
    }
  });
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
  expect(personalSummaryRequests).toEqual([]);
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

for (const viewport of RESPONSIVE_VIEWPORTS) {
  test(`jornada responsiva ${viewport.width}x${viewport.height}: campos, etapas e ações`, async ({ page }, testInfo) => {
    const measurements = [];
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Encontre o veículo certo para você." })).toBeVisible();
    const assertLayout = (audit, stage) => {
      expect(audit.documentFits, `${viewport.width}px/${stage}: documento não cabe`).toBe(true);
      expect(audit.workbenchCentered, `${viewport.width}px/${stage}: workbench não centralizado`).toBe(true);
      expect(audit.builderOverflow, `${viewport.width}px/${stage}: builder fora da viewport`).toBeLessThanOrEqual(1);
      expect(audit.internalScrollers, `${viewport.width}px/${stage}: scroll interno`).toEqual([]);
      expect(audit.ellipsized, `${viewport.width}px/${stage}: texto com reticências`).toEqual([]);
      expect(audit.brokenButtons, `${viewport.width}px/${stage}: palavra quebrada em botão`).toEqual([]);
      expect(audit.buttonsOutsideContainer, `${viewport.width}px/${stage}: botão fora do contêiner`).toEqual([]);
      expect(audit.unreadableSelects, `${viewport.width}px/${stage}: opção selecionada ilegível`).toEqual([]);
      expect(audit.misalignedControls, `${viewport.width}px/${stage}: controles desalinhados`).toEqual([]);
      expect(audit.buttonTargetsValid, `${viewport.width}px/${stage}: alvo menor que 44px`).toBe(true);
      expect(audit.buttonPresentationValid, `${viewport.width}px/${stage}: altura/fonte insuficiente`).toBe(true);
      expect(audit.controlsFit, `${viewport.width}px/${stage}: controle truncado; ${JSON.stringify(audit.controlMetrics.filter((control) => !control.fits))}`).toBe(true);
      expect(audit.selectTextFitsHeight, `${viewport.width}px/${stage}: opção cortada verticalmente`).toBe(true);
      expect(audit.controlsAssociated, `${viewport.width}px/${stage}: controle sem label`).toBe(true);
      expect(audit.checkboxTargetValid, `${viewport.width}px/${stage}: área do checkbox menor que 44px`).toBe(true);
      expect(audit.currentStep).not.toMatch(/\.\.\.$/);
      expect(audit.stepLabels).toEqual(["Necessidade", "Orçamento", "Prioridades", "Ajustes opcionais", "Revisão"]);
      if (viewport.width <= 360) {
        expect(audit.builderWidth, `${viewport.width}px/${stage}: gutters excessivos no card`).toBeGreaterThanOrEqual(audit.viewportClientWidth - 24);
        if (audit.multifactorContentWidth !== null) {
          expect(audit.multifactorContentWidth, `${viewport.width}px/${stage}: paddings aninhados comprimem os controles`).toBeGreaterThanOrEqual(audit.viewportClientWidth - 80);
        }
      }
      if (audit.multifactorContentWidth !== null && audit.multifactorContentWidth < 640 && audit.multifactorColumns !== null) {
        expect(audit.multifactorColumns).toBe(1);
      }
      if (viewport.width <= 639) {
        if (audit.fieldColumns !== null) expect(audit.fieldColumns).toBe(1);
        if (audit.multifactorColumns !== null) expect(audit.multifactorColumns).toBe(1);
        if (audit.reviewColumns !== null) expect(audit.reviewColumns).toBe(1);
        expect(audit.actionColumns).toBe(1);
        expect(Math.max(...audit.actionWidths) - Math.min(...audit.actionWidths)).toBeLessThanOrEqual(1);
      }
    };
    const inspect = async (stage) => {
      const audit = await responsiveAudit(page);
      if (stage === "multifator") {
        audit.priceModeAccessibleSnapshot = await page.locator("#multifactor_price_mode").ariaSnapshot();
      }
      measurements.push({ stage, viewport, ...audit });
      await page.screenshot({ path: testInfo.outputPath(`responsive-${viewport.width}x${viewport.height}-${stage}.png`), fullPage: true });
      await testInfo.attach(`responsive-measurements-${stage}`, { body: JSON.stringify({ stage, viewport, ...audit }, null, 2), contentType: "application/json" });
      for (const control of audit.controlMetrics.filter((item) => !item.fits)) {
        const field = page.locator(control.locator).locator("..");
        await field.screenshot({ path: testInfo.outputPath(`responsive-${viewport.width}-${stage}-${control.locator.replace(/[^a-z0-9_-]/gi, "_")}.png`) });
      }
    };

    await inspect("necessidade");
    await page.getByTestId("recommendation-next-need").click();
    await page.getByTestId("recommendation-budget").fill("90000");
    await page.getByTestId("recommendation-monthly-limit").fill("1800");
    await inspect("orcamento");
    await page.getByTestId("recommendation-next-budget").click();
    await page.getByTestId("recommendation-monthly-mileage").fill("1000");
    await page.getByTestId("recommendation-fuel-price").fill("6");
    await inspect("prioridades");
    await page.getByTestId("recommendation-next-priorities").click();
    await page.getByTestId("multifactor-enabled").check();
    await inspect("multifator");
    await expect(page.locator("#multifactor_price_mode")).toHaveAccessibleName("Origem do preço");
    await expect(page.locator("#multifactor_price_mode")).toHaveValue("anp");
    // The narrow layout must keep a native, labelled and keyboard-operable
    // control, not merely make the overflow metric pass.
    await page.locator("#multifactor_price_mode").selectOption("manual");
    await expect(page.locator("#multifactor_manual_fuel_price_brl")).toBeVisible();
    await page.locator("#multifactor_price_mode").press("ArrowUp");
    await expect(page.locator("#multifactor_price_mode")).toHaveValue("anp");
    await expect(page.locator("#multifactor_manual_fuel_price_brl")).toHaveCount(0);
    await page.getByTestId("recommendation-next-advanced").click();
    await inspect("revisao");
    await page.getByTestId("recommendation-back-review").click();
    await expect(page.getByTestId("multifactor-enabled")).toBeChecked();
    await expect(page.locator("#multifactor_price_mode")).toHaveValue("anp");
    await page.getByTestId("recommendation-back-advanced").click();
    await expect(page.getByTestId("recommendation-monthly-mileage")).toHaveValue("1000");
    await testInfo.attach("responsive-measurements", { body: JSON.stringify(measurements, null, 2), contentType: "application/json" });
    // Capture every stage before asserting, without turning any failure into a pass.
    for (const { stage, ...audit } of measurements) assertLayout(audit, stage);
  });
}

test("cards, ações e botões preservam largura útil sem overflow", async ({ page }, testInfo) => {
  await reachResults(page);
  for (const viewport of RESPONSIVE_VIEWPORTS) {
    await page.setViewportSize(viewport);
    const audit = await page.evaluate(() => {
      const grid = document.querySelector(".recommendation-grid");
      const gridBox = grid.getBoundingClientRect();
      const targets = [
        document.documentElement,
        ...document.querySelectorAll(".vehicle-card, .vehicle-card *"),
      ];
      return {
        columns: getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean).length,
        workbenchWidth: document.querySelector('.recommendation-workbench').getBoundingClientRect().width,
        workbenchColumns: getComputedStyle(document.querySelector('.recommendation-workbench')).gridTemplateColumns.split(' ').length,
        formWidth: document.querySelector('.recommendation-builder').getBoundingClientRect().width,
        shellWidth: document.querySelector('.workspace-v2').getBoundingClientRect().width,
        clientWidth: document.documentElement.clientWidth,
        globalScale: ['html', 'body', '.app-shell', '.workspace-v2', '.recommendation-workbench'].map((selector) => {
          const css = getComputedStyle(document.querySelector(selector));
          return { selector, transform: css.transform, zoom: css.zoom, fontSize: css.fontSize };
        }),
        gridWidth: gridBox.width,
        cardWidths: [...document.querySelectorAll(".vehicle-card")].map((card) => card.getBoundingClientRect().width),
        overflow: targets.filter((element) => element.scrollWidth > element.clientWidth + 1).map((element) => element.className || element.tagName),
        buttons: [...document.querySelectorAll(".card-actions button")].map((button) => ({
          width: button.getBoundingClientRect().width,
          height: button.getBoundingClientRect().height,
          wordBreak: getComputedStyle(button).wordBreak,
          overflowWrap: getComputedStyle(button).overflowWrap,
          textOverflow: getComputedStyle(button).textOverflow,
          fontSize: parseFloat(getComputedStyle(button).fontSize),
        })),
      };
    });
    await testInfo.attach(`ranking-layout-${viewport.width}`, { body: JSON.stringify(audit, null, 2), contentType: 'application/json' });
    await page.screenshot({ path: testInfo.outputPath(`ranking-${viewport.width}.png`), fullPage: true });
    expect(audit.columns).toBeGreaterThanOrEqual(1);
    expect(audit.cardWidths.every((width) => width >= Math.min(360, audit.gridWidth) - 1)).toBe(true);
    expect(audit.workbenchColumns).toBe(audit.workbenchWidth < 1406 ? 1 : 2);
    if (audit.workbenchColumns === 1) expect(audit.formWidth).toBeCloseTo(audit.workbenchWidth, 0);
    if (viewport.width >= 1920) expect(audit.shellWidth).toBeGreaterThanOrEqual(audit.clientWidth * 0.95);
    expect(audit.globalScale.every(({ transform, zoom, fontSize }) => transform === 'none' && Number(zoom) === 1 && parseFloat(fontSize) >= 16)).toBe(true);
    expect(audit.buttons.every(({ fontSize }) => fontSize >= 16)).toBe(true);
    expect(audit.overflow).toEqual([]);
    expect(audit.buttons.every(({ width, height, wordBreak, overflowWrap, textOverflow }) => width >= 44 && height >= 44 && wordBreak !== "break-all" && overflowWrap !== "anywhere" && textOverflow !== "ellipsis")).toBe(true);
  }
});

test("seletor carrega e seleciona um veículo elegível", async ({ page }) => {
  let releaseCatalog;
  const catalogGate = new Promise((resolve) => { releaseCatalog = resolve; });
  await page.route("**/api/v1/integrated-vehicle-cost/vehicles?*", async (route) => {
    await catalogGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          { vehicle_sk: 42, brand_name: "Toyota", model_name: "Etios XLS", model_year: 2018, version_name: "1.5" },
          { vehicle_sk: 43, brand_name: "Chevrolet", model_name: "Onix LT", model_year: 2021, version_name: "1.0" },
        ],
        total: 2,
      }),
    });
  });
  await openFirstRecommendationDetails(page);
  const selector = page.getByTestId("simulation-vehicle-sk");
  await expect(selector).toContainText("Carregando veículos...");
  await expect(selector).toBeDisabled();
  releaseCatalog();
  await expect(selector).toBeEnabled();
  await expect(selector).toHaveValue("42");
  await selector.selectOption("43");
  await expect(selector).toHaveValue("43");
  await expect(page.getByTestId("simulation-selected-vehicle")).toContainText("Onix LT");
  await expect(page.getByTestId("simulation-selection-scope")).toContainText("não vincula nem substitui Toyota Etios XLS");
});

test("seletor distingue lista vazia de erro e permite recuperação", async ({ page }) => {
  let responseMode = "error";
  await page.route("**/api/v1/integrated-vehicle-cost/vehicles?*", async (route) => {
    if (responseMode === "error") {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: { code: "integrated_gold_unavailable", message: "eligible integrated Gold dataset is unavailable" } }) });
      return;
    }
    if (responseMode === "empty") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ vehicle_sk: 51, brand_name: "Honda", model_name: "Fit EX", model_year: 2017 }], total: 1 }) });
  });
  await openFirstRecommendationDetails(page);
  await expect(page.getByText("Não foi possível carregar os veículos para simulação. Tente novamente ou continue informando os valores manualmente.")).toBeVisible();
  await expect(page.getByText(/eligible integrated Gold dataset/i)).toHaveCount(0);
  responseMode = "empty";
  await page.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(page.getByText("Nenhum veículo está disponível para simulação neste momento.")).toBeVisible();
  responseMode = "success";
  await page.getByRole("button", { name: "Tentar novamente" }).click();
  await expect(page.getByTestId("simulation-vehicle-sk")).toBeEnabled();
  await page.getByTestId("simulation-vehicle-sk").selectOption("51");
  await expect(page.getByTestId("simulation-selected-vehicle")).toContainText("Fit EX");
});

test("interface usa português revisado e não exibe consentimento fixo de orçamento", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Informe seu orçamento, sua rotina e suas prioridades. O SIGRA compara as opções e explica cada recomendação.")).toBeVisible();
  await expect(page.getByText(/Autorizo explicitamente a análise de orçamento acima/i)).toHaveCount(0);
  await page.getByTestId("recommendation-next-need").click();
  await page.getByTestId("recommendation-budget").fill("250000");
  await page.getByTestId("recommendation-next-budget").click();
  await expect(page.getByRole("heading", { name: "Defina a prioridade da análise" })).toBeVisible();
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

test("modal sem cobertura não repete aviso e mantém fechar acessível em todas as larguras", async ({ page }, testInfo) => {
  // Synthetic availability belongs only to this UI test, never to production data.
  await page.route('**/recommendations?envelope=true', async (route) => {
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    const wire = await response.json();
    const data = expandTransport(wire);
    expect(Array.isArray(data.recommendations), "expanded response must contain the real recommendation array").toBe(true);
    expect(data.recommendations.length).toBeGreaterThan(0);
    await testInfo.attach("recommendation-wire-contract", {
      body: JSON.stringify({ wireKeys: Object.keys(wire), transport: wire.transport,
        expandedRecommendationCount: data.recommendations.length }),
      contentType: "application/json",
    });
    data.recommendations = data.recommendations.map((item) => ({ ...item, multifactor: {
      enabled: true, status: 'unavailable', final_score: null,
      reason_code: 'GOLD_IDENTITY_NOT_FOUND', identity_diagnostic: { rejection_reason: 'coverage_absent' },
    } }));
    const headers = { ...response.headers() };
    // The expanded, modified JSON has a different byte length from the wire
    // dictionary. Let Playwright compute Content-Length for the new body.
    delete headers["content-length"];
    await route.fulfill({ response, headers, json: data });
  });
  await page.route('**/api/v1/integrated-vehicle-cost/vehicles?*', (route) => route.fulfill({ json: {
    items: [{ vehicle_sk: 42, brand_name: 'Toyota', model_name: 'ETIOS XLS 1.5 Flex 5p Aut.', model_year: 2018 }], total: 1,
  } }));
  await reachResults(page);
  await expect(page.getByTestId('multifactor-summary')).toHaveCount(1);
  await expect(page.getByTestId('multifactor-summary')).toContainText('0 de 34');
  await expect(page.getByRole('heading', { name: 'Comparação multifator para o cenário informado' })).toHaveCount(0);
  const uno = page.locator('.vehicle-card').filter({ has: page.getByRole('heading', { name: 'Fiat Uno Attractive', exact: true }) });
  for (const viewport of RESPONSIVE_VIEWPORTS) {
    await page.setViewportSize(viewport);
    await uno.getByRole('button', { name: 'Detalhes', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: 'Fiat Uno Attractive', exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText('Comparação personalizada indisponível', { exact: true })).toHaveCount(0);
    await expect(dialog.getByText(/veículo correspondente/)).toHaveCount(0);
    const selector = dialog.getByTestId('simulation-vehicle-sk');
    await expect(selector).toHaveAccessibleName('Veículo para simulação');
    await expect(selector).toBeEnabled();
    await expect(selector).toHaveValue('');
    await page.screenshot({ path: testInfo.outputPath(`modal-top-${viewport.width}.png`), fullPage: true });
    await selector.selectOption('42');
    await expect(selector).toHaveValue('42');
    await selector.press('ArrowUp');
    await expect(selector).toHaveValue('');
    await selector.press('ArrowDown');
    await expect(selector).toHaveValue('42');
    await dialog.getByTestId('simulation-selection-scope').scrollIntoViewIfNeeded();
    await expect(dialog.getByTestId('simulation-selection-scope')).toBeVisible();
    await expect(dialog.getByTestId('simulation-selection-scope')).toContainText('não vincula nem substitui Fiat Uno Attractive');
    await expect(dialog.getByTestId('simulation-selected-vehicle')).toContainText('ETIOS XLS');
    const audit = await dialog.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const close = element.querySelector('.modal-close').getBoundingClientRect();
      const scrollers = [...element.querySelectorAll('*'), element].filter((node) => ['auto', 'scroll'].includes(getComputedStyle(node).overflowY) && node.scrollHeight > node.clientHeight + 1);
      const overflow = [...element.querySelectorAll('*'), element, document.documentElement].filter((node) => node.clientWidth && node.scrollWidth > node.clientWidth + 1);
      return { width: innerWidth, clientWidth: document.documentElement.clientWidth, visualWidth: visualViewport.width, scale: visualViewport.scale, devicePixelRatio,
        box: { left: box.left, right: box.right, height: box.height }, close: { top: close.top, bottom: close.bottom, width: close.width, height: close.height },
        scrollers: scrollers.map((node) => node.className), overflow: overflow.map((node) => node.className || node.tagName),
        overflowMetrics: overflow.map((node) => ({ tag: node.tagName, testId: node.dataset.testid,
          clientWidth: node.clientWidth, scrollWidth: node.scrollWidth,
          boxWidth: node.getBoundingClientRect().width, parentWidth: node.parentElement.clientWidth,
          minWidth: getComputedStyle(node).minWidth,
          selected: node instanceof HTMLSelectElement ? node.selectedOptions[0]?.textContent : null })),
        clippedSelects: [...element.querySelectorAll('select')].filter((node) => (
          node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1
        )).map((node) => node.dataset.testid),
        bodyOverflowY: getComputedStyle(document.body).overflowY,
        fieldColumns: getComputedStyle(element.querySelector('.vehicle-simulation-grid')).gridTemplateColumns.split(' ').length,
      };
    });
    await testInfo.attach(`modal-layout-${viewport.width}`, { body: JSON.stringify(audit, null, 2), contentType: 'application/json' });
    await page.screenshot({ path: testInfo.outputPath(`modal-simulation-${viewport.width}.png`), fullPage: true });
    expect(audit.scrollers).toEqual(['modal-body']);
    expect(audit.overflow, JSON.stringify(audit.overflowMetrics)).toEqual([]);
    expect(audit.clippedSelects).toEqual([]);
    expect(audit.box.left).toBeGreaterThanOrEqual(0);
    expect(audit.box.right).toBeLessThanOrEqual(audit.clientWidth);
    expect(audit.box.height).toBeLessThanOrEqual(viewport.height);
    expect(audit.close.top).toBeGreaterThanOrEqual(0);
    expect(audit.close.bottom).toBeLessThanOrEqual(viewport.height);
    expect(audit.close.width).toBeGreaterThanOrEqual(44);
    expect(audit.close.height).toBeGreaterThanOrEqual(44);
    expect(audit.bodyOverflowY).toBe('hidden');
    if (viewport.width <= 390) expect(audit.fieldColumns).toBe(1);
    await dialog.getByRole('button', { name: 'Fechar', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByTestId('multifactor-summary')).toHaveCount(1);
    await expect(uno.getByText('Ranking multifator')).toHaveCount(0);
  }
});
