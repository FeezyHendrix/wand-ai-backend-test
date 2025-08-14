# Docker Setup with Ollama

This setup includes Ollama running in a Docker container for local LLM inference.

## Quick Start

### CPU-only (Default)
```bash
docker-compose up -d
```

### With GPU Support (NVIDIA)
```bash
docker-compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

## Services

- **db**: PostgreSQL database
- **redis**: Redis cache
- **ollama**: Ollama LLM server
- **ollama-init**: One-time model download service
- **api**: FastAPI application

## Model Management

The default model `llama3.2:1b` is automatically pulled during startup. To use a different model:

1. Update `OLLAMA_MODEL` in docker-compose.yml
2. Restart the services: `docker-compose restart ollama-init api`

### Available Models
- `llama3.2:1b` - Fast, small model (1.3GB) **[DEFAULT]**
- `tinyllama` - Ultra-fast, tiny model (637MB)
- `llama3.2:3b` - Balanced model (2.0GB)
- `llama3.1:8b` - Larger, more capable (4.7GB)

## Environment Variables

- `OLLAMA_BASE_URL`: Ollama server URL (default: http://ollama:11434)
- `OLLAMA_MODEL`: Model to use (default: llama3.2:1b)

## Troubleshooting

### Check Ollama Status
```bash
docker logs kb-ollama
docker exec kb-ollama ollama list
```

### Pull Model Manually
```bash
docker exec kb-ollama ollama pull llama3.2:1b
```

### Test Ollama API
```bash
curl http://localhost:11434/api/version
```

## Resource Requirements

- **CPU-only**: 2GB RAM minimum, 4GB recommended
- **GPU**: NVIDIA GPU with 4GB+ VRAM for larger models
- **Storage**: 2-10GB for models (persisted in `ollama_data` volume)

## Performance

- **llama3.2:1b**: ~100-500 tokens/sec (CPU), ~1000+ tokens/sec (GPU)
- **tinyllama**: ~500-2000 tokens/sec (CPU), ~3000+ tokens/sec (GPU)
- **llama3.2:3b**: ~50-200 tokens/sec (CPU), ~500+ tokens/sec (GPU)

## Security

- Ollama runs in an isolated container
- No external API keys required
- All data stays on your infrastructure