#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  open -e .env
  echo "Created .env and opened it in TextEdit. Paste the bot token after DISCORD_TOKEN=, save, then double-click Start Time Bot.command again."
  exit 1
fi

requirements_hash="$(shasum -a 256 requirements.txt | awk '{print $1}')"
installed_hash=""
if [[ -f .venv/.requirements-hash ]]; then
  installed_hash="$(<.venv/.requirements-hash)"
fi

if [[ ! -d .venv || "$requirements_hash" != "$installed_hash" ]]; then
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  print -r -- "$requirements_hash" > .venv/.requirements-hash
fi

source .venv/bin/activate
exec python main.py
