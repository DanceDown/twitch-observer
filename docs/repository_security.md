# Repository Publication Safety

Last checked: 2026-08-07

This document lists what to verify before publishing this repository or pushing
it to a public GitHub remote.

## Current status

- `.env`, `src/.env`, and `.env.*` are ignored. `.env.example` is intentionally
  allowed as the public placeholder file.
- `.data/` is ignored and should contain local PostgreSQL data only.
- `.venv/`, `.tmp/`, Python caches, editor settings, local Codex/agent folders,
  and Docker override files are ignored.
- `.dockerignore` also excludes local environment files, runtime data, Git
  metadata, caches, editor settings, local agent folders, database files, logs,
  and secret-looking files from Docker build contexts.
- A Git tracked-file check found no tracked `.env`, `src/.env`, `.data`,
  `.codex`, `.agents`, or `.vscode` entries.

## Never commit

Do not commit:

- `.env` or other real environment files;
- Discord bot tokens or application secrets;
- Twitch client secrets, OAuth access tokens, or OAuth refresh tokens;
- PostgreSQL passwords, database dumps, or `.data/postgres` contents;
- private keys, certificates, webhook URLs, API keys, or service credentials;
- local editor settings, local agent settings, logs, and temporary files.

## Safe public files

These files are expected to be public:

- `.env.example`, as long as it contains placeholders only;
- source code under `src/`;
- docs under `docs/`;
- Docker files that do not include secrets;
- language files under `lang/`.

## Pre-push checklist

Run these checks before making the repository public:

```powershell
git status --short
git ls-files .env src/.env .data .codex .agents .vscode
git check-ignore -v .env src/.env .data/postgres .env.local .codex .agents .vscode
git grep --untracked -n -I -E "DISCORD_BOT_TOKEN|TWITCH_CLIENT_SECRET|ACCESS_TOKEN|REFRESH_TOKEN|PRIVATE KEY|API_KEY|WEBHOOK|POSTGRES_PASSWORD" -- .
```

The second command should print nothing. The search command may find placeholder
names in code, docs, and `.env.example`; it should not show real secret values.

## If a secret was committed

If a real secret was committed, do not only delete the file in a later commit.
Treat the secret as exposed:

- revoke or rotate the affected Discord, Twitch, database, webhook, or API
  secret;
- replace the local secret with the new value;
- remove the secret from Git history before publishing, if the repository is not
  public yet;
- check local backups, build logs, and deployment systems for copied secrets.
