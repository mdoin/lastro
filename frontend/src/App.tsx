// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { setUnauthorizedHandler } from "./api/client";
import { getAuthState } from "./api/endpoints";
import { Layout } from "./components/Layout";
import { Loading, Notice } from "./components/ui";
import { AppProvider } from "./lib/appContext";
import { LoginPage } from "./pages/Login";
import { OverviewPage } from "./pages/Overview";

// Telas carregadas sob demanda (pacote inicial menor no celular).
const FinancesPage = lazy(() => import("./pages/Finances").then((m) => ({ default: m.FinancesPage })));
const FuturePage = lazy(() => import("./pages/Future").then((m) => ({ default: m.FuturePage })));
const GoalsPage = lazy(() => import("./pages/Goals").then((m) => ({ default: m.GoalsPage })));
const TeamPage = lazy(() => import("./pages/Team").then((m) => ({ default: m.TeamPage })));
const RoutinesPage = lazy(() => import("./pages/Routines").then((m) => ({ default: m.RoutinesPage })));
const DecisionsPage = lazy(() => import("./pages/Decisions").then((m) => ({ default: m.DecisionsPage })));
const RadarPage = lazy(() => import("./pages/Radar").then((m) => ({ default: m.RadarPage })));
const OpportunitiesPage = lazy(() => import("./pages/Opportunities").then((m) => ({ default: m.OpportunitiesPage })));
const OpportunityPage = lazy(() => import("./pages/Opportunities").then((m) => ({ default: m.OpportunityPage })));
const SetupPage = lazy(() => import("./pages/Setup").then((m) => ({ default: m.SetupPage })));
const InboxPage = lazy(() => import("./pages/Inbox").then((m) => ({ default: m.InboxPage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));

// Galeria dos mascotes: só no `npm run dev` (import.meta.env.DEV vira false no build e o módulo some do pacote).
const MascotGallery = import.meta.env.DEV
  ? lazy(() => import("./pages/MascotGallery").then((m) => ({ default: m.MascotGallery })))
  : null;

const page = (el: ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

/** Rotas autenticadas: verifica a sessão uma vez e manda para o login se necessário. */
function RequireAuth() {
  const location = useLocation();
  const [state, setState] = useState<"checking" | "ok" | "login" | "setup" | "offline">("checking");

  useEffect(() => {
    let alive = true;
    getAuthState()
      .then((s) => alive && setState(!s.authenticated ? (s.setup_required ? "setup" : "login")
        : s.onboarding_done ? "ok" : "setup"))
      .catch(() => alive && setState("offline"));
    return () => {
      alive = false;
    };
  }, []);

  if (state === "checking") {
    return (
      <div className="login">
        <Loading label="Verificando sessão…" />
      </div>
    );
  }
  if (state === "setup") return <Navigate to="/instalar" replace />;
  if (state === "login") {
    const next = location.pathname + location.search;
    return <Navigate to={`/login${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} replace />;
  }
  if (state === "offline") {
    return (
      <div className="login">
        <div className="login-card">
          <Notice tone="error" title="Servidor indisponível.">
            Não foi possível falar com o Lastro. Verifique a conexão e recarregue a página.
          </Notice>
        </div>
      </div>
    );
  }
  return (
    <AppProvider>
      <Layout />
    </AppProvider>
  );
}

export function App() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      if (!window.location.pathname.startsWith("/login")) {
        const next = window.location.pathname + window.location.search;
        navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
      }
    });
  }, [navigate]);

  useEffect(() => {
    const titles: Record<string, string> = {
      "/": "Visão geral",
      "/vida-financeira": "Minha vida financeira",
      "/futuro": "Meu futuro",
      "/metas": "Metas",
      "/mentor": "Mentor e especialistas",
      "/rotinas": "Rotinas",
      "/radar": "Radar",
      "/oportunidades": "Diário de oportunidades",
      "/diario": "Diário de decisões",
      "/configuracoes": "Configurações",
      "/login": "Entrar",
      "/instalar": "Configuração inicial",
    };
    const base = "/" + (location.pathname.split("/")[1] ?? "");
    const t = titles[base];
    document.title = t ? `${t} · Lastro` : "Lastro";
  }, [location.pathname]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/instalar" element={page(<SetupPage />)} />
      {MascotGallery && <Route path="/dev/mascotes" element={page(<MascotGallery />)} />}
      <Route element={<RequireAuth />}>
        <Route index element={<OverviewPage />} />
        <Route path="vida-financeira" element={page(<FinancesPage />)} />
        <Route path="futuro" element={page(<FuturePage />)} />
        <Route path="metas" element={page(<GoalsPage />)} />
        <Route path="caixa" element={page(<InboxPage />)} />
        <Route path="mentor" element={page(<TeamPage />)} />
        <Route path="mentor/:conversationId" element={page(<TeamPage />)} />
        <Route path="rotinas" element={page(<RoutinesPage />)} />
        <Route path="radar" element={page(<RadarPage />)} />
        <Route path="oportunidades" element={page(<OpportunitiesPage />)} />
        <Route path="oportunidades/:opportunityId" element={page(<OpportunityPage />)} />
        <Route path="diario" element={page(<DecisionsPage />)} />
        <Route path="configuracoes" element={page(<SettingsPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
