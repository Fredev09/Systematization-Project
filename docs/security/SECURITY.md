# Security — Document Intelligence AI Platform

## API Keys & Secrets

All API keys are loaded exclusively from environment variables via `python-decouple`.
No API keys are hardcoded in any Python, JavaScript, or template file.

### Required env vars for AI

| Variable | Provider | Required? | Get it at |
|---|---|---|---|
| `GEMINI_API_KEY` | Google Gemini | No (FREE-FIRST) | https://aistudio.google.com/apikey |
| `DEEPSEEK_API_KEY` | DeepSeek | No | https://platform.deepseek.com/api_keys |
| `OPENROUTER_API_KEY` | OpenRouter | No | https://openrouter.ai/keys |
| `QWEN_API_KEY` | Qwen (Alibaba) | No | https://dashscope.console.aliyun.com/ |

## What works without AI (FREE-FIRST mode)

- Login and user management
- Dynamic Forms (create, edit, list, delete)
- Data import with ColumnMatcher (heuristic column matching)
- Data Agent (natural language → Django ORM queries)
- Excel/CSV heuristic extraction (extracts rows/columns without AI)
- All CRUD operations for formularios, campos, registros
- User reports with real system data

## What requires AI

- OCR for images and scanned PDFs
- Invoice extraction (proveedor, NIT, items, IVA, totales)
- Chat IA (conversational Q&A about documents)
- Automatic form creation from documents
- AI-powered report generation (semantic analysis)

## Provider security

### Gemini
- API key sent via `X-Goog-Api-Key` HTTP header (NOT in URL)
- Never logged or printed
- Validated on instantiation — raises `ProviderNotAvailable` with safe message

### DeepSeek, OpenRouter, Qwen
- API key sent via `Authorization: Bearer` header
- Never logged or printed
- Validated on instantiation

## Error handling

- `ProviderNotAvailable`: Only shows provider name, never the API key
- `ProviderAuthError`: Safe message "Check your API key"
- HTTP error bodies are sanitized (truncated to 200 chars, sensitive patterns replaced)
- `ProviderConfig.__repr__` shows `api_key='***'` instead of actual value

## Logging

No AI module logger call includes API keys, tokens, or authorization headers.
The only provider-related log is:
```python
logger.info("AI provider initialized: %s (model=%s)", provider_type.value, model)
```

## Git

`.gitignore` includes:
- `.env` and `.env.*`
- `*.pem`, `*.key`, `*.crt`, `*.p12`, `*.pfx`
- `credentials.json`, `service-account.json` (if added)

## Frontend

No API keys are ever sent to the browser. They remain server-side only.
- No API keys in templates
- No API keys in JavaScript
- No API keys in JSON responses
- No API keys in LocalStorage or SessionStorage

## Development-only concerns

- `manage.py crear_datos_prueba` has a hardcoded password `VENDEDOR_PASSWORD = 'Prueba123!'`
  that is printed to stdout. This is a development/testing command only.
