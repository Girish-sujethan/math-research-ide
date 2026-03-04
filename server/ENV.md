# Environment variables (`.env` in `server/`)

## LLM — Perplexity via OpenRouter (recommended for Agent / Ask)

Use these so Ask and Agent use Perplexity Sonar via OpenRouter (fast, good for grounded chat and research):

```env
PRIMARY_PROVIDER=openai_compatible
PRIMARY_MODEL=perplexity/sonar
CHEAP_PROVIDER=openai_compatible
CHEAP_MODEL=perplexity/sonar
OPENAI_API_KEY=sk-or-v1-...          # your OpenRouter API key (https://openrouter.ai/keys)
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

- **OPENAI_API_KEY**: Your OpenRouter API key (same key gives access to Perplexity, Claude, Gemini, etc.).
- **PRIMARY_MODEL** / **CHEAP_MODEL**: Use `perplexity/sonar` for Perplexity Sonar. Other options: `perplexity/sonar-pro`, `anthropic/claude-sonnet-4`, `google/gemini-flash-1.5`. (Do not use `perplexity/sonar-small-chat` — it is deprecated and returns 400.)

## Optional — Claude as primary

If you prefer Claude for primary and a cheaper model for simple tasks:

```env
PRIMARY_PROVIDER=claude
PRIMARY_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
CHEAP_PROVIDER=openai_compatible
CHEAP_MODEL=perplexity/sonar-small-chat
OPENAI_API_KEY=sk-or-v1-...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

## Optional — Exa (research paper search)

Only needed if the research pipeline should use Exa for external paper search (e.g. non-Agent research). Agent mode can run without this.

```env
EXA_API_KEY=your-exa-api-key
```

## Optional — Perplexity direct (chat fallback when no papers staged)

For the chat endpoint’s web-context fallback when no papers are staged:

```env
PERPLEXITY_API_KEY=...
PERPLEXITY_MODEL=sonar
```

## Other

- **WOLFRAM_APP_ID**: For symbolic checks (Wolfram Alpha).
- **SQLITE_URL**, **CHROMA_PERSIST_DIR**, **LEAN_***: Leave default unless you change paths.
