# SPDX-License-Identifier: AGPL-3.0-or-later
"""OCR local de imagens da Caixa de entrada (tesseract), sem rede e sem shell.

Exceção consciente à regra "backend sem subprocess" (tests/security/test_no_financial_execution.py): executa só o
binário `tesseract` encontrado no PATH, com argumentos fixos, a imagem pela entrada padrão e prazo de 60 s.
Sem o tesseract instalado, a imagem fica "sem leitura" e não é enviada a ninguém.
"""

import shutil
import subprocess

from .parsers import UnsupportedDocument


def available() -> bool:
    return shutil.which("tesseract") is not None


def tesseract(data: bytes) -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise UnsupportedDocument("Imagem sem OCR nesta instalação: instale o tesseract no servidor ou envie o "
                                  "PDF/CSV/OFX do banco.")
    try:
        proc = subprocess.run([exe, "stdin", "stdout", "-l", "por+eng"], input=data, capture_output=True,  # noqa: S603
                              timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise UnsupportedDocument("Não foi possível ler a imagem.") from None
    if proc.returncode != 0:
        raise UnsupportedDocument("Não foi possível ler a imagem.")
    return proc.stdout.decode("utf-8", "replace")
