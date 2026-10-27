/**
 * Visualização ao vivo do "navegador de pesquisa" (recurso futuro).
 * Fica oculta até chegar o primeiro evento `browser_frame` ({url, JPEG em base64}).
 *
 * O JPEG é decodificado com createImageBitmap e desenhado num <canvas>, sem URL `data:`/`blob:`,
 * para funcionar com a CSP estrita (img-src herdando default-src 'self').
 */
import { useEffect, useRef, useState } from "react";
import type { BrowserFrame } from "../api/types";

function frameBase64(f: BrowserFrame): string | null {
  const raw = f.image ?? f.jpeg_base64 ?? f.data ?? null;
  if (!raw) return null;
  const comma = raw.startsWith("data:") ? raw.indexOf(",") : -1;
  return comma >= 0 ? raw.slice(comma + 1) : raw;
}

function base64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function BrowserView({ frame, label = "Navegador de pesquisa" }: { frame: BrowserFrame | null; label?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!frame) return;
    const b64 = frameBase64(frame);
    const canvas = canvasRef.current;
    if (!b64 || !canvas) return;
    let cancelled = false;
    (async () => {
      try {
        const bitmap = await createImageBitmap(new Blob([base64ToBytes(b64)], { type: "image/jpeg" }));
        if (cancelled) return;
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
        bitmap.close();
        setError(false);
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [frame]);

  if (!frame) return null;
  return (
    <section className="card flat browser-view stack" aria-label={label}>
      <div className="row between">
        <span className="eyebrow">{label}</span>
        <span className="tiny muted mono" title={frame.url}>
          {frame.url.length > 60 ? `${frame.url.slice(0, 57)}…` : frame.url}
        </span>
      </div>
      <canvas ref={canvasRef} role="img" aria-label={`Captura da página ${frame.url}`} />
      {error && <p className="tiny muted">Não foi possível exibir este quadro.</p>}
      <p className="tiny muted">Somente leitura: o navegador de pesquisa não preenche formulários nem acessa contas.</p>
    </section>
  );
}
