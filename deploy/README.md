# Deploying on the Azure VM

The app runs as two containers: the app itself (FastAPI, pages, API, tiles,
live-alert refresher, and the SQLite database inside the image) and Caddy in
front of it for HTTPS. GitHub Actions builds the database and the image and
publishes the image to GitHub Container Registry (`release.yml`); the server
only pulls and runs it.

## What the VM needs

- Linux with Docker Engine and the Compose plugin.
- Ports 80 and 443 open to the internet (Caddy uses 80 for the certificate
  challenge and redirects it to 443).
- A DNS name pointing at the VM: the university's, or an Azure
  `<name>.<region>.cloudapp.azure.com` name set on the VM's public IP.
- If the GitHub package is private: `docker login ghcr.io` with a token that can
  read packages.

## First install

```bash
mkdir -p ~/rgv-flood && cd ~/rgv-flood
# copy deploy/compose.yaml, deploy/Caddyfile and deploy/.env.example here
cp .env.example .env        # then set RGV_DOMAIN
docker compose pull
docker compose up -d
```

Open `https://<RGV_DOMAIN>`; `https://<RGV_DOMAIN>/health` should answer
`{"status": "ok", ...}` and `/docs` shows the API.

## Updating

A push to `main`, a manual run of the **release** workflow, or the monthly
schedule publishes a new image tagged `latest` and with the date. Then:

```bash
docker compose pull && docker compose up -d
```

## Rolling back

Set `RGV_IMAGE=ghcr.io/luiscarlosgarcia1/senior-proj:<date>` in `.env` to an
earlier dated tag and run `docker compose up -d`.

## Logs and health

```bash
docker compose logs -f app      # one JSON line per request
docker compose ps               # "healthy" once /health answers
```

## Scaling

The app is stateless apart from its read-only database, so: raise `--workers`
(the image runs 4) on a bigger VM first; beyond one VM, run the same image on
several and put a load balancer in front. Each copy refreshes its own live
alerts (one refresher per host, by a file lock).
