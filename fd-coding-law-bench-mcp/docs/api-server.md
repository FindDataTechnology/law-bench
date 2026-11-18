# Law Bench HTTP API Server

FastAPI-based REST API for async contract generation via tag-driven assembly.

> **Documentation:** This is the **setup/configuration guide**. For the full
> endpoint + schema + error reference, see [API Reference](api-reference.md).
> For valid tag values and contract types, see
> [Tag Vocabulary Reference](tag-vocabulary.md).

## Quick Start

### Starting the server

```bash
# From fd-coding-law-bench-mcp directory
./scripts/start-api-server.sh

# Or directly with uvicorn
uvicorn fd_coding_law_bench_mcp.api.main:app --host 0.0.0.0 --port 8000

# Development mode (auto-reload)
uvicorn fd_coding_law_bench_mcp.api.main:app --reload
```

### Configuration

Environment variables (see `api/config.py`):

```bash
# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false

# CORS (comma-separated list of allowed origins)
CORS_ORIGINS=["http://localhost:3000", "https://app.example.com"]

# Authentication (optional)
API_KEY_ENABLED=false
API_KEYS="key1,key2,key3"

# Rate limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
RATE_LIMIT_BACKEND=memory  # or "redis"
REDIS_URL="redis://localhost:6379"
```

## API Endpoints

### Contract Content Generation

**POST /contracts/content**

Generate single contract content.

```bash
curl -X POST http://localhost:8000/contracts/content \
  -H "Content-Type: application/json" \
  -d '{
    "contract_type": "sale",
    "tags": {"scenario": "农产品买卖", "stance": "balanced"},
    "format": "markdown"
  }'
```

Response:
```json
{
  "trace_id": "uuid",
  "contract_type": "sale",
  "body_text": "## 当事人\n\n甲方...",
  "slots": ["party_a", "party_b", ...],
  "instructions": [...],
  "law_refs": [...],
  "tags_used": {"scenario": "农产品买卖", "stance": "balanced"}
}
```

### Batch Contract Generation

**POST /contracts/batch**

Generate multiple contracts in parallel.

```bash
curl -X POST http://localhost:8000/contracts/batch \
  -H "Content-Type: application/json" \
  -d '{
    "contract_type": "sale",
    "tag_combinations": [
      {"scenario": "农产品买卖", "stance": "pro_a"},
      {"scenario": "消费品零售", "stance": "balanced"}
    ],
    "max_concurrent": 5
  }'
```

Response:
```json
{
  "trace_id": "uuid",
  "success_count": 2,
  "failure_count": 0,
  "results": [
    {
      "success": true,
      "tags": {"scenario": "农产品买卖", "stance": "pro_a"},
      "body_text": "...",
      "slots": [...]
    },
    ...
  ]
}
```

### Contract Type Catalog

**GET /contracts/types**

List all available contract types.

```bash
curl http://localhost:8000/contracts/types
```

**GET /contracts/types/{type}**

Get detailed metadata for a specific contract type.

```bash
curl http://localhost:8000/contracts/types/sale
```

### Tag Management

**GET /tags/combinations/{type}**

Enumerate valid tag combinations.

```bash
curl "http://localhost:8000/tags/combinations/sale?filter_by_clause_coverage=true"
```

**POST /tags/validate**

Validate tags against controlled vocabulary.

```bash
curl -X POST http://localhost:8000/tags/validate \
  -H "Content-Type: application/json" \
  -d '{
    "tags": {"stance": "pro_a", "scenario": "农产品买卖"},
    "contract_type": "sale"
  }'
```

### Health Check

**GET /health**

Health check endpoint for monitoring.

```bash
curl http://localhost:8000/health
```

## Documentation

- OpenAPI Schema: `/openapi.json`
- Swagger UI: `/docs`
- ReDoc: `/redoc`

## Authentication

Enable optional API key authentication by setting:

```bash
export API_KEY_ENABLED=true
export API_KEYS="secret-key-1,secret-key-2"
```

Then include `X-API-Key` header in requests:

```bash
curl http://localhost:8000/contracts/content \
  -H "X-API-Key: secret-key-1" \
  -d '{"contract_type": "sale"}'
```

## Rate Limiting

Default: 100 requests per minute per client IP.

Customize via environment variables:

```bash
export RATE_LIMIT_REQUESTS=50
export RATE_LIMIT_WINDOW=60
```

Rate limit headers included in responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining
- `X-RateLimit-Reset`: Reset timestamp

## Error Responses

All errors return standardized format:

```json
{
  "error": "ValidationError",
  "message": "Request validation failed",
  "details": {...},
  "trace_id": "uuid"
}
```

Common status codes:
- `200 OK` - Success
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Missing API key
- `403 Forbidden` - Invalid API key
- `404 Not Found` - Contract type not found
- `422 Unprocessable Entity` - Validation error
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Unexpected error

## Testing

Run tests (if available):

```bash
pytest tests/test_api/ -v
```

## Deployment

### Docker (optional)

Create `Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -r pyproject.toml
EXPOSE 8000
CMD ["uvicorn", "fd_coding_law_bench_mcp.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t law-bench-api .
docker run -p 8000:8000 -e DATABASE_URL=... law-bench-api
```

### systemd Service

Create `/etc/systemd/system/law-bench-api.service`:
```ini
[Unit]
Description=Law Bench HTTP API Server
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/fd-coding-law-bench-mcp
Environment="DATABASE_URL=postgresql://..."
Environment="CORS_ORIGINS=http://localhost:3000"
ExecStart=/usr/bin/python -m uvicorn fd_coding_law_bench_mcp.api.main:app --host 0.0.0.0 --port 8000 --workers 2

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable law-bench-api
sudo systemctl start law-bench-api
sudo systemctl status law-bench-api
```

## Troubleshooting

### Connection refused to database

Ensure `DATABASE_URL` env var is set correctly.

### CORS errors

Verify `CORS_ORIGINS` includes your frontend origin.

### Rate limit errors

Check `X-RateLimit-Remaining` header and adjust rate limits if needed.

### Module import errors

Set `PYTHONPATH` correctly or use the provided startup script.
