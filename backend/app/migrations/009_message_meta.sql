-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v9: metadados de mensagem (docs/MULTIAGENT.md): conexão e modelo que escreveram a resposta, versão do
-- registro do agente, posição declarada no parecer do Conselho e mapa de posições.
-- Compatível: só acrescenta uma coluna; o código anterior a ignora.

ALTER TABLE messages ADD COLUMN meta_json TEXT;
