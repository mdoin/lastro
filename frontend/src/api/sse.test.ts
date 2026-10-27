// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { SSEParser, readSSE, type SSEFrame } from "./sse";

function parseAll(chunks: string[]): SSEFrame[] {
  const p = new SSEParser();
  const out: SSEFrame[] = [];
  for (const c of chunks) out.push(...p.feed(c));
  out.push(...p.end());
  return out;
}

describe("SSEParser", () => {
  it("lê eventos nomeados com JSON", () => {
    const frames = parseAll(['event: delta\ndata: {"text":"Olá"}\n\nevent: done\ndata: {"ok":true}\n\n']);
    expect(frames).toEqual([
      { event: "delta", data: '{"text":"Olá"}' },
      { event: "done", data: '{"ok":true}' },
    ]);
  });

  it("junta pedaços quebrados em qualquer ponto", () => {
    const raw = 'event: tool\ndata: {"name":"diagnostico","input":{}}\n\nevent: delta\ndata: {"text":"a"}\n\n';
    for (let i = 1; i < raw.length; i++) {
      const frames = parseAll([raw.slice(0, i), raw.slice(i)]);
      expect(frames.map((f) => f.event)).toEqual(["tool", "delta"]);
    }
  });

  it("aceita CRLF e CR, inclusive com CRLF partido entre pedaços", () => {
    expect(parseAll(["event: a\r\ndata: 1\r", "\n\r\n"])).toEqual([{ event: "a", data: "1" }]);
    expect(parseAll(["event: b\rdata: 2\r\r"])).toEqual([{ event: "b", data: "2" }]);
  });

  it("concatena múltiplas linhas data com \\n", () => {
    expect(parseAll(["data: linha 1\ndata: linha 2\n\n"])).toEqual([{ event: "message", data: "linha 1\nlinha 2" }]);
  });

  it("ignora comentários, keep-alive e campos desconhecidos", () => {
    expect(parseAll([": ping\n\nretry: 1000\nfoo: bar\nevent: x\ndata: {}\n\n"])).toEqual([{ event: "x", data: "{}" }]);
  });

  it("evento sem data não é despachado e não vaza o nome", () => {
    expect(parseAll(["event: vazio\n\ndata: 1\n\n"])).toEqual([{ event: "message", data: "1" }]);
  });

  it("remove só um espaço depois dos dois-pontos", () => {
    expect(parseAll(["data:  dois espaços\n\n"])).toEqual([{ event: "message", data: " dois espaços" }]);
    expect(parseAll(["data:colado\n\n"])).toEqual([{ event: "message", data: "colado" }]);
  });

  it("guarda id", () => {
    expect(parseAll(["id: 7\nevent: e\ndata: x\n\n"])).toEqual([{ event: "e", data: "x", id: "7" }]);
  });

  it("tolera último evento sem linha vazia final", () => {
    expect(parseAll(['event: done\ndata: {"a":1}'])).toEqual([{ event: "done", data: '{"a":1}' }]);
  });
});

describe("readSSE", () => {
  it("decodifica UTF-8 partido entre bytes", async () => {
    const bytes = new TextEncoder().encode('event: delta\ndata: {"text":"ação"}\n\n');
    const split = bytes.indexOf(0xc3) + 1; // corta no meio de "ç"
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, split));
        c.enqueue(bytes.slice(split));
        c.close();
      },
    });
    const frames: SSEFrame[] = [];
    await readSSE(stream, (f) => frames.push(f));
    expect(frames).toEqual([{ event: "delta", data: '{"text":"ação"}' }]);
  });
});
