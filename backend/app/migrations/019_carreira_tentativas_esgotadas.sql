-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v19: só dados. Candidaturas que esgotaram as 2 tentativas antes da migração 018 ficaram como
-- "curriculo" (na fila), mas o Aplicador não as tenta mais: passam a "falhou", com evento no histórico.

INSERT INTO carreira_eventos (vaga_id, tipo, origem, detalhe_json, created_at)
    SELECT vaga_id, 'candidatura_falhou', 'sistema',
           json_object('motivo', 'tentativas esgotadas antes do registro de falhas', 'reconstruido', 1),
           strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
    FROM carreira_candidaturas c
    WHERE status = 'curriculo' AND (SELECT COUNT(*) FROM carreira_envios e WHERE e.vaga_id = c.vaga_id) >= 2;
UPDATE carreira_candidaturas SET status = 'falhou', updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
    WHERE status = 'curriculo' AND (SELECT COUNT(*) FROM carreira_envios e WHERE e.vaga_id = carreira_candidaturas.vaga_id) >= 2;
