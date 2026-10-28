# SPDX-License-Identifier: AGPL-3.0-or-later
"""Que tipo de interação é esta mensagem, antes de decidir quem responde e se há reunião.

Regras de texto, sem modelo (custo zero, previsível, testado). Só classifica como conversa o que é claramente
social (saudação, papo, humor, pergunta sobre o próprio agente) e sem sinal financeiro forte; na dúvida, segue o
comportamento de sempre, cujos prompts também sabem responder a uma conversa casual. Reunião só com pedido
explícito; tema financeiro de decisão ("pensando em investir…") vira oferta do Bento, nunca reunião automática.
"""

import re

from .auditor import fold

CONVERSA, PERGUNTA, DECISAO, ANALISE, REUNIAO = "conversa", "pergunta", "decisao", "analise", "reuniao"

_SOCIAL = re.compile(
    r"^\W*(oi+|ola|ole|e ai|eai|eae|opa|fala|salve|bom dia|boa tarde|boa noite|hey|hello|alo)\b"
    r"|\b(como (voces|vcs|vc|voce|ce|cês|ces|vai|vao) ?(estao|esta|ta|tao|vai|vao|anda|andam)?\b|tudo (bem|bom|certo|joia)"
    r"|bater (um )?papo|(so )?(queria|quero) (conversar|bater|dar um oi|papear)|papo"
    r"|(to|estou|ando|tou) (meio |muito |bem )?(entediad|cansad|feliz|triste|animad|com sono|ansios|estressad|de bom humor"
    r"|de mau humor|sem nada)"
    r"|me conta (alguma coisa|algo|uma|um)|conta (uma piada|algo|alguma)|piada|kkk+|haha+|hehe+|obrigad|valeu|brigad"
    r"|tchau|ate (mais|logo|amanha)|boa semana|bom fim de semana|saudade|como foi (o |seu )?dia|que (calor|frio)"
    r"|(por que|pq|porque) (voce|vc|ce) (e|eh|anda|fica|ta|esta) (tao|assim|sempre)"
    r"|quem (e|sao) (voce|voces|vc|vcs)|o que (voce|voces|vc|vcs) (gosta|gostam|faz|fazem) (de|nas|no|quando))")
# Sinais fortes de que a mensagem é sobre dinheiro da pessoa (valor, operação, produto).
_MONEY = re.compile(
    r"r\$|\d+ ?(mil|reais|k)\b|\b(invest\w*|aplica\w*|carteira|reserva|divida\w*|cartao|orcamento|salario|"
    r"acoes|fii\w*|cdb|lci|lca|tesouro|selic|cdi|ipca|dolar|bitcoin|btc|cripto\w*|ethereum|previdencia|"
    r"emprestimo|financiamento|aposentadoria|patrimonio|rendimento\w*|juros|inflacao|economia|mercado|bolsa|imposto\w*|gast\w*|despesa\w*|renda|"
    r"poupa\w*|fundo\w*|etf\w*|acao|dinheiro|orcamento|cambio|dividendo\w*)\b")
_MEETING = re.compile(
    r"\b(convoc(a|ar|ue|aria|acao)\b|reun(e|a|am|ir|ir os|e os|a os)\b|abr(e|a|ir) (uma )?reuniao|faz(er)? (uma )?reuniao"
    r"|chama(r)? (o conselho|os especialistas|a equipe toda)|lev(a|ar|e) (isso |isto )?(ao|para o|pro) conselho"
    r"|junt(a|ar|e) (os|todos os) especialistas)")
_ANALYSIS = re.compile(r"\b(analis[ae]\w*|analise|avali[ae]\w*|avaliacao|parecer completo|diagnostico completo)\b")
_DECISION = re.compile(
    r"\b(pensando em|penso em|quero|queria|vou|devo|deveria|vale a pena|compensa|considerando|cogitando|planejando)"
    r"\b.{0,60}\b(invest\w*|aplica\w*|compra\w*|vend\w*|resgat\w*|quita\w*|financi\w*|coloca\w*|tira\w*|troca\w*)"
    r"|\b(discutir|conversar sobre|falar sobre|rever|revisar|repensar)\b.{0,30}\b(carteira|reserva|investimentos|"
    r"financas|aposentadoria|dividas|orcamento|patrimonio)")
PLURAL = re.compile(r"\b(pessoal|galera|gente|voces|vcs|todos|todo mundo|time|equipe|turma|povo)\b")
_YES = re.compile(r"^\W*(sim|pode|bora|claro|ok|okay|beleza|blz|vamos|quero|por favor|manda|reune|reuna|convoca|"
                  r"faz isso|fechado|isso|com certeza|pode ser)\b")


def classify(text: str) -> str:
    folded = fold(text or "").strip()
    if _MEETING.search(folded):
        return REUNIAO
    money = bool(_MONEY.search(folded))
    if _ANALYSIS.search(folded) and money:
        return ANALISE
    if _DECISION.search(folded):
        return DECISAO
    if (_SOCIAL.search(folded) or preferred_name(text)) and not money:
        return CONVERSA
    return PERGUNTA


def is_plural(text: str) -> bool:
    return bool(PLURAL.search(fold(text or "")))


def accepts(text: str) -> bool:
    """Resposta curta de aceite a uma oferta ("sim, pode reunir")."""
    folded = fold(text or "").strip()
    return len(folded) <= 80 and bool(_YES.search(folded)) and "nao" not in folded.split()


_NAME = re.compile(r"\b(?:pode me chamar de|me chama de|me chame de|prefiro ser chamad[ao] de|prefiro que me chamem de|"
                   r"meu nome [eé])\s+([^\W\d_][\w'-]{1,29})", re.IGNORECASE)
_NOT_NAMES = {"voce", "você", "vc", "que", "um", "uma", "o", "a", "nada", "qualquer"}


def preferred_name(text: str) -> str | None:
    """Nome que a própria pessoa disse no chat ("pode me chamar de Ana"). Só vira perfil se ela confirmar."""
    match = _NAME.search(text or "")
    if not match or match.group(1).lower() in _NOT_NAMES:
        return None
    name = match.group(1)
    return name[0].upper() + name[1:]


def topic_left(text: str) -> str:
    """O que sobra de um pedido de reunião depois de tirar o pedido em si ("Bento, convoca uma reunião" → "")."""
    rest = _MEETING.sub(" ", fold(text or ""))
    rest = re.sub(r"\b(reuniao|conselho|especialistas|bento|mentor|por favor|pf|pls|uma|um|a|o|os|as|ai|agora|pra|para|sobre|isso|isto|de|do|da)\b",
                  " ", rest)
    return re.sub(r"[\W_]+", " ", rest).strip()
