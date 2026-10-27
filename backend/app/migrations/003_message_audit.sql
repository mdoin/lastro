-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v3: veredito do Auditor persistido junto da mensagem do painel.
ALTER TABLE messages ADD COLUMN audit_json TEXT;
