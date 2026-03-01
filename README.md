# 🧪 QA Dashboard

A modern test results aggregation and visualization platform with full DevOps pipeline.

![Architecture](https://img.shields.io/badge/Architecture-Microservices-blue)
![Docker](https://img.shields.io/badge/Docker-Ready-blue)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Actions-green)

## Features

- 📊 **Test Results Visualization** - Beautiful dashboard with charts and trends
- 🎭 **Playwright Integration** - Parse and display Playwright test results
- 🔌 **API Test Support** - Newman/Postman and pytest integration
- 📈 **Trend Analysis** - Track pass rates over time
- 🔔 **Slack Notifications** - Get notified on test failures
- 🐳 **Fully Containerized** - Docker Compose for easy deployment
- 🚀 **CI/CD Ready** - GitHub Actions pipeline included

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Git

### Run Locally

```bash
# Clone the repository
git clone https://github.com/yourusername/qa-dashboard.git
cd qa-dashboard

# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Open dashboard
open http://localhost:3000
```

### Send Test Results

```bash
# Example: Send Playwright results
npx playwright test --reporter=json | \
  python scripts/playwright_reporter.py - \
    --project my-app \
    --branch main \
    --api-url http://localhost:3000

# Example: Send Newman results
newman run collection.json -r json --reporter-json-export results.json
python scripts/api_reporter.py results.json \
  --project my-api \
  --branch main
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 QA Dashboard Architecture                │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐   │
│  │ Frontend │───▶│  Nginx   │───▶│  FastAPI Backend │   │
│  │  (HTML)  │    │ (Proxy)  │    │    (Python)      │   │
│  └──────────┘    └──────────┘    └────────┬─────────┘   │
│                                           │              │
│                        ┌──────────────────┼───────────┐ │
│                        │                  │           │ │
│                        ▼                  ▼           │ │
│                 ┌──────────┐       ┌──────────┐       │ │
│                 │ PostgreSQL│       │  Redis   │       │ │
│                 │    DB    │       │  Cache   │       │ │
│                 └──────────┘       └──────────┘       │ │
│                                                        │ │
└────────────────────────────────────────────────────────┘
```

## Project Structure

```
qa-dashboard/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile          # Backend container
├── frontend/
│   ├── index.html          # Dashboard UI
│   ├── nginx.conf          # Nginx configuration
│   └── Dockerfile          # Frontend container
├── scripts/
│   ├── playwright_reporter.py  # Playwright integration
│   └── api_reporter.py         # API test integration
├── .github/
│   └── workflows/
│       └── ci-cd.yml       # GitHub Actions pipeline
├── docker-compose.yml      # Docker Compose config
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/runs` | Submit test run results |
| GET | `/api/v1/runs` | List recent test runs |
| GET | `/api/v1/runs/{id}` | Get run details |
| GET | `/api/v1/runs/{id}/failures` | Get failed tests |
| GET | `/api/v1/trends/{project}` | Get pass rate trends |
| GET | `/api/v1/stats/{project}` | Get project statistics |
| GET | `/api/v1/projects` | List all projects |

## CI/CD Pipeline

The GitHub Actions workflow includes:

1. **Test** - Run unit tests and linting
2. **Build** - Build Docker images with multi-stage builds
3. **Security** - Scan images with Trivy
4. **Deploy** - Deploy to production (configurable)

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `SLACK_WEBHOOK_URL` | Slack webhook for notifications | No |

## Development

### Run Backend Locally

```bash
cd backend
pip install -r requirements.txt

# Start PostgreSQL and Redis
docker compose up -d db redis

# Run backend
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/qa_dashboard \
REDIS_URL=redis://localhost:6379 \
uvicorn main:app --reload
```

### Run Frontend Locally

```bash
cd frontend
python -m http.server 8080
# Open http://localhost:8080
```

## Docker Commands Cheatsheet

```bash
# Build images
docker compose build

# Start services
docker compose up -d

# View logs
docker compose logs -f backend

# Stop services
docker compose down

# Remove volumes (reset data)
docker compose down -v

# Rebuild and restart single service
docker compose up -d --build backend
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

MIT License - feel free to use this project for learning and production.

---

Built with ❤️ for learning Docker + DevOps
