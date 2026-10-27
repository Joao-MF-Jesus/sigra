const PAGE_ORIGIN = "http://127.0.0.1:14185";
const API_ORIGIN = "http://127.0.0.1:8011";
const SAFE_MESSAGES = new Set([
  "E-mail ou senha incorretos",
  "Origem da operação não confirmada",
  "Origem da operação não autorizada",
  "Muitas tentativas. Aguarde um minuto.",
  "Homologação: use somente uma conta fictícia .test ou .invalid",
  "Destino exclusivo de homologação Revision6 não confirmado",
  "Persistência de participantes indisponível. A migration precisa ser aplicada pelo responsável.",
]);

export function loginErrorMessage(failure) {
  const status = httpStatus(failure?.status);
  if (status === 409) return "Este e-mail já está cadastrado. Entre com sua senha.";
  if (status === 401) return "E-mail ou senha incorretos.";
  if (status === 422) return "Confira o nome, o e-mail e a senha (12 a 256 caracteres).";
  if (status === 429) return "Muitas tentativas. Aguarde um minuto.";
  if (status === 403) {
    return `${safeMessage(failure) || "A API não autorizou esta operação"} (HTTP 403).`;
  }
  if (status === 503) {
    return `${safeMessage(failure) || "O serviço de autenticação está indisponível"} (HTTP 503).`;
  }
  if (status) return `A API não concluiu a operação (HTTP ${status}).`;
  if (failure?.name === "TypeError") {
    return "O navegador não recebeu uma resposta acessível da API. Confira a conexão e eventuais bloqueios de CORS; não foi disponibilizado um status HTTP.";
  }
  if (failure?.name === "AbortError") return "A solicitação de acesso foi interrompida. Tente novamente.";
  return "Não foi possível interpretar o resultado do acesso. Confira os eventos sanitizados da tentativa.";
}

function httpStatus(value) {
  return Number.isInteger(value) && value >= 100 && value <= 599 ? value : null;
}

function referenceLabel(user) {
  if (!user?.id) return "NONE";
  if (user.name === "Participante fictício TLS A") return "TLS_A";
  if (user.name === "Participante fictício TLS B") return "TLS_B";
  return "OTHER";
}

function safeMessage(failure) {
  return SAFE_MESSAGES.has(failure?.message) ? failure.message : null;
}

// Diagnostic metadata only. This wrapper never inspects bodies, cookie values,
// response headers, tokens, or arbitrary error text, and never proxies login.
export function createLoginObservation({ apiUrl, location, cookieEnabled,
  fetchImpl = fetch, now = () => Date.now(), newId = () => crypto.randomUUID(),
  writeEvent = (metadata) => console.info(`SIGRA_LOGIN_OBSERVATION:${JSON.stringify(metadata)}`) }) {
  if (location?.origin !== PAGE_ORIGIN || apiUrl !== API_ORIGIN
    || new URLSearchParams(location.search).get("sigra_login_observe") !== "v1") return null;
  let attemptId = newId();
  function emit(event, metadata = {}) {
    try {
      const response = writeEvent({ event, attempt_id: attemptId, ...metadata });
      Promise.resolve(response).catch(() => {}); // Diagnostic output must not change authentication.
    } catch { /* Metadata transport must not change authentication. */ }
  }
  const observer = {
    buttonClick() { attemptId = newId(); emit("login_button_clicked"); },
    nativeInvalid(target) {
      const validity = target.validity;
      emit("native_validation_blocked", {
        field: ["email", "password"].includes(target.type) ? target.type : "unknown",
        value_missing: Boolean(validity.valueMissing), type_mismatch: Boolean(validity.typeMismatch),
        too_short: Boolean(validity.tooShort), too_long: Boolean(validity.tooLong),
        bad_input: Boolean(validity.badInput), pattern_mismatch: Boolean(validity.patternMismatch),
        custom_error: Boolean(validity.customError),
      });
    },
    submitHandled() { emit("submit_handled"); },
    async fetchImpl(url, options) {
      const parsed = new URL(url);
      if (parsed.origin !== API_ORIGIN || !["/auth/login", "/auth/session"].includes(parsed.pathname)
        || parsed.search || parsed.hash || parsed.username || parsed.password) return fetchImpl(url, options);
      const method = options?.method || "GET";
      const path = parsed.pathname;
      const start = now();
      emit("request_start", { path, method, credentials_included: options?.credentials === "include",
        csrf_marker_present: new Headers(options?.headers).get("X-SIGRA-CSRF") === "1",
        page_origin: PAGE_ORIGIN, api_origin: API_ORIGIN });
      try {
        const response = await fetchImpl(url, options);
        emit("response_received", { path, method, http_status: httpStatus(response.status),
          ok: Boolean(response.ok), response_type: ["basic", "cors", "opaque", "opaqueredirect", "default", "error"].includes(response.type) ? response.type : "unknown",
          redirected: Boolean(response.redirected), elapsed_ms: Math.max(0, Math.round(now() - start)) });
        return response;
      } catch (failure) {
        emit("request_failed", { path, method,
          error_type: ["TypeError", "AbortError", "SyntaxError"].includes(failure.name) ? failure.name : "OtherError",
          elapsed_ms: Math.max(0, Math.round(now() - start)) });
        throw failure;
      }
    },
    failure(failure) { emit("login_failure", { http_status: httpStatus(failure.status),
      ui_message: loginErrorMessage(failure), backend_message: safeMessage(failure) }); },
    success(user) { emit("login_success", { returned_user_present: Boolean(user?.id), reference_label: referenceLabel(user) }); },
    async checkSession(requestSession) {
      try {
        const session = await requestSession({ fetchImpl: observer.fetchImpl });
        emit("session_recognition", { authenticated: Boolean(session?.user?.id), reference_label: referenceLabel(session?.user) });
      } catch (failure) {
        emit("session_recognition_failed", { http_status: httpStatus(failure.status), backend_message: safeMessage(failure) });
      }
    },
  };
  emit("observer_ready", { page_origin: PAGE_ORIGIN, api_origin: API_ORIGIN, cookie_enabled: Boolean(cookieEnabled) });
  return observer;
}
