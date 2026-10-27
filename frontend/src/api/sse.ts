/**
 * Parser de Server-Sent Events para respostas de POST lidas com fetch + ReadableStream.
 * Segue o formato do WHATWG (event:/data:/id:, comentários com ":", fim de evento em linha vazia,
 * CRLF/LF/CR), sem depender de EventSource (que só faz GET).
 */

export interface SSEFrame {
  event: string;
  data: string;
  id?: string;
}

export class SSEParser {
  private buffer = "";
  private eventName = "";
  private dataLines: string[] = [];
  private lastId: string | undefined;
  private hasData = false;

  /** Recebe um pedaço de texto (já decodificado) e devolve os eventos completos. */
  feed(chunk: string): SSEFrame[] {
    this.buffer += chunk;
    const frames: SSEFrame[] = [];
    for (;;) {
      const match = /\r\n|\n|\r/.exec(this.buffer);
      if (!match) break;
      // "\r" no fim do buffer pode ser metade de um "\r\n": espera o próximo pedaço.
      if (match[0] === "\r" && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const frame = this.processLine(line);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  /** Fim do fluxo: processa o que restou (tolerante a um último evento sem linha vazia final). */
  end(): SSEFrame[] {
    const frames: SSEFrame[] = [];
    if (this.buffer.length > 0) {
      const rest = this.buffer.replace(/\r$/, "");
      this.buffer = "";
      const f = this.processLine(rest);
      if (f) frames.push(f);
    }
    const last = this.dispatch();
    if (last) frames.push(last);
    return frames;
  }

  private processLine(line: string): SSEFrame | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null; // comentário / keep-alive
    const colon = line.indexOf(":");
    let field: string;
    let value: string;
    if (colon === -1) {
      field = line;
      value = "";
    } else {
      field = line.slice(0, colon);
      value = line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
    }
    switch (field) {
      case "event":
        this.eventName = value;
        break;
      case "data":
        this.dataLines.push(value);
        this.hasData = true;
        break;
      case "id":
        if (!value.includes("\u0000")) this.lastId = value;
        break;
      default:
        break; // "retry" e campos desconhecidos são ignorados
    }
    return null;
  }

  private dispatch(): SSEFrame | null {
    if (!this.hasData) {
      this.eventName = "";
      return null;
    }
    const frame: SSEFrame = { event: this.eventName || "message", data: this.dataLines.join("\n") };
    if (this.lastId !== undefined) frame.id = this.lastId;
    this.eventName = "";
    this.dataLines = [];
    this.hasData = false;
    return frame;
  }
}

/** Lê um corpo de resposta SSE e chama `onFrame` a cada evento completo. */
export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: SSEFrame) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new SSEParser();
  const onAbort = () => {
    reader.cancel().catch(() => undefined);
  };
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const f of parser.feed(decoder.decode(value, { stream: true }))) onFrame(f);
    }
    for (const f of parser.feed(decoder.decode())) onFrame(f);
    for (const f of parser.end()) onFrame(f);
  } finally {
    signal?.removeEventListener("abort", onAbort);
    try {
      reader.releaseLock();
    } catch {
      /* leitor já liberado */
    }
  }
}
