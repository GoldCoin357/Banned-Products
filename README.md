# Banned Products Detection System

Automated AI-powered detection of recalled and banned consumer products listed on C2C (consumer-to-consumer) marketplaces, with full integration into the **CPSC eSAFE Rapid** reporting tool.

---

## Features

| Capability | Details |
|---|---|
| **AI Detection** | Claude (claude-sonnet-4-6) analyses listing text and images to identify recalled products with confidence scoring |
| **Multi-Platform Scraping** | Searches eBay, Craigslist, Facebook Marketplace, and OfferUp |
| **CPSC Data Sync** | Automatically pulls recalled & banned product data from the CPSC SaferProducts REST API |
| **eSAFE Rapid Integration** | Submits confirmed findings directly to the CPSC eSAFE Rapid reporting tool |
| **Analytics Dashboard** | Interactive web dashboard with charts, filters, and cross-platform analytics |
| **Scheduled Scans** | Configurable background scheduler refreshes recall data and rescans platforms |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Frontend Dashboard                     │
│   (HTML/CSS/JS with Chart.js — served by FastAPI)        │
└────────────────────┬────────────────────────────────────┘
                     │ REST API
┌────────────────────▼────────────────────────────────────┐
│                  FastAPI Backend                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Recalls  │ │ Listings │ │Analytics │ │  eSAFE    │  │
│  │  Router  │ │  Router  │ │  Router  │ │  Router   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
│       │            │            │              │         │
│  ┌────▼────────────▼────────────▼──────────────▼─────┐  │
│  │                    Services                        │  │
│  │  ┌─────────────┐  ┌────────────┐  ┌────────────┐  │  │
│  │  │ CPSC Service│  │AI Detector │  │Scan Service│  │  │
│  │  │(fetch+submit│  │  (Claude)  │  │(orchestrate│  │  │
│  │  └──────┬──────┘  └─────┬──────┘  └──────┬─────┘  │  │
│  │         │               │                │         │  │
│  │  ┌──────▼───────────────▼────────────────▼─────┐  │  │
│  │  │               Scrapers                       │  │  │
│  │  │  eBay  │  Craigslist  │  Facebook  │ OfferUp │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │         SQLite / PostgreSQL Database              │   │
│  │   recalled_products | detected_listings | scans  │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
          │                                  │
  ┌───────▼──────┐                 ┌─────────▼──────┐
  │ CPSC SafeProd│                 │  CPSC eSAFE    │
  │  REST API    │                 │  Rapid API     │
  └──────────────┘                 └────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- An [Anthropic API key](https://console.anthropic.com) (for AI detection)
- (Optional) CPSC eSAFE Rapid API key for report submission

### 1. Clone and configure

```bash
git clone <repo-url>
cd Banned-Products
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 2. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3. Run the application

```bash
# From the project root
uvicorn backend.app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) for the dashboard.

### 4. Docker (recommended for production)

```bash
cp .env.example .env   # fill in your keys
docker-compose up -d
```

---

## API Reference

The full interactive API docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Key endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/recalls/` | List recalled products |
| `POST` | `/api/recalls/sync` | Trigger CPSC data sync |
| `POST` | `/api/recalls/import` | Manually import a recall |
| `GET` | `/api/listings/` | List detected marketplace listings |
| `PATCH` | `/api/listings/{id}/confirm` | Confirm or dismiss a listing |
| `POST` | `/api/scans/trigger` | Trigger platform scans |
| `GET` | `/api/scans/` | List scan job history |
| `POST` | `/api/esafe/submit/{id}` | Submit listing to CPSC eSAFE Rapid |
| `POST` | `/api/esafe/submit-pending` | Bulk submit all confirmed listings |
| `GET` | `/api/analytics/summary` | Dashboard summary stats |
| `GET` | `/api/analytics/by-platform` | Breakdown by C2C platform |
| `GET` | `/api/analytics/by-product-type` | Breakdown by product type |
| `GET` | `/api/analytics/trend` | Daily detection trend |

---

## Configuration

All settings are controlled via environment variables (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Claude API key |
| `CPSC_RAPID_API_KEY` | — | CPSC eSAFE Rapid API key |
| `EBAY_APP_ID` | — | eBay developer App ID (improves results) |
| `AI_CONFIDENCE_THRESHOLD` | `0.75` | Minimum confidence to flag a listing |
| `IMAGE_ANALYSIS_ENABLED` | `true` | Enable Claude vision for image matching |
| `SCRAPE_INTERVAL_MINUTES` | `60` | How often to run platform scans |
| `CPSC_REFRESH_INTERVAL_HOURS` | `6` | How often to sync CPSC recall data |
| `MAX_CONCURRENT_SCRAPERS` | `3` | Concurrent AI analysis tasks |

---

## AI Detection Pipeline

For each marketplace listing, the system runs a two-stage analysis:

1. **Text Analysis** — Claude reads the listing title and description, comparing against recalled product attributes (name, brand, model numbers, keywords). Returns a confidence score.

2. **Vision Analysis** (optional) — Claude examines listing images alongside official CPSC recall photos to visually confirm the product match.

3. **Score Combination** — Text (40%) + Image (60%) scores are blended. Listings at or above `AI_CONFIDENCE_THRESHOLD` are saved as detected matches.

---

## CPSC eSAFE Rapid Integration

The system integrates with the [CPSC eSAFE Rapid](https://esafe.cpsc.gov) reporting tool:

1. **Auto-submit** — Listings with ≥90% confidence can be automatically submitted during scans.
2. **Manual submit** — Analysts can review and submit individual listings via the dashboard.
3. **Bulk submit** — All confirmed, unreported listings can be submitted in one click.

Each submission includes the listing URL, platform, price, seller info, recall number, AI reasoning, and captured images.

---

## Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## Supported Platforms

| Platform | Method | API Used |
|---|---|---|
| **eBay** | Browse API + HTML fallback | Official eBay Browse API |
| **Craigslist** | HTML scraping | N/A (no public API) |
| **Facebook Marketplace** | GraphQL internal API + HTML | Internal FB GraphQL |
| **OfferUp** | Internal REST API | OfferUp mobile API |

---

## Data Flow

```
CPSC SaferProducts API
        │
        ▼
  recalled_products DB
        │
   (keywords, images)
        │
        ▼
  C2C Platform Scrapers ──► Raw Listings
        │
        ▼
   Claude AI Analysis
   (text + vision)
        │
        ▼
  detected_listings DB
        │
   (confidence ≥ threshold)
        │
        ├──► Dashboard / Analyst Review
        │
        └──► CPSC eSAFE Rapid API
```

---

## License

This project was developed for the CPSC Banned Products Detection initiative.
