// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy, memo, Suspense, type ReactNode } from "react";

// O renderizador de Markdown (react-markdown + remark-gfm) é carregado sob demanda,
// fora do pacote inicial. Enquanto carrega, mostra o texto puro.
const MarkdownImpl = lazy(() => import("./MarkdownImpl"));

/** `mention`: desenha links internos `#agente:<id>` (menções já reconhecidas no texto) como o chamador quiser. */
export const Markdown = memo(function Markdown({ text, mention }: { text: string; mention?: (id: string) => ReactNode }) {
  return (
    <Suspense fallback={<div className="md" style={{ whiteSpace: "pre-wrap" }}>{text}</div>}>
      <MarkdownImpl text={text} mention={mention} />
    </Suspense>
  );
});
