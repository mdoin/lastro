// SPDX-License-Identifier: AGPL-3.0-or-later
import { lazy, memo, Suspense } from "react";

// O renderizador de Markdown (react-markdown + remark-gfm) é carregado sob demanda,
// fora do pacote inicial. Enquanto carrega, mostra o texto puro.
const MarkdownImpl = lazy(() => import("./MarkdownImpl"));

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <Suspense fallback={<div className="md" style={{ whiteSpace: "pre-wrap" }}>{text}</div>}>
      <MarkdownImpl text={text} />
    </Suspense>
  );
});
