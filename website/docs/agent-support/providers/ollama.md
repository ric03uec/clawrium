# Ollama

**Status:** ✅ Supported

Ollama lets you run open-source LLMs locally on your own hardware.

## Supported Models

<!-- MODEL-TABLE:START -->
*Ollama models are discovered dynamically from local installation.*
<!-- MODEL-TABLE:END -->

See more at [ollama.com/library](https://ollama.com/library)

## Setup

### 1. Install Ollama

On your target host (or any machine on your network):

```bash
# macOS/Linux
curl -fsSL https://ollama.com/install.sh | sh

# Or download from https://ollama.com/download
```

### 2. Pull Models

```bash
# Pull a model
ollama pull llama3.2

# List available models
ollama list
```

### 3. Configure Server Access

By default, Ollama only accepts local connections. To allow remote access:

```bash
# Set environment variable
export OLLAMA_HOST=0.0.0.0:11434

# Or edit systemd service
sudo systemctl edit ollama.service
```

Add:
```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Then restart:
```bash
sudo systemctl restart ollama
```

### 4. Add to Clawrium

```bash
clm provider add local-ollama --type ollama --url http://192.168.1.50:11434
```

Clawrium will:
1. Connect to the Ollama server
2. Fetch available models
3. Let you select a default

## Configuration

```bash
# View provider details
clm provider list

# Refresh model list (after pulling new models)
clm provider refresh local-ollama

# Change default model
clm provider edit local-ollama --model llama3.2

# Update server URL
clm provider edit local-ollama --url http://new-server:11434

# Remove provider
clm provider remove local-ollama
```

## Hardware Requirements

| Model | RAM Required | GPU Recommended |
|-------|--------------|-----------------|
| llama3.2 (3B) | 8GB | Optional |
| llama3.1 (8B) | 16GB | 8GB VRAM |
| llama3.3 (70B) | 64GB | 40GB+ VRAM |
| mixtral (47B) | 32GB | 24GB VRAM |

## Benefits

- **Privacy:** Data never leaves your network
- **No API costs:** Pay only for hardware/electricity
- **No rate limits:** Unlimited requests
- **Offline capable:** Works without internet
- **Model variety:** 100+ open-source models

## Troubleshooting

**"Connection refused"**
- Verify Ollama is running: `ollama serve`
- Check `OLLAMA_HOST` is set for remote access
- Ensure firewall allows port 11434

**"Model not found"**
- Pull the model first: `ollama pull <model>`
- Check available models: `ollama list`

**"Out of memory"**
- Use a smaller model (e.g., llama3.2 instead of llama3.1)
- Add more RAM or VRAM
- Use CPU-only mode (slower): `ollama run <model> --cpu`

**"Slow responses"**
- GPU acceleration significantly improves speed
- Consider quantization (Q4, Q5, Q8)
- Check GPU utilization with `nvidia-smi`

---

[Back to Providers](index.md)
