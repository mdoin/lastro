# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compatibilidade: o turno do Claude Code mora agora no adaptador `providers.claude_code`."""

from providers.base import TurnOutcome  # noqa: F401
from providers.claude_code import run_turn, short_tool_name  # noqa: F401
