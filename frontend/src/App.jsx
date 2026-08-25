import React, { useEffect, useMemo, useRef, useState } from "react";
import { requestRecommendations } from "./api/sigraApi.js";
import RecommendationDetails from "./features/recommendations/RecommendationDetails.jsx";
import RecommendationForm from "./features/recommendations/RecommendationForm.jsx";
import RecommendationPage from "./features/recommendations/RecommendationPage.jsx";
import FinancingPage from "./features/financing/FinancingPage.jsx";
import { isLatestRequest, shouldMarkResultsStale, validateRecommendationProfile } from "./features/recommendations/recommendationValidation.js";
import { MULTIFACTOR_DEFAULT_WEIGHTS, resetMultifactorWeightFields } from "./features/recommendations/multifactorRecommendationModel.js";
import { API_URL, PUBLIC_DEMO_MODE } from "./config/runtime.js";


function formatCurrency(value) {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
}

function formatPercent(value) {
  return `${Number(value || 0).toLocaleString("pt-BR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })}%`;
}

function handleCarImageError(event) {
  event.currentTarget.style.display = "none";
  event.currentTarget.parentElement?.classList.add("image-failed");
}

function purchaseSourceButtons(sources = [], bestSource = null) {
  if (!Array.isArray(sources) || sources.length === 0) return null;
  const alternativeSources = bestSource
    ? sources.filter((source) => source.url !== bestSource.url)
    : sources;
  return (
    <>
    {bestSource?.url && (
      <a className="best-source-link" href={bestSource.url} target="_blank" rel="noreferrer">
        Melhor opcao: {bestSource.name}
      </a>
    )}
    <div className="source-links">
      {alternativeSources.map((source) => (
        <a key={`${source.name}-${source.url}`} href={source.url} target="_blank" rel="noreferrer">
          {source.name}
        </a>
      ))}
    </div>
    </>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState("recommendations");
  const [theme, setTheme] = useState(() => localStorage.getItem("sigra-theme") || "light");
  const [currentUser, setCurrentUser] = useState(null);
  const [loginRole, setLoginRole] = useState("user");
  const [loginForm, setLoginForm] = useState({
    email: "",
    password: "",
  });
  const [loginError, setLoginError] = useState("");
  const [profile, setProfile] = useState({
    vehicle_type: "car",
    budget: "70000",
    monthly_limit: "1200",
    use_case: "cidade",
    recommendation_strategy: "cost_benefit",
    monthly_mileage: "1000",
    fuel_price: "6",
    multifactor_enabled: false,
    allow_budget_above_200k: false,
    multifactor_monthly_distance_km: "1000",
    multifactor_city_percentage: "50",
    multifactor_highway_percentage: "50",
    multifactor_fuel_strategy: "gasoline_c_common",
    multifactor_price_mode: "anp",
    multifactor_manual_fuel_price_brl: "",
    multifactor_horizon_months: "12",
    multifactor_state_code: "SP",
    multifactor_municipality: "",
    multifactor_reference_week_start: "",
    multifactor_city_consumption_km_l: "",
    multifactor_highway_consumption_km_l: "",
    ...Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([code, value]) => [`weight_${code}`, value])),
  });
  const [recommendations, setRecommendations] = useState([]);
  const [recommendationMetadata, setRecommendationMetadata] = useState(null);
  const [recommendationErrors, setRecommendationErrors] = useState({});
  const [recommendationError, setRecommendationError] = useState("");
  const [recommendationLoading, setRecommendationLoading] = useState(false);
  const [recommendationStale, setRecommendationStale] = useState(false);
  const [recommendationHasCalculated, setRecommendationHasCalculated] = useState(false);
  const recommendationRequestId = useRef(0);
  const recommendationAbortController = useRef(null);
  const recommendationProfileVersion = useRef(0);
  const [vehicles, setVehicles] = useState([]);
  const [selectedIds, setSelectedIds] = useState([2, 4]);
  const [expenses, setExpenses] = useState([]);
  const [onlineQuery, setOnlineQuery] = useState("");
  const [onlineResults, setOnlineResults] = useState([]);
  const [partsAnalyses, setPartsAnalyses] = useState({});
  const [partsVehicleId, setPartsVehicleId] = useState("");
  const [selectedRecommendationDetails, setSelectedRecommendationDetails] = useState(null);
  const [showAllRecommendations, setShowAllRecommendations] = useState(false);
  const [summary, setSummary] = useState({
    total_expenses: 0,
    total_maintenance: 0,
    total_cost: 0,
    expenses_by_category: {},
    pending_maintenances: 0,
  });
  const [expenseForm, setExpenseForm] = useState({
    user_id: 1,
    vehicle_id: 1,
    category: "combustivel",
    amount: 250,
    expense_date: new Date().toISOString().slice(0, 10),
    description: "",
  });
  const [myCars, setMyCars] = useState([]);
  const [selectedUserVehicleId, setSelectedUserVehicleId] = useState("");
  const [vehicleHistory, setVehicleHistory] = useState(null);
  const [myCarForm, setMyCarForm] = useState({
    user_id: 1,
    vehicle_id: 1,
    year_model: 2021,
    current_km: 85000,
    purchase_km: 30000,
    purchase_date: new Date().toISOString().slice(0, 10),
    main_usage: "cidade",
    notes: "",
  });
  const [problemForm, setProblemForm] = useState({
    user_vehicle_id: "",
    problem_category: "suspensao",
    description: "Barulho ou falha observada durante o uso.",
    occurrence_km: 90000,
    repair_cost: 1200,
    severity: "media",
    occurrence_date: new Date().toISOString().slice(0, 10),
    resolved: false,
    notes: "",
  });
  const [consumptionForm, setConsumptionForm] = useState({
    user_vehicle_id: "",
    km_per_liter: 10.5,
    usage_type: "urbano",
    fuel_type: "flex",
    notes: "",
  });
  const [status, setStatus] = useState(
    PUBLIC_DEMO_MODE
      ? "Homologação acadêmica com dados demonstrativos."
      : "Modo visitante: simule recomendações sem cadastro.",
  );

  async function loadVehicles() {
    try {
      const response = await fetch(`${API_URL}/vehicles`);
      if (!response.ok) {
        throw new Error("Falha ao carregar veiculos");
      }
      const data = await response.json();
      setVehicles(data);
      if (data[0]) {
        setExpenseForm((current) => ({ ...current, vehicle_id: data[0].id }));
        setMyCarForm((current) => ({ ...current, vehicle_id: data[0].id, year_model: data[0].year }));
        setPartsVehicleId(data[0].id);
      }
      setStatus("Dados carregados da base demonstrativa.");
    } catch {
      setStatus("API indisponível. Não foi possível carregar a base de veículos.");
    }
  }

  async function runRecommendation(event) {
    event?.preventDefault?.();
    if (recommendationLoading) return;
    const validation = validateRecommendationProfile(profile);
    setRecommendationErrors(validation.errors);
    if (!validation.isValid) return;

    recommendationAbortController.current?.abort();
    const controller = new AbortController();
    recommendationAbortController.current = controller;
    const requestId = recommendationRequestId.current + 1;
    const profileVersion = recommendationProfileVersion.current;
    recommendationRequestId.current = requestId;
    setRecommendationLoading(true);
    setRecommendationError("");
    try {
      const data = await requestRecommendations(validation.payload, { signal: controller.signal });
      if (!isLatestRequest(requestId, recommendationRequestId.current)) return;
      setRecommendations(data.recommendations);
      setRecommendationMetadata(data);
      setRecommendationHasCalculated(true);
      setRecommendationStale(profileVersion !== recommendationProfileVersion.current);
      setSelectedRecommendationDetails(null);
      setStatus("Recomendação calculada pela API do SIGRA.");
    } catch (error) {
      if (error?.name === "AbortError" || !isLatestRequest(requestId, recommendationRequestId.current)) return;
      setRecommendationHasCalculated(true);
      setRecommendationError("Não foi possível calcular sua recomendação. Verifique a conexão com o serviço e tente novamente.");
      setRecommendationStale(recommendations.length > 0);
      setStatus("Serviço de recomendação indisponível.");
    } finally {
      if (isLatestRequest(requestId, recommendationRequestId.current)) setRecommendationLoading(false);
    }
  }

  async function loadOperationalData() {
    try {
      const [expensesResponse, summaryResponse] = await Promise.all([
        fetch(`${API_URL}/expenses`),
        fetch(`${API_URL}/reports/financial-summary`),
      ]);
      if (!expensesResponse.ok || !summaryResponse.ok) {
        throw new Error("Falha ao carregar dados operacionais");
      }
      setExpenses(await expensesResponse.json());
      setSummary(await summaryResponse.json());
    } catch {
      setExpenses([]);
    }
  }

  async function loadMyCarData(userId = currentUser?.id || 1) {
    if (!currentUser) {
      setMyCars([]);
      setVehicleHistory(null);
      return;
    }
    try {
      const response = await fetch(`${API_URL}/user-vehicles?user_id=${userId}`);
      if (!response.ok) {
        throw new Error("Falha ao carregar meu carro");
      }
      const data = await response.json();
      setMyCars(data);
      const selectedId = selectedUserVehicleId || data[0]?.id || "";
      setSelectedUserVehicleId(selectedId);
      setProblemForm((current) => ({ ...current, user_vehicle_id: selectedId }));
      setConsumptionForm((current) => ({ ...current, user_vehicle_id: selectedId }));
      if (selectedId) {
        await loadVehicleHistory(selectedId);
      }
    } catch {
      setMyCars([]);
      setStatus("Não foi possível carregar a área Meu carro.");
    }
  }

  async function loadVehicleHistory(userVehicleId) {
    if (!userVehicleId) return;
    try {
      const response = await fetch(`${API_URL}/user-vehicles/${userVehicleId}/history`);
      if (!response.ok) {
        throw new Error("Falha ao carregar historico");
      }
      setVehicleHistory(await response.json());
    } catch {
      setVehicleHistory(null);
    }
  }

  async function searchOnlineCars(event) {
    event.preventDefault();
    try {
      const response = await fetch(`${API_URL}/online-car-search?query=${encodeURIComponent(onlineQuery)}`);
      if (!response.ok) {
        throw new Error("Falha na busca online");
      }
      setOnlineResults(await response.json());
      setStatus("Busca online concluída.");
    } catch {
      setOnlineResults([]);
      setStatus("Não foi possível buscar carros online.");
    }
  }

  async function loadPartsAnalysis(vehicleId) {
    if (!vehicleId) return;
    try {
      const response = await fetch(`${API_URL}/vehicles/${vehicleId}/parts-analysis`);
      if (!response.ok) {
        throw new Error("Falha ao carregar analise de pecas");
      }
      const data = await response.json();
      setPartsAnalyses((current) => ({ ...current, [vehicleId]: data }));
      setStatus("Análise demonstrativa de peças carregada.");
    } catch {
      setStatus("Não foi possível carregar a análise de peças.");
    }
  }

  async function submitExpense(event) {
    event.preventDefault();
    if (!currentUser) {
      setStatus("Faça login para salvar dados e acompanhar seu histórico.");
      return;
    }
    try {
      const response = await fetch(`${API_URL}/expenses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...expenseForm,
          user_id: currentUser?.role === "admin" ? 1 : currentUser?.id || expenseForm.user_id,
          amount: Number(expenseForm.amount),
          vehicle_id: Number(expenseForm.vehicle_id),
        }),
      });
      if (!response.ok) {
        throw new Error("Falha ao salvar despesa");
      }
      setExpenseForm((current) => ({ ...current, amount: 0, description: "" }));
      await loadOperationalData();
      setStatus("Despesa registrada com sucesso.");
    } catch {
      setStatus("Não foi possível registrar a despesa.");
    }
  }

  async function submitMyCar(event) {
    event.preventDefault();
    if (!currentUser) {
      setStatus("Faça login para salvar dados e acompanhar seu histórico.");
      return;
    }
    try {
      const response = await fetch(`${API_URL}/user-vehicles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...myCarForm,
          user_id: currentUser.role === "admin" ? 1 : currentUser.id,
          vehicle_id: Number(myCarForm.vehicle_id),
          year_model: Number(myCarForm.year_model),
          current_km: Number(myCarForm.current_km),
          purchase_km: Number(myCarForm.purchase_km),
        }),
      });
      if (!response.ok) {
        throw new Error("Falha ao cadastrar veiculo");
      }
      setStatus("Veículo do usuário cadastrado com sucesso.");
      await loadMyCarData(currentUser.role === "admin" ? 1 : currentUser.id);
      setRecommendationStale(shouldMarkResultsStale(recommendationHasCalculated));
    } catch {
      setStatus("Não foi possível cadastrar o veículo do usuário.");
    }
  }

  async function submitProblem(event) {
    event.preventDefault();
    if (!currentUser || !selectedUserVehicleId) {
      setStatus("Selecione um veículo cadastrado para registrar problema.");
      return;
    }
    try {
      const response = await fetch(`${API_URL}/vehicle-reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...problemForm,
          user_vehicle_id: Number(selectedUserVehicleId),
          occurrence_km: Number(problemForm.occurrence_km),
          repair_cost: Number(problemForm.repair_cost),
        }),
      });
      if (!response.ok) {
        throw new Error("Falha ao registrar problema");
      }
      setStatus("Problema registrado e agregado ao modelo.");
      await loadVehicleHistory(selectedUserVehicleId);
      setRecommendationStale(shouldMarkResultsStale(recommendationHasCalculated));
    } catch {
      setStatus("Não foi possível registrar o problema.");
    }
  }

  async function submitConsumption(event) {
    event.preventDefault();
    if (!currentUser || !selectedUserVehicleId) {
      setStatus("Selecione um veículo cadastrado para registrar consumo.");
      return;
    }
    try {
      const response = await fetch(`${API_URL}/fuel-consumption-reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...consumptionForm,
          user_vehicle_id: Number(selectedUserVehicleId),
          km_per_liter: Number(consumptionForm.km_per_liter),
        }),
      });
      if (!response.ok) {
        throw new Error("Falha ao registrar consumo");
      }
      setStatus("Consumo real registrado e agregado ao modelo.");
      await loadVehicleHistory(selectedUserVehicleId);
      setRecommendationStale(shouldMarkResultsStale(recommendationHasCalculated));
    } catch {
      setStatus("Não foi possível registrar o consumo real.");
    }
  }

  async function submitLogin(event) {
    event.preventDefault();
    if (PUBLIC_DEMO_MODE) {
      setLoginError("Login desabilitado no ambiente demonstrativo público.");
      return;
    }
    setLoginError("");
    try {
      const response = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...loginForm, role: loginRole }),
      });
      if (!response.ok) {
        throw new Error("Credenciais invalidas");
      }
      const user = await response.json();
      setCurrentUser(user);
      localStorage.setItem("sigra-session", JSON.stringify(user));
      setExpenseForm((current) => ({ ...current, user_id: user.id }));
      setMyCarForm((current) => ({ ...current, user_id: user.id }));
      setActiveTab(user.role === "admin" ? "admin" : "recommendations");
      setStatus(`Sessão iniciada como ${user.role === "admin" ? "administrador" : "usuário"}.`);
      await loadMyCarData(user.role === "admin" ? 1 : user.id);
    } catch {
      setLoginError("Email, senha ou perfil incorretos.");
    }
  }

  function chooseLoginRole(role) {
    setLoginRole(role);
    setLoginError("");
    setLoginForm({ email: "", password: "" });
  }

  function logout() {
    setCurrentUser(null);
    localStorage.removeItem("sigra-session");
    setActiveTab("recommendations");
    setStatus("Você está navegando como visitante.");
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("sigra-theme", theme);
  }, [theme]);

  useEffect(() => {
    loadVehicles();
    if (!PUBLIC_DEMO_MODE) loadOperationalData();
    searchOnlineCars({ preventDefault() {} });
    if (PUBLIC_DEMO_MODE) localStorage.removeItem("sigra-session");
    return () => recommendationAbortController.current?.abort();
  }, []);

  useEffect(() => {
    if (currentUser) {
      loadMyCarData(currentUser.role === "admin" ? 1 : currentUser.id);
    }
  }, [currentUser]);

  const comparedVehicles = useMemo(
    () => (Array.isArray(vehicles) ? vehicles : []).filter((vehicle) => selectedIds.includes(vehicle.id)),
    [vehicles, selectedIds],
  );

  const safeRecommendations = Array.isArray(recommendations) ? recommendations : [];
  const safeVehicles = Array.isArray(vehicles) ? vehicles : [];
  const safeExpenses = Array.isArray(expenses) ? expenses : [];

  function updateProfile(field, value) {
    recommendationProfileVersion.current += 1;
    setProfile((current) => ({ ...current, [field]: value }));
    setRecommendationErrors((current) => ({ ...current, [field]: undefined }));
    setRecommendationStale(shouldMarkResultsStale(recommendationHasCalculated));
  }

  function resetMultifactorWeights() {
    recommendationProfileVersion.current += 1;
    setProfile((current) => ({ ...current, ...resetMultifactorWeightFields(current) }));
    setRecommendationErrors((current) => ({ ...current, multifactor_weights: undefined }));
    setRecommendationStale(shouldMarkResultsStale(recommendationHasCalculated));
  }

  function toggleVehicle(id) {
    setSelectedIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  }

  function updateExpense(field, value) {
    setExpenseForm((current) => ({ ...current, [field]: value }));
  }

  function updateMyCar(field, value) {
    setMyCarForm((current) => ({ ...current, [field]: value }));
  }

  function updateProblem(field, value) {
    setProblemForm((current) => ({ ...current, [field]: value }));
  }

  function updateConsumption(field, value) {
    setConsumptionForm((current) => ({ ...current, [field]: value }));
  }

  function chooseUserVehicle(value) {
    setSelectedUserVehicleId(value);
    setProblemForm((current) => ({ ...current, user_vehicle_id: value }));
    setConsumptionForm((current) => ({ ...current, user_vehicle_id: value }));
    loadVehicleHistory(value);
  }

  function recommendationLabel(status) {
    if (status === "not_recommended") return "Não recomendado";
    if (status === "attention") return "Atenção";
    if (status === "good_option") return "Boa opção";
    return "Recomendado";
  }

  function decisionText(item) {
    if (!item?.is_best_choice) return null;
    return "Melhor escolha do SIGRA considerando perfil, preço e custo mensal.";
  }

  function shortReason(item) {
    if (item?.is_best_choice) {
      return "Boa aderência ao perfil informado, com custo mensal e manutenção equilibrados.";
    }
    const explanations = Array.isArray(item?.explanations) ? item.explanations : [];
    const firstUseful = explanations.find((text) => !text.startsWith("Custo mensal") && !text.startsWith("Classificacao") && !text.startsWith("Classificação"));
    return firstUseful || "Opção avaliada pelos critérios financeiros, uso informado e facilidade de manutenção.";
  }

  function recommendationStrengths(item) {
    const awards = Array.isArray(item?.category_awards) ? item.category_awards.map((award) => award.label) : [];
    const strengths = [...awards];
    if (item?.parts_feedback?.supplier_availability_score >= 70) strengths.push("Boa disponibilidade de peças");
    if (item?.parts_feedback?.maintenance_index >= 70) strengths.push("Manutenção favorável");
    if (item?.components?.fuel_efficiency >= 70) strengths.push("Consumo competitivo");
    const uniqueStrengths = Array.from(new Set(strengths)).slice(0, 2);
    return uniqueStrengths.length ? uniqueStrengths : ["Perfil analisado pelos critérios definidos"];
  }

  function recommendationCautions(item) {
    const cautions = [];
    const penalties = Array.isArray(item?.penalties) ? item.penalties : [];
    cautions.push(...penalties);
    if (item?.parts_feedback?.price_variation_risk >= 55) {
      cautions.push("Compare preços de peças antes da compra.");
    }
    if (item?.recommendation_status === "attention") {
      cautions.push("Requer conferencia dos limites informados.");
    }
    return Array.from(new Set(cautions)).slice(0, 1);
  }

  function visibleAwards(item) {
    const awards = Array.isArray(item?.category_awards) ? item.category_awards : [];
    return awards.slice(0, item?.is_best_choice ? 1 : 2);
  }

  function vehicleSpecs(vehicle, monthlyCost) {
    return {
      Ano: vehicle.year,
      "Preço de referência": formatCurrency(vehicle.price),
      Consumo: `${vehicle.fuel_efficiency_km_l} km/l`,
      "Manutencao anual": formatCurrency(vehicle.annual_maintenance_cost),
      "Custo mensal estimado": formatCurrency(monthlyCost),
      Confiabilidade: `${vehicle.reliability_score}/100`,
      "Disponibilidade de pecas": `${vehicle.parts_availability_score}/100`,
      "Desvalorizacao": `${vehicle.depreciation_rate}%`,
    };
  }

  function tcoItems(tco = {}) {
    return {
      Combustível: formatCurrency(tco.monthly_fuel_cost),
      Manutenção: formatCurrency(tco.monthly_maintenance_cost),
      IPVA: formatCurrency(tco.monthly_ipva_cost),
      Seguro: formatCurrency(tco.monthly_insurance_cost),
      Depreciação: formatCurrency(tco.monthly_depreciation_cost),
      "Total mensal": formatCurrency(tco.total_monthly_cost),
    };
  }

  function financialProfileLabel(profile) {
    const labels = {
      restricted: "Restrito",
      purchase_high_monthly_low: "Compra alta, mensal baixo",
      balanced: "Equilibrado",
      comfortable: "Confortável",
      high_capacity: "Alta capacidade",
    };
    return labels[profile] || "Equilibrado";
  }

  function recommendationStrategyLabel(strategy) {
    const labels = {
      lowest_cost: "Menor custo possível",
      budget_economy: "Econômico dentro do orçamento",
      cost_benefit: "Custo-benefício",
      balanced: "Equilibrado",
      comfort_space: "Conforto e espaço",
      best_within_budget: "Melhor categoria dentro do orçamento",
    };
    return labels[strategy] || strategy;
  }

  function financialStatus(details) {
    if (details?.recommendation_summary?.financial_status) {
      return details.recommendation_summary.financial_status;
    }
    const components = details?.score_components || {};
    if (components.fully_viable) return "Cabe na compra e na manutenção.";
    if (components.purchase_viable && !components.monthly_viable) return "Cabe na compra, mas pesa no mensal.";
    return "Acima do limite mensal.";
  }

  function financialDetailItems(details) {
    const components = details?.score_components || {};
    const totalMonthlyCost = components.total_monthly_cost ?? details?.tco?.total_monthly_cost ?? details?.monthly_cost;
    const monthlyGap = components.monthly_limit_gap ?? 0;
    const monthlyLimit = totalMonthlyCost !== undefined ? Number(totalMonthlyCost) + Number(monthlyGap) : undefined;
    return {
      "Perfil financeiro": financialProfileLabel(components.financial_capacity_profile),
      "Custo mensal estimado": formatCurrency(totalMonthlyCost),
      "Limite mensal informado": formatCurrency(monthlyLimit),
      "Diferença mensal": formatCurrency(monthlyGap),
      Status: financialStatus(details),
    };
  }

  function partsCatalogButton(catalog) {
    if (!catalog?.url) return null;
    const label = catalog.target_level === "model" ? "Abrir catalogo do modelo" : "Consultar pecas";
    return (
      <a className="parts-link" href={catalog.url} target="_blank" rel="noreferrer">
        {label}
      </a>
    );
  }

  return (
    <main className="app-shell">
      {PUBLIC_DEMO_MODE && (
        <div
          className="demo-mode-banner"
          data-testid="public-demo-banner"
          role="status"
        >
          <strong>Ambiente demonstrativo em modo somente leitura</strong>
          <span>
            Recomendações e simulações não representam proposta comercial.
          </span>
        </div>
      )}
      <section className="workspace">
        <aside className="control-panel">
          <div>
            <p className="eyebrow">SIGRA</p>
            <h1>Recomendacao automotiva inteligente</h1>
            <p className="status">{status}</p>
          </div>

          <div className="session-panel">
            <div>
              <span>{PUBLIC_DEMO_MODE ? "Homologação" : (currentUser ? (currentUser.role === "admin" ? "Administrador" : "Usuario") : "Visitante")}</span>
              <strong>{PUBLIC_DEMO_MODE ? "Demonstração pública" : (currentUser ? currentUser.name : "Simulacao livre")}</strong>
              {!PUBLIC_DEMO_MODE && !currentUser && <small>Faça login para salvar dados e acompanhar seu histórico.</small>}
              {PUBLIC_DEMO_MODE && <small>Nenhum dado pessoal pode ser gravado neste ambiente.</small>}
            </div>
            {!PUBLIC_DEMO_MODE && currentUser && (
              <button className="ghost-button" type="button" onClick={logout}>
                Sair
              </button>
            )}
          </div>

          {!PUBLIC_DEMO_MODE && !currentUser && (
            <section className="login-panel">
              <p>O modo visitante permite simular recomendacoes sem cadastro.</p>
              <div className="theme-toggle" aria-label="Selecionar perfil">
                <button className={loginRole === "user" ? "active" : ""} type="button" onClick={() => chooseLoginRole("user")}>
                  Usuario
                </button>
                <button className={loginRole === "admin" ? "active" : ""} type="button" onClick={() => chooseLoginRole("admin")}>
                  Admin
                </button>
              </div>
              <form className="login-form" onSubmit={submitLogin}>
                <label>
                  Email
                  <input
                    type="email"
                    value={loginForm.email}
                    onChange={(event) => setLoginForm((current) => ({ ...current, email: event.target.value }))}
                  />
                </label>
                <label>
                  Senha
                  <input
                    type="password"
                    value={loginForm.password}
                    onChange={(event) => setLoginForm((current) => ({ ...current, password: event.target.value }))}
                  />
                </label>
                {loginError && <p className="login-error">{loginError}</p>}
                <button type="submit">Entrar</button>
              </form>
            </section>
          )}

          <div className="theme-toggle" aria-label="Selecionar tema">
            <button className={theme === "light" ? "active" : ""} type="button" onClick={() => setTheme("light")}>
              Claro
            </button>
            <button className={theme === "dark" ? "active" : ""} type="button" onClick={() => setTheme("dark")}>
              Escuro
            </button>
          </div>

          {activeTab === "recommendations" && <RecommendationForm
            profile={profile}
            errors={recommendationErrors}
            loading={recommendationLoading}
            onChange={updateProfile}
            onResetMultifactorWeights={resetMultifactorWeights}
            onSubmit={runRecommendation}
          />}
        </aside>

        <section className="content">
          <nav className="tabs" aria-label="Navegacao principal">
            <button data-testid="nav-recommendations" className={activeTab === "recommendations" ? "active" : ""} onClick={() => setActiveTab("recommendations")}>
              Recomendacao
            </button>
            <button className={activeTab === "comparison" ? "active" : ""} onClick={() => setActiveTab("comparison")}>
              Comparacao
            </button>
            {!PUBLIC_DEMO_MODE && (
              <button className={activeTab === "expenses" ? "active" : ""} onClick={() => setActiveTab("expenses")}>
                Despesas
              </button>
            )}
            <button data-testid="nav-financing" className={activeTab === "financing" ? "active" : ""} onClick={() => setActiveTab("financing")}>
              Financiamento
            </button>
            {!PUBLIC_DEMO_MODE && (
              <button className={activeTab === "my-car" ? "active" : ""} onClick={() => setActiveTab("my-car")}>
                Meu carro
              </button>
            )}
            <button className={activeTab === "parts" ? "active" : ""} onClick={() => setActiveTab("parts")}>
              Peças
            </button>
            <button className={activeTab === "online" ? "active" : ""} onClick={() => setActiveTab("online")}>
              Busca online
            </button>
            {!PUBLIC_DEMO_MODE && currentUser?.role === "admin" && (
              <button className={activeTab === "admin" ? "active" : ""} onClick={() => setActiveTab("admin")}>
                Admin
              </button>
            )}
          </nav>

          {activeTab === "recommendations" && (
            <RecommendationPage
              vehicleType={profile.vehicle_type}
              state={{
                recommendations: safeRecommendations,
                metadata: recommendationMetadata,
                loading: recommendationLoading,
                error: recommendationError,
                stale: recommendationStale,
                hasCalculated: recommendationHasCalculated,
              }}
              showAll={showAllRecommendations}
              onToggleShowAll={() => setShowAllRecommendations((current) => !current)}
              onRetry={runRecommendation}
              onDetails={setSelectedRecommendationDetails}
              onParts={(item) => { setActiveTab("parts"); setPartsVehicleId(item.vehicle.id); loadPartsAnalysis(item.vehicle.id); }}
              onCompare={(item) => { if (!selectedIds.includes(item.vehicle.id)) toggleVehicle(item.vehicle.id); setActiveTab("comparison"); }}
            />
          )}

          {activeTab === "comparison" && (
          <>
          <div className="section-heading">
            <p className="eyebrow">Comparacao</p>
            <h2>Indicadores tecnicos</h2>
          </div>

          <div className="vehicle-selector">
            {safeVehicles.map((vehicle) => (
              <label key={vehicle.id}>
                <input
                  type="checkbox"
                  checked={selectedIds.includes(vehicle.id)}
                  onChange={() => toggleVehicle(vehicle.id)}
                />
                {vehicle.brand} {vehicle.model}
              </label>
            ))}
          </div>

          <div className="comparison-table" role="table">
            <div className="table-row table-head" role="row">
              <span>Veículo</span>
              <span>Preco</span>
              <span>Consumo</span>
              <span>Manutencao anual</span>
              <span>Confiabilidade</span>
            </div>
            {comparedVehicles.map((vehicle) => (
              <div className="table-row" role="row" key={vehicle.id}>
                <span>
                  {vehicle.brand} {vehicle.model}
                </span>
                <span>{formatCurrency(vehicle.price)}</span>
                <span>{vehicle.fuel_efficiency_km_l} km/l</span>
                <span>{formatCurrency(vehicle.annual_maintenance_cost)}</span>
                <span>{vehicle.reliability_score}/100</span>
              </div>
            ))}
          </div>
          </>
          )}

          {activeTab === "financing" && <FinancingPage cars={safeVehicles} />}

          {activeTab === "expenses" && (
          <>
          <div className="section-heading">
            <p className="eyebrow">Gestao financeira</p>
            <h2>Despesas e custos do usuário</h2>
          </div>

          <div className="finance-layout">
            <form className="finance-form" onSubmit={submitExpense}>
              {!currentUser && (
                <p className="login-error">Faça login para salvar dados e acompanhar seu histórico.</p>
              )}
              <label>
                Veículo
                <select value={expenseForm.vehicle_id} onChange={(event) => updateExpense("vehicle_id", event.target.value)}>
                  {safeVehicles.map((vehicle) => (
                    <option value={vehicle.id} key={vehicle.id}>
                      {vehicle.brand} {vehicle.model}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Categoria
                <select value={expenseForm.category} onChange={(event) => updateExpense("category", event.target.value)}>
                  <option value="combustivel">Combustivel</option>
                  <option value="seguro">Seguro</option>
                  <option value="documentacao">Documentacao</option>
                  <option value="manutencao">Manutenção</option>
                  <option value="outros">Outros</option>
                </select>
              </label>
              <label>
                Valor
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={expenseForm.amount}
                  onChange={(event) => updateExpense("amount", event.target.value)}
                />
              </label>
              <label>
                Data
                <input
                  type="date"
                  value={expenseForm.expense_date}
                  onChange={(event) => updateExpense("expense_date", event.target.value)}
                />
              </label>
              <label>
                Descricao
                <input
                  type="text"
                  value={expenseForm.description}
                  onChange={(event) => updateExpense("description", event.target.value)}
                />
              </label>
              <button type="submit">{currentUser ? "Registrar despesa" : "Entrar para registrar"}</button>
            </form>

            <section className="summary-panel">
              <div className="summary-card">
                <span>Total de despesas</span>
                <strong>{formatCurrency(summary.total_expenses)}</strong>
              </div>
              <div className="summary-card">
                <span>Manutencoes previstas</span>
                <strong>{summary.pending_maintenances}</strong>
              </div>
              <div className="summary-card">
                <span>Custo acumulado</span>
                <strong>{formatCurrency(summary.total_cost)}</strong>
              </div>
            </section>
          </div>

          <div className="expense-list">
            {safeExpenses.length === 0 ? (
              <p>Nenhuma despesa registrada.</p>
            ) : (
              safeExpenses.map((expense) => (
                <article key={expense.id}>
                  <strong>{expense.category}</strong>
                  <span>{formatCurrency(expense.amount)}</span>
                  <small>{expense.expense_date}</small>
                </article>
              ))
            )}
          </div>
          </>
          )}

          {activeTab === "my-car" && (
          <>
          <div className="section-heading">
            <p className="eyebrow">Meu carro</p>
            <h2>Histórico do veículo e alertas preventivos</h2>
            <p className="section-note">Registre dados reais de uso para alimentar estatisticas por modelo e melhorar recomendacoes futuras.</p>
          </div>

          {!currentUser ? (
            <section className="restricted-panel">
              <strong>Login necessario</strong>
              <p>Faça login para salvar dados e acompanhar seu histórico.</p>
            </section>
          ) : (
            <>
            <div className="my-car-layout">
              <form className="finance-form" onSubmit={submitMyCar}>
                <h3>Cadastrar veículo próprio</h3>
                <label>
                  Modelo da base
                  <select value={myCarForm.vehicle_id} onChange={(event) => updateMyCar("vehicle_id", event.target.value)}>
                    {safeVehicles.map((vehicle) => (
                      <option value={vehicle.id} key={vehicle.id}>
                        {vehicle.brand} {vehicle.model} {vehicle.year}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="form-grid">
                  <label>
                    Ano/modelo
                    <input type="number" value={myCarForm.year_model} onChange={(event) => updateMyCar("year_model", event.target.value)} />
                  </label>
                  <label>
                    Km atual
                    <input type="number" value={myCarForm.current_km} onChange={(event) => updateMyCar("current_km", event.target.value)} />
                  </label>
                  <label>
                    Km na compra
                    <input type="number" value={myCarForm.purchase_km} onChange={(event) => updateMyCar("purchase_km", event.target.value)} />
                  </label>
                  <label>
                    Data da compra
                    <input type="date" value={myCarForm.purchase_date} onChange={(event) => updateMyCar("purchase_date", event.target.value)} />
                  </label>
                </div>
                <label>
                  Uso principal
                  <select value={myCarForm.main_usage} onChange={(event) => updateMyCar("main_usage", event.target.value)}>
                    <option value="cidade">Cidade</option>
                    <option value="estrada">Estrada</option>
                    <option value="misto">Misto</option>
                    <option value="app">Aplicativo</option>
                    <option value="familia">Familia</option>
                    <option value="trabalho">Trabalho</option>
                  </select>
                </label>
                <label>
                  Observacoes
                  <input type="text" value={myCarForm.notes} onChange={(event) => updateMyCar("notes", event.target.value)} />
                </label>
                <button type="submit">Cadastrar meu carro</button>
              </form>

              <section className="history-panel">
                <h3>Veículos cadastrados</h3>
                {myCars.length === 0 ? (
                  <p>Nenhum veículo cadastrado ainda.</p>
                ) : (
                  <>
                  <label>
                    Selecionar veículo
                    <select value={selectedUserVehicleId} onChange={(event) => chooseUserVehicle(event.target.value)}>
                      {myCars.map((item) => (
                        <option value={item.id} key={item.id}>
                          {item.vehicle?.brand} {item.vehicle?.model} - {item.current_km} km
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="alert-list">
                    {(vehicleHistory?.alerts || []).length === 0 ? (
                      <p>Nenhum alerta preventivo para o km atual.</p>
                    ) : (
                      vehicleHistory.alerts.map((alert) => (
                        <article className={`alert-card ${alert.priority}`} key={`${alert.category}-${alert.reference_km}`}>
                          <strong>{alert.priority === "alta" ? "Alerta alto" : "Alerta preventivo"}</strong>
                          <p>{alert.message}</p>
                          <small>{alert.report_count} relato(s) usados como referencia.</small>
                        </article>
                      ))
                    )}
                  </div>
                  {vehicleHistory?.model_statistics && (
                    <dl className="spec-list compact">
                      <div>
                        <dt>Relatos do modelo</dt>
                        <dd>{vehicleHistory.model_statistics.report_count}</dd>
                      </div>
                      <div>
                        <dt>Indice de risco</dt>
                        <dd>{vehicleHistory.model_statistics.risk_index}/100</dd>
                      </div>
                      <div>
                        <dt>Km medio de problema</dt>
                        <dd>{vehicleHistory.model_statistics.average_problem_km || "Sem dados"}</dd>
                      </div>
                      <div>
                        <dt>Custo medio de reparo</dt>
                        <dd>{vehicleHistory.model_statistics.average_repair_cost ? formatCurrency(vehicleHistory.model_statistics.average_repair_cost) : "Sem dados"}</dd>
                      </div>
                    </dl>
                  )}
                  {vehicleHistory?.user_vehicle?.vehicle_id && (
                    <button
                      className="ghost-button"
                      type="button"
                      onClick={() => {
                        setActiveTab("parts");
                        setPartsVehicleId(vehicleHistory.user_vehicle.vehicle_id);
                        loadPartsAnalysis(vehicleHistory.user_vehicle.vehicle_id);
                      }}
                    >
                      Ver peças e manutenção do meu modelo
                    </button>
                  )}
                  </>
                )}
              </section>
            </div>

            <div className="my-car-layout">
              <form className="finance-form" onSubmit={submitProblem}>
                <h3>Registrar problema</h3>
                <div className="form-grid">
                  <label>
                    Categoria
                    <select value={problemForm.problem_category} onChange={(event) => updateProblem("problem_category", event.target.value)}>
                      <option value="motor">Motor</option>
                      <option value="cambio">Cambio</option>
                      <option value="suspensao">Suspensao</option>
                      <option value="freio">Freio</option>
                      <option value="eletrica">Eletrica</option>
                      <option value="arrefecimento">Arrefecimento</option>
                      <option value="acabamento">Acabamento</option>
                      <option value="consumo">Consumo</option>
                      <option value="pecas">Peças</option>
                      <option value="seguro">Seguro</option>
                      <option value="outros">Outros</option>
                    </select>
                  </label>
                  <label>
                    Gravidade
                    <select value={problemForm.severity} onChange={(event) => updateProblem("severity", event.target.value)}>
                      <option value="baixa">Baixa</option>
                      <option value="media">Media</option>
                      <option value="alta">Alta</option>
                    </select>
                  </label>
                  <label>
                    Km ocorrido
                    <input type="number" value={problemForm.occurrence_km} onChange={(event) => updateProblem("occurrence_km", event.target.value)} />
                  </label>
                  <label>
                    Custo aproximado
                    <input type="number" step="0.01" value={problemForm.repair_cost} onChange={(event) => updateProblem("repair_cost", event.target.value)} />
                  </label>
                </div>
                <label>
                  Descricao
                  <input type="text" value={problemForm.description} onChange={(event) => updateProblem("description", event.target.value)} />
                </label>
                <label>
                  Data
                  <input type="date" value={problemForm.occurrence_date} onChange={(event) => updateProblem("occurrence_date", event.target.value)} />
                </label>
                <label className="checkbox-line">
                  <input type="checkbox" checked={problemForm.resolved} onChange={(event) => updateProblem("resolved", event.target.checked)} />
                  Foi resolvido?
                </label>
                <button type="submit">Registrar problema</button>
              </form>

              <form className="finance-form" onSubmit={submitConsumption}>
                <h3>Registrar consumo real</h3>
                <div className="form-grid">
                  <label>
                    Km/l real
                    <input type="number" step="0.1" value={consumptionForm.km_per_liter} onChange={(event) => updateConsumption("km_per_liter", event.target.value)} />
                  </label>
                  <label>
                    Tipo de uso
                    <select value={consumptionForm.usage_type} onChange={(event) => updateConsumption("usage_type", event.target.value)}>
                      <option value="urbano">Urbano</option>
                      <option value="estrada">Estrada</option>
                      <option value="misto">Misto</option>
                    </select>
                  </label>
                  <label>
                    Combustivel
                    <select value={consumptionForm.fuel_type} onChange={(event) => updateConsumption("fuel_type", event.target.value)}>
                      <option value="flex">Flex</option>
                      <option value="gasolina">Gasolina</option>
                      <option value="etanol">Etanol</option>
                      <option value="diesel">Diesel</option>
                    </select>
                  </label>
                </div>
                <label>
                  Observacao
                  <input type="text" value={consumptionForm.notes} onChange={(event) => updateConsumption("notes", event.target.value)} />
                </label>
                <button type="submit">Registrar consumo</button>
              </form>
            </div>
            </>
          )}
          </>
          )}

          {activeTab === "parts" && (
          <>
          <div className="section-heading">
            <p className="eyebrow">Peças e manutenção</p>
            <h2>Índice SIGRA de Manutenção</h2>
            <p className="section-note">Análise demonstrativa de peças, fornecedores, variação de preço e compatibilidade com outros modelos.</p>
          </div>

          <form className="search-bar" onSubmit={(event) => { event.preventDefault(); loadPartsAnalysis(partsVehicleId); }}>
            <select value={partsVehicleId} onChange={(event) => setPartsVehicleId(event.target.value)}>
              {safeVehicles.map((vehicle) => (
                <option value={vehicle.id} key={vehicle.id}>
                  {vehicle.brand} {vehicle.model} {vehicle.year}
                </option>
              ))}
            </select>
            <button type="submit">Analisar pecas</button>
          </form>

          {partsAnalyses[partsVehicleId] ? (
            <section className="parts-analysis">
              <div className="maintenance-hero">
                <div>
                  <p className="eyebrow">Modelo analisado</p>
                  <h3>{partsAnalyses[partsVehicleId].vehicle.brand} {partsAnalyses[partsVehicleId].vehicle.model}</h3>
                  <p>Dados demonstrativos. Compare fornecedores antes de qualquer compra real.</p>
                </div>
                <strong>{partsAnalyses[partsVehicleId].maintenance_index}/100</strong>
              </div>

              <div className="summary-panel">
                <article className="summary-card">
                  <span>Fornecedores</span>
                  <strong>{partsAnalyses[partsVehicleId].supplier_availability_score}/100</strong>
                </article>
                <article className="summary-card">
                  <span>Compatibilidade</span>
                  <strong>{partsAnalyses[partsVehicleId].shared_parts_score}/100</strong>
                </article>
                <article className="summary-card">
                  <span>Risco de variacao</span>
                  <strong>{partsAnalyses[partsVehicleId].price_variation_risk}/100</strong>
                </article>
              </div>

              <div className="alert-list">
                {(partsAnalyses[partsVehicleId].alerts || []).map((alert) => (
                  <article className="alert-card alta" key={alert}>
                    <strong>Alerta para comprador</strong>
                    <p>{alert}</p>
                  </article>
                ))}
                {(partsAnalyses[partsVehicleId].positives || []).map((positive) => (
                  <article className="alert-card" key={positive}>
                    <strong>Ponto positivo</strong>
                    <p>{positive}</p>
                  </article>
                ))}
              </div>

              <div className="parts-grid">
                {(partsAnalyses[partsVehicleId].parts || []).map((part) => (
                  <article className="part-card" key={part.part_id}>
                    <div className="vehicle-topline">
                      <div>
                        <h3>{part.part_name}</h3>
                        <p>{part.category}</p>
                      </div>
                      <strong>{part.supplier_count}<span>fornec.</span></strong>
                    </div>
                    <dl className="spec-list compact">
                      <div>
                        <dt>Menor preço</dt>
                        <dd>{formatCurrency(part.min_price)}</dd>
                      </div>
                      <div>
                        <dt>Maior preço</dt>
                        <dd>{formatCurrency(part.max_price)}</dd>
                      </div>
                      <div>
                        <dt>Media</dt>
                        <dd>{formatCurrency(part.average_price)}</dd>
                      </div>
                      <div>
                        <dt>Variacao</dt>
                        <dd>{part.variation_percent}%</dd>
                      </div>
                    </dl>
                    {(part.alerts || []).map((alert) => (
                      <p className="part-alert" key={alert}>{alert}</p>
                    ))}
                  </article>
                ))}
              </div>

              <div className="comparison-table" role="table">
                <div className="table-row table-head" role="row">
                  <span>Peca</span>
                  <span>Veículo compatível</span>
                  <span>Tipo</span>
                  <span>Confianca</span>
                  <span>Observacao</span>
                </div>
                {(partsAnalyses[partsVehicleId].compatibilities || []).map((item) => (
                  <div className="table-row" role="row" key={`${item.part}-${item.compatible_vehicle}`}>
                    <span>{item.part}</span>
                    <span>{item.compatible_vehicle}</span>
                    <span>{item.compatibility_type}</span>
                    <span>{item.confidence_level}</span>
                    <span>{item.notes}</span>
                  </div>
                ))}
              </div>
            </section>
          ) : (
            <section className="restricted-panel">
              <strong>Selecione um veículo e clique em analisar</strong>
              <p>O SIGRA exibirá preços demonstrativos, fornecedores, variação de preço e compatibilidade de peças.</p>
            </section>
          )}
          </>
          )}

          {activeTab === "online" && (
          <>
          <div className="section-heading">
            <p className="eyebrow">Busca online</p>
            <h2>Pesquisar carros com fotos</h2>
            <p className="section-note">Busca demonstrativa com imagens e links externos. Os anúncios podem ter preços diferentes da ficha por versão, estado, quilometragem e vendedor.</p>
          </div>

          <form className="search-bar" onSubmit={searchOnlineCars}>
            <input
              type="search"
              placeholder="Buscar por modelo, marca ou ano"
              value={onlineQuery}
              onChange={(event) => setOnlineQuery(event.target.value)}
            />
            <button type="submit">Buscar</button>
          </form>

          <div className="online-grid">
            {onlineResults.map((car) => (
              <article className="online-card" key={car.id}>
                <a className="online-image-link" href={car.purchase_url} target="_blank" rel="noreferrer" aria-label={`Buscar ${car.brand} ${car.model} para comprar`}>
                  <img src={car.image_url} alt={`${car.brand} ${car.model}`} onError={handleCarImageError} />
                  <span className="image-fallback">{car.brand} {car.model}</span>
                </a>
                <div>
                  <h3>{car.brand} {car.model}</h3>
                  <p>{car.year}</p>
                  <span>{car.source}</span>
                  <p className="market-note">Consultar preço atualizado no anúncio.</p>
                  <dl className="spec-list compact">
                    {Object.entries(car.technical_specs || {}).map(([label, value]) => (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                  {purchaseSourceButtons(car.purchase_sources, car.best_purchase_source)}
                </div>
              </article>
            ))}
          </div>
          </>
          )}

          {activeTab === "admin" && currentUser?.role === "admin" && (
          <>
          <div className="section-heading">
            <p className="eyebrow">Administracao</p>
            <h2>Painel do administrador</h2>
            <p className="section-note">Visao rapida para acompanhar dados cadastrados, despesas e funcionamento da API.</p>
          </div>

          <section className="admin-grid">
            <article className="summary-card">
              <span>Veículos cadastrados</span>
              <strong>{safeVehicles.length}</strong>
            </article>
            <article className="summary-card">
              <span>Despesas registradas</span>
              <strong>{safeExpenses.length}</strong>
            </article>
            <article className="summary-card">
              <span>Custo total</span>
              <strong>{formatCurrency(summary.total_cost)}</strong>
            </article>
            <article className="summary-card">
              <span>Manutencoes pendentes</span>
              <strong>{summary.pending_maintenances}</strong>
            </article>
          </section>

          <div className="comparison-table" role="table">
            <div className="table-row table-head" role="row">
              <span>Veículo</span>
              <span>Preco</span>
              <span>Uso</span>
              <span>Peças</span>
              <span>Confiabilidade</span>
            </div>
            {safeVehicles.map((vehicle) => (
              <div className="table-row" role="row" key={vehicle.id}>
                <span>{vehicle.brand} {vehicle.model}</span>
                <span>{formatCurrency(vehicle.price)}</span>
                <span>{(vehicle.use_cases || []).join(", ")}</span>
                <span>{vehicle.parts_availability_score}/100</span>
                <span>{vehicle.reliability_score}/100</span>
              </div>
            ))}
          </div>
          </>
          )}
        </section>
      </section>

      <RecommendationDetails
        item={selectedRecommendationDetails}
        metadata={recommendationMetadata}
        profile={profile}
        onClose={() => setSelectedRecommendationDetails(null)}
        onParts={(item) => { setActiveTab("parts"); setPartsVehicleId(item.vehicle.id); loadPartsAnalysis(item.vehicle.id); setSelectedRecommendationDetails(null); }}
        onCompare={(item) => { if (!selectedIds.includes(item.vehicle.id)) toggleVehicle(item.vehicle.id); setActiveTab("comparison"); setSelectedRecommendationDetails(null); }}
      />
    </main>
  );
}

export default App;
