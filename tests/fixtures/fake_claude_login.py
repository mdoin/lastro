"""`claude auth login --claudeai` falso: mostra o link num terminal e espera o código colado."""

import sys

if not sys.stdin.isatty():  # o CLI real só mostra o campo de código num terminal
    sys.exit(3)
print("\x1b[1mBrowser didn't open? Use the url below to sign in:\x1b[0m")
print("https://claude.ai/oauth/authorize?code=true&client_id=fake&state=xyz")
print("Paste code here if prompted > ", end="", flush=True)
code = sys.stdin.readline().strip()
sys.exit(0 if code == "CODIGO#123" else 1)
