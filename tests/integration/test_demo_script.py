# SPDX-License-Identifier: AGPL-3.0-or-later
"""O demo não pode contradizer o diagnóstico (achado do agente AG-00 em 2026-10-26)."""
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2] / "scripts" / "demo.py"


def run(*args):
    return subprocess.run([sys.executable, str(DEMO), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def test_projection_hidden_when_next_step_is_paying_debt():
    out = run("cartao-rotativo", "300", "120")
    assert "Projeção omitida" in out and "nominal" not in out


def test_forced_projection_is_labelled_and_warns_about_budget_and_debt():
    out = run("cartao-rotativo", "300", "120", "--projecao")
    assert "HIPOTÉTICA" in out
    assert "passa da sobra mensal" in out
    assert "ignora as dívidas" in out


def test_investing_persona_shows_full_fingerprint_and_purchasing_power_note():
    out = run("reserva-completa-1000", "1000", "120")
    fingerprints = [line.split()[-1] for line in out.splitlines() if "inputs_fingerprint" in line]
    assert len(fingerprints) == 3 and all(len(f) == 64 for f in fingerprints)
    assert "Projeção omitida" not in out
