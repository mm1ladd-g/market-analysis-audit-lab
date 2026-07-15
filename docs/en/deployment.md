# Deployment

[English](deployment.md) · [فارسی](../fa/deployment.md) · [Documentation](index.md)

Localhost is the supported default. Run the synthetic demo and verification locally before any network exposure.

```bash
docker compose up --build
```

Compose separates duties: the profiled `audit-lab` worker receives the full workspace and configured runtime secrets only for explicit tool commands; the default `audit-web` process receives only `workspace/reports` read-only, runs with a read-only root filesystem, binds only to localhost, and receives no OpenAI key. Do not collapse these services for convenience. The viewer uses Docker's ordinary network so its published localhost port works consistently on Docker Desktop and Linux; apply a host firewall or deployment-specific egress policy when outbound isolation is required.

Keep the host binding on `127.0.0.1`. For a shared or public service, place a reviewed reverse proxy or tunnel in front of the app and add TLS, authentication, authorization, rate/size limits, secure headers, log redaction, monitoring, backups, and a correction contact. Use a non-common host port without documenting a private domain or account in the source repository.

Do not mount the repository, home directory, Docker socket, `.env`, or unrelated workspaces into the web container. Keep raw evidence and AI caches outside the static root. Disable debug mode and directory indexes. Restrict CORS, trusted hosts, egress, and report endpoints. Health checks must expose status, not configuration or evidence.

Cloud tunnels do not add application authorization by themselves. Review caching, access logs, bot indexing, link previews, and geographic/privacy effects. A public dashboard is a publication event and must pass the rights/privacy/fairness checklist.
