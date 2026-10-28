# Livro de movimentações, memória financeira automática e Caixa de entrada

**O que a pessoa diz e os documentos que ela envia viram registros, sem formulário duplicado. Retratos financeiros
continuam intocados.** Código em `backend/ledger/`, rotas em `backend/app/ledger_web.py`, migração 010.

## Três camadas de número (e de onde cada uma vem)
| Camada | Onde | Quem escreve | Natureza |
|---|---|---|---|
| Informado | `financial_snapshots` (retrato do mês) | só a pessoa, na tela Minha vida financeira | append-only; nunca recebe campo desconhecido como zero |
| Fato datado | `financial_facts` (saldo disponível, renda informada, despesa recorrente, dívida, meta) | a pessoa; frases dela na conversa viram fato (com consentimento) ou proposta | histórico com `superseded`; desfazer restaura o anterior |
| Derivado | `ledger_entries` (movimentações) | conversa (frases explícitas), documentos, IA (sempre pendente) | totais só com `registrado` + efetivado; dependem de conciliação |

`book.summary()` (Minha vida financeira → "Movimentações do mês" e a ferramenta `movimentacoes`) soma receitas e
despesas registradas e efetivadas. Estorno e reembolso abatem despesas. Transferência entre contas próprias,
pagamento de fatura e saldo bancário aparecem à parte e **não** são receita nem despesa. Lançamento agendado ou
pendente (`settled = 0`) não conta.

## Conversa → registro (`ledger/capture.py`)
Determinístico, só sobre mensagens da própria pessoa (texto de agente nunca registra nada). Classes: fato financeiro,
receita realizada, despesa realizada, transferência, saldo ou disponibilidade, despesa recorrente, dívida, meta,
decisão, intenção futura, simulação, informação insuficiente.

| Frase | Resultado |
|---|---|
| "Gastei R$ 38 no Uber hoje." | despesa de transporte, data de hoje |
| "Recebi R$ 3.700 de salário." | receita realizada (data da mensagem, marcada como suposta) |
| "Tenho R$ 400 sobrando para investir." | fato `disponivel_para_investir` datado — nenhuma receita |
| "Talvez eu compre um notebook de R$ 4.000." | intenção: nada é registrado (a captura fica como informativa) |
| "Meu aluguel é R$ 1.200 por mês." | proposta de despesa recorrente (sempre pendente, mesmo com consentimento) |
| "Paguei a conta de luz ontem." | pendência que pede **só** o valor |
| "Não gastei R$ 50" / "E se eu colocar…" | nada |

Com o consentimento **Registrar automaticamente** (`consents.auto_register`, desligado por padrão), o que está
completo e sem conflito é registrado pelo backend e o chat mostra uma confirmação discreta com **Desfazer**. Sem ele,
ou com ambiguidade (valor faltando, transferência para terceiros, parecido com algo já registrado), vira pendência.
Decisão ("decidi quitar o cartão") só aponta para o Diário: quem confirma decisões é a pessoa, lá.

## Caixa de entrada (`ledger/inbox.py`, `ledger/parsers.py`)
1. Rota autenticada (sessão + `X-Lastro`), corpo binário com tamanho limitado durante a leitura (10 MB), até
   `LASTRO_DOCS_PER_DAY` (40) por dia e `LASTRO_DOCS_MAX` (500) guardados.
2. Tipo pelo **conteúdo** (`sniff`), não pela extensão: PDF, PNG, JPG, CSV, OFX. Executáveis, HTML e afins → 415.
3. Documento repetido (sha256 por pessoa) devolve o existente, sem reprocessar.
4. Arquivo gravado em `LASTRO_DOCS_DIR` (padrão `<pasta do banco>/documentos`, 0700) com nome aleatório de 32
   hexadecimais, permissão 0600, fora de qualquer pasta servida. O nome enviado só é exibido (sanitizado).
5. Leitura: CSV e OFX por parsers determinísticos; PDF pelo texto (`pypdf`, extra `documents`); imagem por OCR local
   (`tesseract`, se instalado — `ledger/ocr.py`). Sem leitura possível → `sem_leitura`, nada é enviado a ninguém.
6. Normalização (Decimal, datas, moeda; conta só com os 4 últimos dígitos), impressão digital por movimentação
   (FITID/identificador quando há; senão data+valor+descrição+conta+ordem) → reimportar não duplica.
7. Classificação: pagamento de fatura, transferência, estorno (ligado à compra original), reembolso, parcelas,
   lançamento futuro; saldo vai para `account_balances`.
8. Conciliação: mesma data, valor e contraparte compatível de outra origem (extrato × comprovante) → `duplicada`
   (não conta; "Não é duplicata" desfaz); parecido em até 3 dias → pendência `possivel_duplicata`; −X/+X entre
   documentos diferentes com cara de transferência → ambos viram transferência.
9. Registro: com consentimento, itens de confiança alta/média, em reais e sem conflito; o resto fica pendente.
10. A Mila responde na conversa de onde veio o arquivo com os números reais ("Identifiquei N… X registradas…").

**Leitura por IA (opcional):** só quando a pessoa pede, documento a documento, com o consentimento
`ai_documents` e aviso de que o **texto** (nunca a imagem) vai ao provedor configurado para a Mila. A sessão usa o
papel interno `extrator`, **sem nenhuma ferramenta**; o texto entra marcado como dado não confiável; a resposta só é
aceita como lista JSON com as chaves pedidas, data válida e valor decimal. Tudo fica pendente, confiança baixa.

**Retenção:** `LASTRO_DOCS_RETENTION_DAYS` (padrão 90; 0 = apaga o arquivo logo após a leitura). Vencido o prazo, o
arquivo é apagado e ficam os metadados e os lançamentos com a origem. Excluir um documento apaga o arquivo e,
se a pessoa escolher, desfaz/descarta os lançamentos que vieram dele.

## Auditoria e permissões
- Toda mudança de lançamento gera `ledger_events` (append-only, antes/depois, autor); rotas registram `audit_log`.
- Agentes só leem (`movimentacoes`, `caixa_documentos`, via API GET-only). Nenhuma ferramenta de escrita foi criada.
- Logs registram ids e contagens, nunca nome de arquivo, conteúdo, valores ou descrições.
- Isolamento: toda consulta filtra por `user_id`; recurso de outra pessoa responde 404.

## Implantação
Backup (`.backup /var/lib/patrimonio/pre-v10.db`), `uv sync --extra documents` (PDF), opcionalmente
`apt install tesseract-ocr tesseract-ocr-por` (imagens), `npm run build` e `sudo scripts/deploy.sh`. A migração 010
só cria tabelas; o código anterior as ignora.
