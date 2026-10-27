import React, { useState } from "react";
import { API_URL, requestLogin, requestRegistration, requestSession } from "../../api/sigraApi.js";
import { createLoginObservation, loginErrorMessage } from "./loginObservation.js";

export default function AuthPanel({ onAuthenticated }) {
  const [register, setRegister] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loginObservation] = useState(() => createLoginObservation({
    apiUrl: API_URL,
    location: typeof window === "undefined" ? undefined : window.location,
    cookieEnabled: typeof navigator === "undefined" ? false : navigator.cookieEnabled,
  }));

  function changeMode(next) {
    setRegister(next); setForm({ name: "", email: "", password: "" });
    setError(""); setMessage("");
  }
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    if (!register) loginObservation?.submitHandled();
    setBusy(true); setError(""); setMessage("");
    try {
      const credentials = { email: form.email, password: form.password };
      if (register) {
        await requestRegistration({ ...credentials, name: form.name });
        setRegister(false);
        setForm((current) => ({ ...current, password: "" }));
        setMessage("Cadastro concluído. Entre para registrar seus testes.");
      } else {
        const user = await requestLogin(credentials, loginObservation ? { fetchImpl: loginObservation.fetchImpl } : {});
        loginObservation?.success(user);
        setForm({ name: "", email: "", password: "" });
        onAuthenticated(user);
        void loginObservation?.checkSession(requestSession);
      }
    } catch (failure) {
      if (!register) loginObservation?.failure(failure);
      setError(loginErrorMessage(failure));
    } finally { setBusy(false); }
  }
  return <details className="account-access">
    <summary>Acessar recursos pessoais</summary>
    <section className="login-panel">
      <p>Você pode simular como visitante. Com uma conta de participante, seus testes e avaliações ficam no seu histórico privado.</p>
      {loginObservation && <p role="status">Observação de login ativa somente nesta homologação. Credenciais não são registradas.</p>}
      <div className="segmented-control">
        <button type="button" disabled={busy} className={!register ? "active" : ""} onClick={() => changeMode(false)}>Entrar</button>
        <button type="button" disabled={busy} className={register ? "active" : ""} onClick={() => changeMode(true)}>Criar conta</button>
      </div>
      <form className="login-form" onSubmit={submit} onInvalidCapture={(event) => { if (!register) loginObservation?.nativeInvalid(event.target); }}>
        {register && <label>Nome<input required minLength={2} maxLength={120} autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>}
        <label>E-mail<input required type="email" maxLength={160} autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label>Senha<input required type="password" minLength={register ? 12 : 1} maxLength={256} autoComplete={register ? "new-password" : "current-password"} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        {register && <small>Use uma senha de pelo menos 12 caracteres. Novas contas são participantes; permissões administrativas não são escolhidas no cadastro.</small>}
        {error && <p className="login-error" role="alert">{error}</p>}
        {message && <p role="status">{message}</p>}
        <button disabled={busy} type="submit" onClick={() => { if (!register) loginObservation?.buttonClick(); }}>{busy ? "Aguarde…" : register ? "Cadastrar participante" : "Entrar na conta"}</button>
      </form>
    </section>
  </details>;
}
