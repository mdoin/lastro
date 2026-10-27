// SPDX-License-Identifier: AGPL-3.0-or-later
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown do mentor. HTML bruto é descartado (`skipHtml`, sem rehype-raw) e imagens não são
 * renderizadas (evitam requisições a terceiros e seriam bloqueadas pela CSP de qualquer forma).
 */
/** Host de um link absoluto http(s), para mostrar o destino real ao lado do texto (que o modelo escolhe). */
export function externalHost(href: string | undefined): string | null {
  if (!href) return null;
  try {
    const url = new URL(href);
    return url.protocol === "http:" || url.protocol === "https:" ? url.hostname : null;
  } catch {
    return null;
  }
}

const components: Components = {
  a: ({ href, children }) => {
    const host = externalHost(href);
    if (!host) return <a href={href}>{children}</a>; // âncoras internas (ex.: notas de rodapé) abrem na mesma aba
    return (
      <a href={href} target="_blank" rel="noopener noreferrer nofollow" title={href}>
        {children}
        <span className="md-link-host"> ({host})</span>
      </a>
    );
  },
  table: ({ children }) => <table>{children}</table>,
};

export default function MarkdownImpl({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        disallowedElements={["img"]}
        unwrapDisallowed
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
