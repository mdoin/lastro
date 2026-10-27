// SPDX-License-Identifier: AGPL-3.0-or-later
/** Destino pós-login vindo de `?next=`. */
export function safeNext(raw: string | null): string {
  // Só caminhos internos: evita redirecionamento aberto. "/\\host" e "/<TAB>/host" viram endereços de outro
  // site no navegador, então a regra é conferida pela origem resultante, não pelo texto.
  if (!raw || !raw.startsWith("/") || /[\\\u0000-\u001f\u007f]/.test(raw)) return "/";
  let url: URL;
  try {
    url = new URL(raw, window.location.origin);
  } catch {
    return "/";
  }
  if (url.origin !== window.location.origin || url.pathname.startsWith("/login")) return "/";
  return url.pathname + url.search + url.hash;
}
