import React, { useState } from "react";

const BASE_NAV_ITEMS = Object.freeze([
  { id: "recommendations", label: "Recomendação", testId: "nav-recommendations" },
  { id: "comparison", label: "Comparar" },
  { id: "financing", label: "Financiamento", testId: "nav-financing" },
  { id: "parts", label: "Peças" },
  { id: "online", label: "Referências" },
]);

export default function AppHeader({ activeTab, currentUser, publicDemo, status, onNavigate, onLogout }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const items = [
    ...BASE_NAV_ITEMS.slice(0, 2),
    ...(!publicDemo ? [{ id: "expenses", label: "Despesas" }] : []),
    ...BASE_NAV_ITEMS.slice(2, 3),
    ...(!publicDemo ? [{ id: "my-car", label: "Meu carro" }] : []),
    ...BASE_NAV_ITEMS.slice(3),
    ...(!publicDemo && currentUser?.role === "admin" ? [{ id: "admin", label: "Admin" }] : []),
  ];

  function navigate(id) {
    onNavigate(id);
    setMenuOpen(false);
  }

  return <header className="app-header">
    <div className="app-header-bar">
      <button className="brand-button" type="button" onClick={() => navigate("recommendations")} aria-label="Ir para a recomendação">
        <span className="brand-mark" aria-hidden="true">S</span>
        <span><strong>SIGRA</strong><small>Escolhas automotivas com contexto</small></span>
      </button>
      <div className="header-trust" aria-label="Fontes de dados ativas">
        <span>FIPE</span><span>PBEV</span><span>ANP</span>
      </div>
      <button className="mobile-menu-button" type="button" aria-controls="primary-navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen((current) => !current)}>
        <span aria-hidden="true">{menuOpen ? "×" : "☰"}</span>
        <span>{menuOpen ? "Fechar" : "Menu"}</span>
      </button>
    </div>
    <div className={`header-navigation ${menuOpen ? "open" : ""}`}>
      <nav id="primary-navigation" className="primary-navigation" aria-label="Navegação principal">
        {items.map((item) => <button key={item.id} type="button" data-testid={item.testId} className={activeTab === item.id ? "active" : ""} aria-current={activeTab === item.id ? "page" : undefined} onClick={() => navigate(item.id)}>{item.label}</button>)}
      </nav>
      <div className="header-session">
        <span>{publicDemo ? "Demonstração acadêmica" : currentUser ? currentUser.name : "Modo visitante"}</span>
        {!publicDemo && currentUser && <button className="header-signout" type="button" onClick={onLogout}>Sair</button>}
      </div>
    </div>
    <p className="sr-only" aria-live="polite">{status}</p>
  </header>;
}
