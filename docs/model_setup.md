# On-Device Model Setup & Inference Guide

This guide covers selecting, downloading, and serving quantized GGUF models on the Snapdragon 888 (12GB RAM) using `llama.cpp` on Termux.

---

## 1. Hardware & Model Sizing Matrix (Snapdragon 888 / 12GB RAM)

The Snapdragon 888 features an 8-core big.LITTLE ARM architecture:
- 1 × Cortex-X1 @ 2.84 GHz (Performance supercore)
- 3 × Cortex-A78 @ 2.42 GHz (Performance cluster)
- 4 × Cortex-A55 @ 1.80 GHz (Efficiency cluster)

| Model Name | Parameters | Quantization | Model Size | Active RAM | Recommended Threads | Tokens / Sec (Prefill / Eval) |
|---|---|---|---|---|---|---|
| **Qwen2.5-1.5B-Instruct** | 1.54B | `Q4_K_M` | ~1.1 GB | ~1.8 GB | `-t 4` | ~38 tps / ~22 tps |
| **Qwen2.5-3B-Instruct** *(Recommended)* | 3.09B | `Q4_K_M` | ~1.93 GB | ~2.9 GB | `-t 4` | ~25 tps / ~14 tps |
| **Qwen2.5-7B-Instruct** | 7.61B | `Q4_K_M` | ~4.68 GB | ~6.2 GB | `-t 4` | ~12 tps / ~6.5 tps |
| **DeepSeek-R1-Distill-Qwen-1.5B** | 1.54B | `Q4_K_M` | ~1.1 GB | ~1.8 GB | `-t 4` | ~36 tps / ~21 tps |
| **DeepSeek-R1-Distill-Qwen-7B** | 7.61B | `Q4_K_M` | ~4.68 GB | ~6.4 GB | `-t 4` | ~11 tps / ~6.2 tps |

> **Why `-t 4` instead of `-t 8`?**
> The Cortex-X1 and Cortex-A78 cores deliver the highest IPC. Spreading computation across all 8 cores activates the A55 efficiency cores which drag down the average thread completion time (Amdahl's law) and drastically increase thermal throttling on the Snapdragon 888. 4 threads (`1x X1 + 3x A78`) achieves optimal throughput-to-watt ratio.

---

## 2. Model Download (Hugging Face / ModelScope)

Download the recommended GGUF directly inside Termux:

```bash
# Create models directory
mkdir -p ~/models
cd ~/models

# Option A: Fast Mirror via ModelScope (China Mainland)
curl -L -O https://www.modelscope.cn/models/qwen/Qwen2.5-3B-Instruct-GGUF/resolve/master/qwen2.5-3b-instruct-q4_k_m.gguf

# Option B: Hugging Face
curl -L -O https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf
```

---

## 3. Starting the OpenAI-Compatible API Server

Run `llama-server` in the background with LAN exposure enabled:

```bash
nohup ~/llama.cpp/build/bin/llama-server \
  -m ~/models/qwen2.5-3b-instruct-q4_k_m.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  -c 4096 \
  -t 4 \
  -b 512 \
  -cb \
  --flash-attn \
  > ~/llama_server.log 2>&1 &
```

### Parameter Breakdown
- `--host 0.0.0.0`: Binds to all network interfaces so other LAN devices (PC, Home Assistant, etc.) can access the endpoint.
- `-c 4096`: Allocates a 4096-token KV context cache.
- `-t 4`: Uses 4 threads for optimal core affinity and thermal efficiency.
- `-cb`: Context shifting enabled to allow continuous conversation without prompt rebuilds.
- `--flash-attn`: Minimizes KV cache memory overhead.

---

## 4. Testing Inference

### Simple Curl Check
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a concise AI assistant."},
      {"role": "user", "content": "Write a 1-sentence motivational quote for a software developer."}
    ],
    "temperature": 0.7,
    "max_tokens": 64
  }'
```

### Python SDK Integration
Any OpenAI-compatible SDK can interact with the mobile server:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://192.168.31.172:8080/v1",  # Replace with phone's LAN IP
    api_key="none"
)

response = client.chat.completions.create(
    model="qwen2.5-3b-instruct-q4_k_m.gguf",
    messages=[
        {"role": "user", "content": "Hello from PC!"}
    ]
)
print(response.choices[0].message.content)
```
