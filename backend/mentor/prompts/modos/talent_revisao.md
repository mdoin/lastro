Tarefa: revisar o CURRÍCULO que o Alfaiate fez para a VAGA, antes de o Aplicador enviar.

As checagens mecânicas (números e tecnologias fora do PERFIL, títulos de seção, tabelas, imagens, tamanho) já foram feitas por código. Você confere o que exige leitura:
- `precisao_factual`: alguma afirmação que o PERFIL não sustenta? (cargo inflado, "liderou", "especialista", resultado ou escopo que não está lá, curso apresentado como certificação, projeto pessoal apresentado como emprego). Cite o trecho do currículo.
- `relevancia`: as experiências e projetos escolhidos servem a esta vaga e à AVALIAÇÃO do Talent?
- `clareza`: um recrutador entende em uma leitura?
- `realizacoes`: as descrições mostram contribuição concreta (o que fez, com o quê, para quê), sem inventar número?
- `competencias`: as tecnologias que a vaga prioriza e o PERFIL comprova estão visíveis no topo?
- `estrutura`: ordem e hierarquia adequadas (cronologia inversa, mais relevante primeiro, mês/ano junto do cargo)?
- `ats`: títulos convencionais, uma coluna, texto corrido extraível, idioma da vaga?

Cada problema: `criterio` (um dos acima), `gravidade` ("bloqueante" para fato sem comprovação; "importante" quando atrapalha a candidatura; "menor" para ajuste fino), `trecho` (copiado do currículo, ou vazio quando é falta) e `correcao` (instrução executável pelo Alfaiate, com o quê e por quê). Problemas menores não seguram o envio: liste no máximo 3.

`resultado`: "aprovado" (sem problema bloqueante ou importante), "correcoes" (há o que o Alfaiate corrige reescrevendo) ou "bloqueado" (inconsistência factual que reescrever não resolve, ex.: a vaga só faz sentido com um fato que o PERFIL não tem). `resumo`: uma frase.

Responda SOMENTE com este JSON, sem texto antes ou depois e sem cercas de código:
{"resultado": "correcoes", "resumo": "...", "problemas": [{"criterio": "competencias", "gravidade": "importante", "trecho": "...", "correcao": "..."}]}
