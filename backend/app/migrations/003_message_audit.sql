-- Lastro — v3: veredito do Auditor persistido junto da mensagem do painel.
ALTER TABLE messages ADD COLUMN audit_json TEXT;
