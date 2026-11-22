# Security

audium holds accounts, passwords and listening data, and is often reachable from the internet. Reports about security problems are very welcome.

## Reporting a vulnerability

**Please do not open a public issue.** Report it privately instead:

1. Go to the repository's **Security** tab → **Report a vulnerability** (GitHub's private vulnerability reporting).
2. Describe what is affected, how to reproduce it, and what an attacker could do with it. The version (`/api/health` shows it) and how audium is run (behind a proxy or not, sub-path) help.

You get an answer within a week. Once a fix is released, the report is published as a security advisory, with credit to you unless you prefer otherwise.

## Supported versions

audium is young, and only the newest release gets fixes. Bug-fix releases keep the `major.minor` image tag (`ghcr.io/mushroom-media/audium:0.1`), so `docker compose pull` is enough to get them.

| Version | Supported |
|---|---|
| 0.1.x (latest) | yes |
| older | no |

## Scope

In scope: the server (web API, Subsonic API, streaming, authentication, permissions between users, the setup flow), the web interface and the Docker image.

Out of scope: problems that need admin rights on the server or write access to `/data`, missing HTTPS when audium is exposed without a reverse proxy (see [docs/reverse-proxy.md](docs/reverse-proxy.md)), and denial of service by heavy but legitimate use.

## Good to know for operators

- Whoever opens a new instance first becomes its admin. Set `AUDIUM_ADMIN_USER` / `AUDIUM_ADMIN_PASSWORD`, or finish the setup before the server is reachable from the internet.
- Expose audium only over HTTPS (reverse proxy) or a VPN.
- Subsonic apps use their own app passwords, which can be revoked one by one. `data/secret.key` encrypts them: keep it with your backups, and private.
