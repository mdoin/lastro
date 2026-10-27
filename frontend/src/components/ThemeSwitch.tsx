import { setThemePref, useThemePref, type ThemePref } from "../lib/theme";
import { Icon, type IconName } from "./Icon";

const OPTIONS: { value: ThemePref; label: string; icon: IconName }[] = [
  { value: "system", label: "Automático", icon: "monitor" },
  { value: "light", label: "Claro", icon: "sun" },
  { value: "dark", label: "Escuro", icon: "moon" },
];

/** Escolha do tema. `compact` mostra só os ícones (barra lateral e menu do celular). */
export function ThemeSwitch({ compact = false }: { compact?: boolean }) {
  const pref = useThemePref();
  return (
    <div className={`segmented theme-switch ${compact ? "compact" : ""}`} role="group" aria-label="Tema">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={pref === o.value}
          aria-label={compact ? `Tema ${o.label.toLowerCase()}` : undefined}
          title={compact ? (o.value === "system" ? "Automático (segue o aparelho)" : `Tema ${o.label.toLowerCase()}`) : undefined}
          onClick={() => setThemePref(o.value)}
        >
          <Icon name={o.icon} />
          {!compact && <span>{o.label}</span>}
        </button>
      ))}
    </div>
  );
}
