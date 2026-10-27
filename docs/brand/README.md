# Marca do Lastro — "Bloco L"

![Quadro da marca](lastro-marca.png)

## Conceito

Um **L maciço com as faces superiores em ouro**. Duas leituras de *lastro* no mesmo desenho:

- a **base que sustenta** — o lastro que mantém um barco de pé (a reserva que faz você voltar ao prumo depois de um imprevisto);
- o **ouro que dá valor** — o lastro-ouro de uma moeda.

O bloco é tinta (ou marfim, no escuro) e o ouro aparece só nas arestas: a marca convive com a interface monocromática
sem disputar atenção, e o dourado fica reservado para o que tem significado.

## Arquivos

| Arquivo | Uso |
|---|---|
| `svg/lastro-simbolo.svg` · `svg/lastro-simbolo-escuro.svg` | Símbolo sozinho, fundo claro / escuro |
| `svg/lastro-assinatura-horizontal(-escuro).svg` | Símbolo + nome lado a lado (padrão) |
| `svg/lastro-assinatura-empilhada(-escuro).svg` | Símbolo sobre o nome (espaços quadrados) |
| `svg/lastro-icone-app.svg` | Ícone com cantos arredondados (grafite, marfim e ouro) |
| `svg/lastro-icone-app-quadrado.svg` | Ícone sangrado, para sistemas que arredondam sozinhos (iOS) |
| `svg/lastro-icone-maskable.svg` | Ícone com área de segurança, para Android ("maskable") |
| `svg/favicon.svg` | Favicon (quadrado escuro: legível em abas claras e escuras) |
| `png/` | Exportações prontas (ícone 1024 px, assinaturas a 256 px de altura) |

No app, os mesmos arquivos estão em `frontend/public/`: `favicon.svg`, `apple-touch-icon.png` (180),
`icon-192.png`, `icon-512.png`, `icon-maskable-512.png` e `manifest.webmanifest` (instalar na tela inicial).
O componente `BrandMark` (`frontend/src/components/Icon.tsx`) desenha o símbolo com as cores do tema.

## Construção

Grade de 64 unidades. Braço `T = 10,5`, comprimento `A = 31,5` (braços iguais), extrusão `d = 3,6 × 3,3`
para cima e para a direita. Face frontal com origem em `(14,25; 18,5)`; o conjunto fica levemente abaixo do
centro geométrico para compensar o peso visual da face escura.

O nome é a **Inter** (corte óptico display, peso 640, espaçamento −0,032 em), convertida em curvas nos SVGs com
kerning real; as coordenadas são inteiras e separadas por vírgula (o teste de higiene do repositório procura
sequências longas de dígitos). Na assinatura horizontal, a base do nome se alinha à base do bloco.

## Cores

| Papel | Claro | Escuro |
|---|---|---|
| Face frontal | Tinta `#121211` | Marfim `#F3EFE6` |
| Face superior (ouro claro) | `#D9B25B` | `#E3BD68` |
| Face lateral (ouro profundo) | `#A7781F` | `#B4852A` |
| Ícone do app | Grafite `#2E2E2B → #0A0A09`, marfim em degradê, ouro em degradê | — |

Na interface, o ouro de texto é `#835F14` (claro, ≥ 4,5:1) / `#E2BE6E` (escuro) e o ouro gráfico é `#B38328`.

## Uso

- **Respiro mínimo:** ¼ da altura do símbolo em volta de toda a marca.
- **Tamanho mínimo:** símbolo com 16 px; assinatura horizontal com 96 px de largura.
- **Fundos:** versão tinta sobre claros, versão marfim sobre escuros; em fotos ou fundos agitados, use o ícone do app.

Não faça: distorcer ou girar o bloco, trocar o ouro por outra cor, inverter a direção da extrusão, aplicar sombra,
contorno ou brilho extra, recompor o nome com outra fonte, usar o dourado em textos longos.
