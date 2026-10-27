/**
 * Mascotes dos agentes do Lastro: pixel art autoral numa grade 16×16 (um caractere = um pixel).
 * Todos compartilham a linguagem: contorno de 1 px, luz no alto à esquerda, sombra embaixo à direita,
 * olhos 2×3 nas colunas 5–6 e 9–10. Cada um tem silhueta e acessório próprios.
 *
 * Legenda: "." vazio · o contorno · b base · h luz · s sombra · w branco do olho · p pupila (pisca) ·
 * e olho luminoso (pisca) · k boca/traço escuro · demais letras: cores do acessório (paleta de cada um).
 */

export const GRID = 16;

export interface Mascot {
  id: string;
  name: string;
  /** Texto alternativo: quem é, em poucas palavras. */
  alt: string;
  rows: string[];
  palette: Record<string, string>;
}

const SHARED = { w: "#ffffff", p: "#15151a", k: "#15151a" };

export const MASCOTS: Record<string, Mascot> = {
  mentor: {
    id: "mentor",
    name: "Mentor",
    alt: "Mentor: robozinho grafite com coroa dourada",
    palette: { ...SHARED, o: "#1b1b21", b: "#4a4b56", h: "#71727f", s: "#32333b", g: "#c79634", G: "#f2d27e" },
    rows: [
      "................",
      "....g..GG..g....",
      "....gGggggGg....",
      "....gggggggg....",
      "...oooooooooo...",
      "..ohhbbbbbbbbo..",
      "..ohbbbbbbbbbo..",
      "..obbwwbbwwbbo..",
      "..obbwpbbpwbbo..",
      "..obbwwbbwwbso..",
      "..obbbbkkbbbso..",
      "..obbbbbbbbsso..",
      "..oggggggggsso..",
      "..osbbbbbbssso..",
      "...oooooooooo...",
      "....oo....oo....",
    ],
  },
  planejador: {
    id: "planejador",
    name: "Planejador",
    alt: "Planejador: robozinho verde-sálvia segurando uma prancheta",
    palette: { ...SHARED, o: "#2b3a2d", b: "#8fae8b", h: "#b9d2b3", s: "#6c8c69", x: "#8a6a45", A: "#f6f1e3", a: "#3d7a44" },
    rows: [
      "................",
      "................",
      "................",
      "......oooo......",
      "....oohhbboo....",
      "...ohhbbbbbbo...",
      "..ohbbbbbbbbbo..",
      "..obbwwbbwwbbo..",
      "..obbwwbbwwbbo..",
      "..obbwpbbpwbbo..",
      "..obbbbbbxxxxo..",
      "..obbkkbbxaAxo..",
      "..obbbbbbxAAxo..",
      "..osbbbbbxaAxo..",
      "...ossssxxxxo...",
      "....oooooooo....",
    ],
  },
  analista: {
    id: "analista",
    name: "Analista",
    alt: "Analista: robozinho azul com um pequeno monitor de gráfico de barras na cabeça",
    palette: { ...SHARED, o: "#1a2b49", b: "#4d86d8", h: "#86b6f2", s: "#3467b2", x: "#0e1b30", a: "#d9a63f", A: "#ffe08a" },
    rows: [
      "........ooooo...",
      "........oxxAo...",
      "........oxaAo...",
      "........oaaAo...",
      "...oooooooooo...",
      "..ohhhbbbbbbbo..",
      "..ohbbbbbbbbbo..",
      "..obbwpbbwpbbo..",
      "..obbwwbbwwbbo..",
      "..obbwwbbwwbso..",
      "..obbbbbbbbbso..",
      "..obbbbkbbbbso..",
      "..obbbbbbbbsso..",
      "..osssssssssso..",
      "...oooooooooo...",
      "...oo......oo...",
    ],
  },
  economista: {
    id: "economista",
    name: "Economista",
    alt: "Economista: robozinho turquesa com um anel orbital e uma pequena lua",
    palette: { ...SHARED, o: "#103f3c", b: "#2fb2a5", h: "#74dccf", s: "#1e8a80", a: "#c79634", A: "#f2d27e", m: "#e9e4d6" },
    rows: [
      ".............m..",
      "................",
      "................",
      ".....oooooo.....",
      "...oohhbbbboo...",
      "..ohhbbbbbbbbo..",
      "aaoAAAAAAAAAAoaa",
      "..obbbbbbbbbbo..",
      "..obbpwbbpwbbo..",
      "..obbwwbbwwbbo..",
      "..obbwwbbwwbso..",
      "..obbbbbbkkbso..",
      "..obbbbbbbbsso..",
      "...osssssssso...",
      "....oooooooo....",
      "....oo....oo....",
    ],
  },
  riscos: {
    id: "riscos",
    name: "Gestor de Riscos",
    alt: "Gestor de Riscos: robozinho terracota, largo, com capacete e visor",
    palette: { ...SHARED, o: "#47200f", b: "#c6644a", h: "#e59173", s: "#9c4932", a: "#f2d27e", v: "#24130e", e: "#ffcf5a" },
    rows: [
      "................",
      "................",
      ".......oo.......",
      "......oaao......",
      "..oooooaaooooo..",
      ".ohhhbbbbbbbbbo.",
      ".ohbbbbbbbbbbbo.",
      ".obvvvvvvvvvvbo.",
      ".obvveevveevvbo.",
      ".obvvvvvvvvvvbo.",
      ".obbbbbbbbbbbso.",
      ".obbbbkkkkbbbso.",
      ".obbbbbbbbbbsso.",
      ".osssssssssssso.",
      "..oooooooooooo..",
      "..ooo......ooo..",
    ],
  },
  comportamental: {
    id: "comportamental",
    name: "Conselheiro",
    alt: "Conselheiro: robozinho lilás e redondo, com um coração e bochechas rosadas",
    palette: { ...SHARED, o: "#3c2959", b: "#a98ad8", h: "#cbb4f0", s: "#8567b6", c: "#ec79a6" },
    rows: [
      ".....cc..cc.....",
      ".....cccccc.....",
      "......cccc......",
      ".......cc.......",
      "......oooo......",
      "....oohhbboo....",
      "...ohhbbbbbbo...",
      "..ohbbbbbbbbbo..",
      "..obbpbbbbpbbo..",
      "..obpbpbbpbpbo..",
      "..obcbbkkbbcbo..",
      "..obbbbbbbbbso..",
      "...obbbbbbbso...",
      "....osssssso....",
      ".....oooooo.....",
      "................",
    ],
  },
  auditor: {
    id: "auditor",
    name: "Auditor",
    alt: "Auditor: robozinho cinza-azulado, alto, de óculos quadrados e sobrancelha erguida",
    palette: { ...SHARED, o: "#1e2832", b: "#7e90a4", h: "#a8b8c9", s: "#5d6e81", x: "#1a2129" },
    rows: [
      "................",
      "....oooooooo....",
      "...ohhbbbbbbo...",
      "...ohbbbbbbbo...",
      "...obbbbbkkbo...",
      "..obxxxxxxxxbo..",
      "..obxwwxxwwxbo..",
      "..obxwpxxpwxbo..",
      "..obxxxxxxxxbo..",
      "..obbbbbbbbbbo..",
      "..obbbbkkkbbso..",
      "..obbbbbbbbbso..",
      "..obbbbbbbbsso..",
      "..osbbbbbbssso..",
      "...osssssssso...",
      "....oo....oo....",
    ],
  },
};

export const EYE_CHARS = new Set(["w", "p", "e"]);

export interface Run {
  x: number;
  y: number;
  w: number;
  ch: string;
}

/** Junta pixels vizinhos da mesma cor numa linha: menos elementos no SVG, mesmo desenho. */
export function runs(rows: string[]): Run[] {
  const out: Run[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x]!;
      let end = x + 1;
      while (end < row.length && row[end] === ch) end++;
      if (ch !== ".") out.push({ x, y, w: end - x, ch });
      x = end;
    }
  });
  return out;
}
