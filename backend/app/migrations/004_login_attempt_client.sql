-- SPDX-License-Identifier: AGPL-3.0-or-later
-- Lastro — v4: tentativas de login guardam o cliente (IP; IPv6 por /64), para o bloqueio valer só para quem errou.
ALTER TABLE login_attempts ADD COLUMN client TEXT NOT NULL DEFAULT '';
CREATE INDEX login_attempts_client_at ON login_attempts (client, at);
CREATE INDEX login_attempts_at ON login_attempts (at);
