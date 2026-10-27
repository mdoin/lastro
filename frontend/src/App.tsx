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
const MentorPage = lazy(() => import("./pages/Mentor").then((m) => ({ default: m.MentorPage })));
const RoutinesPage = lazy(() => import("./pages/Routines").then((m) => ({ default: m.RoutinesPage })));
const DecisionsPage = lazy(() => import("./pages/Decisions").then((m) => ({ default: m.DecisionsPage })));
const SettingsPage = lazy(() => import("./pages/Settings").then((m) => ({ default: m.SettingsPage })));

const page = (el: ReactNode) => <Suspense fallback={<Loading />}>{el}</Suspense>;

/** Rotas autenticadas: verifica a sessão uma vez e manda para o login se necessário. */
function RequireAuth() {
  const location = useLocation();
  const [state, setState] = useState<"checking" | "ok" | "login" | "offline">("checking");

  useEffect(() => {
    let alive = true;
    getAuthState()
      .then((s) => alive && setState(s.authenticated ? "ok" : "login"))
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
      "/mentor": "Mentor",
      "/rotinas": "Rotinas",
      "/diario": "Diário de decisões",
      "/configuracoes": "Configurações",
      "/login": "Entrar",
    };
    const base = "/" + (location.pathname.split("/")[1] ?? "");
    const t = titles[base];
    document.title = t ? `${t} · Lastro` : "Lastro";
  }, [location.pathname]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<OverviewPage />} />
        <Route path="vida-financeira" element={page(<FinancesPage />)} />
        <Route path="futuro" element={page(<FuturePage />)} />
        <Route path="metas" element={page(<GoalsPage />)} />
        <Route path="mentor" element={page(<MentorPage />)} />
        <Route path="mentor/:conversationId" element={page(<MentorPage />)} />
        <Route path="rotinas" element={page(<RoutinesPage />)} />
        <Route path="diario" element={page(<DecisionsPage />)} />
        <Route path="configuracoes" element={page(<SettingsPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
