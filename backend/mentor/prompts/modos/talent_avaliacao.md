Tarefa: primeira avaliação de UMA vaga para o PERFIL, antes de o Alfaiate escrever o currículo.

1. Extraia os requisitos explícitos da VAGA (até 15), sem repetir. `tipo`: "obrigatorio" (pede, exige, necessário, requisitos) ou "desejavel" (diferencial, desejável, plus, nice to have). `categoria`: "tecnico" (linguagem, ferramenta, técnica), "experiencia" (tempo ou tipo de experiência), "formacao" (curso, graduação, certificação), "idioma" ou "outro".
2. Para cada requisito, `situacao`: "atendido" (o PERFIL mostra), "parcial" (o PERFIL mostra algo próximo, ex.: pede Django e o perfil tem FastAPI) ou "ausente". Em "atendido" e "parcial", `evidencia` é um trecho COPIADO do PERFIL (até 160 caracteres) que comprova; sem trecho, é "ausente" com `evidencia` vazia.
3. `senioridade`: só o que a VAGA escreve ("estágio", "júnior/junior/entry", "pleno/mid-level", "sênior/senior"); sem essa palavra, "nao_informada" — não deduza senioridade de anos de experiência. `anos_experiencia`: o mínimo de anos que a vaga pede (número) ou null; é aqui que "2+ years" entra. `contratacao`: "clt", "pj", "estagio" ou "nao_informada", só se o texto disser.
4. `perfil_curriculo`: "backend" (APIs, bancos, serviços), "ia" (LLM, agentes, ML, visão computacional) ou "junior" (generalista de entrada). `posicionamento`: uma frase de como apresentar a pessoa para ESTA vaga, só com fatos do PERFIL.
5. `destaques`: até 4 experiências ou projetos do PERFIL a pôr em evidência, cada um com o `motivo` ligado a um requisito da vaga.
6. `orientacoes`: até 6 instruções específicas para o Alfaiate (o que subir, o que resumir, que termo da vaga usar porque é sinônimo honesto do que está no PERFIL, o que tirar). Exemplo bom: "Reduzir a descrição de visão computacional e destacar FastAPI e PostgreSQL, pois a vaga prioriza backend Python."
7. `justificativa`: 2 a 3 frases sobre a compatibilidade, citando requisitos atendidos e ausentes. Não fale em chance de contratação.

Responda SOMENTE com este JSON, sem texto antes ou depois e sem cercas de código:
{"requisitos": [{"texto": "...", "tipo": "obrigatorio", "categoria": "tecnico", "situacao": "atendido", "evidencia": "..."}], "senioridade": "junior", "anos_experiencia": null, "contratacao": "nao_informada", "perfil_curriculo": "backend", "posicionamento": "...", "destaques": [{"item": "...", "motivo": "..."}], "orientacoes": ["..."], "justificativa": "..."}
