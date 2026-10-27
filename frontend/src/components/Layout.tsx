import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { logout } from "../api/endpoints";
import type { AppStatus } from "../api/types";
import { useApp } from "../lib/appContext";
import { formatTime } from "../lib/dates";
import { BrandMark, Icon, type IconName } from "./Icon";
import { ThemeSwitch } from "./ThemeSwitch";

interface NavItem {
  to: string;
  label: string;
  short: string;
  icon: IconName;
  group: "Painel" | "Mentor" | "Radar" | "Sistema";
}

const NAV: NavItem[] = [
  { to: "/", label: "Visão geral", short: "Início", icon: "home", group: "Painel" },
  { to: "/vida-financeira", label: "Minha vida financeira", short: "Finanças", icon: "wallet", group: "Painel" },
  { to: "/futuro", label: "Meu futuro", short: "Futuro", icon: "trend", group: "Painel" },
  { to: "/metas", label: "Metas", short: "Metas", icon: "target", group: "Painel" },
  { to: "/mentor", label: "Mentor e especialistas", short: "Equipe", icon: "chat", group: "Mentor" },
  { to: "/rotinas", label: "Rotinas", short: "Rotinas", icon: "clock", group: "Mentor" },
  { to: "/diario", label: "Diário de decisões", short: "Diário", icon: "book", group: "Mentor" },
  { to: "/radar", label: "Radar", short: "Radar", icon: "pulse", group: "Radar" },
  { to: "/oportunidades", label: "Diário de oportunidades", short: "Oportunidades", icon: "bars", group: "Radar" },
  { to: "/configuracoes", label: "Configurações e auditoria", short: "Ajustes", icon: "settings", group: "Sistema" },
];

const GROUPS: NavItem["group"][] = ["Painel", "Mentor", "Radar", "Sistema"];
const PRIMARY_MOBILE = ["/", "/vida-financeira", "/futuro", "/mentor"];

/** Estado do mentor em uma linha: ponto de status + rótulo + detalhe. */
function mentorState(status: AppStatus | null): { tone: string; label: string; detail: string } {
  const m = status?.mentor;
  if (!m) return { tone: "", label: "Mentor", detail: "Verificando…" };
  if (!m.available) return { tone: "critical", label: "Mentor indisponível", detail: "O serviço não respondeu." };
  if (m.limit_until)
    return { tone: "warning", label: "Mentor em pausa", detail: `Limite da assinatura até ${formatTime(m.limit_until)}.` };
  if (m.logged_in === false) return { tone: "warning", label: "Mentor desconectado", detail: "Veja Configurações." };
  if (m.busy > 0)
    return { tone: "running", label: "Mentor trabalhando", detail: m.queued ? `${m.busy} em andamento · ${m.queued} na fila` : `${m.busy} em andamento` };
  return { tone: "good", label: "Mentor disponível", detail: "Educação, organização e simulação." };
}

export function Layout() {
  const { unreadCount, status } = useApp();
  const [moreOpen, setMoreOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const ms = mentorState(status);

  useEffect(() => setMoreOpen(false), [location.pathname]);

  useEffect(() => {
    if (!moreOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMoreOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [moreOpen]);

  async function doLogout() {
    try {
      await logout();
    } finally {
      navigate("/login", { replace: true });
    }
  }

  const secondary = NAV.filter((n) => !PRIMARY_MOBILE.includes(n.to));
  const secondaryActive = secondary.some((n) => location.pathname.startsWith(n.to));

  return (
    <div className="shell">
      <a className="skip-link" href="#conteudo">
        Pular para o conteúdo
      </a>
      <aside className="sidebar" aria-label="Navegação principal">
        <Link to="/" className="brand" aria-label="Lastro — visão geral">
          <BrandMark className="brand-mark" />
          <span className="brand-word">Lastro</span>
        </Link>
        <nav>
          {GROUPS.map((g) => (
            <div key={g} role="group" aria-label={g} style={{ display: "grid", gap: 2 }}>
              <div className="nav-group" aria-hidden="true">
                {g}
              </div>
              {NAV.filter((n) => n.group === g).map((n) => (
                <NavLink key={n.to} to={n.to} end={n.to === "/"}>
                  <Icon name={n.icon} className="nav-icon" />
                  {n.label}
                  {n.to === "/rotinas" && unreadCount > 0 && (
                    <span className="nav-dot" role="img" aria-label={`${unreadCount} resultado(s) não lido(s)`} />
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="mentor-state" role="status">
            <div className="ms-row">
              <span className={`status-dot ${ms.tone}`} aria-hidden="true" />
              {ms.label}
            </div>
            <p>{ms.detail} Nenhuma operação financeira é executada.</p>
          </div>
          <div className="foot-row">
            <button type="button" className="btn btn-ghost btn-sm" onClick={doLogout}>
              <Icon name="logout" />
              Sair
            </button>
            <ThemeSwitch compact />
          </div>
        </div>
      </aside>

      <header className="topbar">
        <Link to="/" className="brand" aria-label="Lastro — visão geral">
          <BrandMark className="brand-mark" />
          <span className="brand-word">Lastro</span>
        </Link>
        <Link to="/mentor" className="status-pill" aria-label={`${ms.label}. ${ms.detail}`}>
          <span className={`status-dot ${ms.tone}`} aria-hidden="true" />
          Mentor
        </Link>
      </header>

      <main id="conteudo" className="main" tabIndex={-1}>
        <Outlet />
      </main>

      {moreOpen && (
        <>
          <button type="button" className="scrim" aria-label="Fechar menu" onClick={() => setMoreOpen(false)} />
          <nav className="more-sheet" id="mais-menu" aria-label="Mais seções">
            {secondary.map((n) => (
              <NavLink key={n.to} to={n.to}>
                <Icon name={n.icon} className="nav-icon" />
                {n.label}
                {n.to === "/rotinas" && unreadCount > 0 && <span className="unread-dot" role="img" aria-label="não lidos" />}
              </NavLink>
            ))}
            <div className="sheet-row">
              <span>Tema</span>
              <ThemeSwitch compact />
            </div>
            <button type="button" onClick={doLogout}>
              <Icon name="logout" className="nav-icon" />
              Sair
            </button>
          </nav>
        </>
      )}

      <nav className="bottom-nav" aria-label="Navegação principal">
        {NAV.filter((n) => PRIMARY_MOBILE.includes(n.to)).map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} aria-label={n.label}>
            <Icon name={n.icon} className="nav-icon" />
            <span>{n.short}</span>
          </NavLink>
        ))}
        <button
          type="button"
          aria-expanded={moreOpen}
          aria-controls="mais-menu"
          onClick={() => setMoreOpen((v) => !v)}
          className={secondaryActive ? "active" : ""}
        >
          <Icon name="more" className="nav-icon" />
          <span>Mais</span>
          {unreadCount > 0 && <span className="nav-dot" role="img" aria-label="Há resultados não lidos" />}
        </button>
      </nav>
    </div>
  );
}
