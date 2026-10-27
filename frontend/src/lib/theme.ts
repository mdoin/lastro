// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Tema da interface: automático (segue o aparelho), claro ou escuro.
 * A escolha fica só neste navegador (localStorage) e é aplicada como `data-theme` no <html>;
 * `public/theme-init.js` faz o mesmo antes da primeira pintura, para não piscar o tema errado.
 */
import { useSyncExternalStore } from "react";

export type ThemePref = "system" | "light" | "dark";

const KEY = "lastro.theme";
/** Cor da barra do navegador no celular, igual ao fundo da página de cada tema. */
const BAR_COLOR = { light: "#f4f4f2", dark: "#0b0b0a" } as const;
const listeners = new Set<() => void>();

export function readThemePref(): ThemePref {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

/** Aplica a preferência ao documento (atributo do tema e cor da barra do navegador). */
export function applyThemePref(pref: ThemePref): void {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((m) => {
    const mode = pref !== "system" ? pref : (m.getAttribute("media") ?? "").includes("dark") ? "dark" : "light";
    m.setAttribute("content", BAR_COLOR[mode]);
  });
}

export function setThemePref(pref: ThemePref): void {
  try {
    if (pref === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, pref);
  } catch {
    /* armazenamento indisponível: vale só nesta visita */
  }
  applyThemePref(pref);
  listeners.forEach((l) => l());
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  // Outra aba mudou o tema: acompanha.
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      applyThemePref(readThemePref());
      cb();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function useThemePref(): ThemePref {
  return useSyncExternalStore(subscribe, readThemePref, () => "system");
}
