# Adaptive Media Streaming

Django-based adaptive media streaming application with Celery for background tasks.

## Quick Start

### 1. Setup Environment

Create `.env` file:

```bash
SECRET_KEY=your-secret-key
DEBUG=1
POSTGRES_PASSWORD=your-password
```

### 2. Run Application

```bash
docker compose up --build
```

Access at: http://localhost:8000

### 3. Stop Application

```bash
# Stop services
docker compose down

# Clean reinstall (removes all data)
docker compose down -v && docker compose up --build
```

## Troubleshooting

**Permission error:** `sudo chown -R $(whoami) ~/.docker`

## Versioning
For specific assignments see the corresponding branch.
