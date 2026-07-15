# Installation

[English](installation.md) · [فارسی](../fa/installation.md) · [Documentation](index.md)

## Supported path

Docker Compose is the reproducible path. Use a current, supported Docker release on macOS,
Linux, or Windows with WSL2. Rootless Docker is preferred on Linux. A fresh build needs network
access for the pinned base image and dependencies; runtime network access is needed only for the
collection, model, and market providers the operator explicitly configures.

```bash
git clone https://github.com/mm1ladd-g/market-analysis-audit-lab.git
cd market-analysis-audit-lab
umask 077 && cp .env.example .env
docker compose build
docker compose run --rm audit-lab python -m audit_lab.cli doctor
```

The service should bind to localhost by default. Do not add a public interface merely to simplify testing.

## Capacity planning

Disk usage is driven by subtitle/metadata volume, optional thumbnails, market resolution, API caches, and final archives. Start with at least several gigabytes free and monitor `workspace/`. Long windows and one-minute crypto data can grow quickly. CPU requirements are modest unless local speech-to-text is added; API-based extraction is network- and cost-bound.

## Local Python

Local development is possible with the Python version declared by the project and the exact dependency lock. It is not the preferred reproducibility path.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.lock
python -m unittest discover -s tests -v
```

Never install with unreviewed dependency upgrades during a release reproduction.

## Upgrade

Read `CHANGELOG.md` and the release notes, back up the workspace, pull the exact tag, rebuild without injecting secrets into the image, run tests and the synthetic demo, then verify an existing bundle before rerunning paid stages. Pre-1.0 schemas may require migration.

## Uninstall

Stopping or deleting a container does not remove bind-mounted evidence. Remove the workspace, backups, exported reports, and external storage only after following your retention policy. Rotate credentials separately if they were exposed.
