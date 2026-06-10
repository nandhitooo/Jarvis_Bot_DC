import os
import time
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────
API_SECRET   = os.getenv("JARVIS_API_SECRET", "jarvis-secret-key")  # ganti di .env!
GROQ_KEY     = os.getenv("GROQ_API_KEY")
GEMINI_KEY   = os.getenv("GEMINI_API_KEY")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")

# Provider priority: urutan fallback kalau satu gagal
# Bisa diubah via env: PROVIDER_ORDER=groq,gemini,deepseek
PROVIDER_ORDER = [p.strip() for p in os.getenv("PROVIDER_ORDER", "groq,gemini,deepseek").split(",")]

app = FastAPI(
    title="Jarvis AI API",
    description="Unified AI wrapper — Groq, Gemini, DeepSeek in one endpoint",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Ganti dengan domain spesifik di production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ───────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    system_prompt: Optional[str] = None
    provider: Optional[str] = None   # "groq" | "gemini" | "deepseek" | "auto"
    max_tokens: Optional[int] = 1000
    temperature: Optional[float] = 0.7

class ChatResponse(BaseModel):
    answer: str
    provider: str
    model: str
    latency_ms: int
    timestamp: str

# ── Auth ─────────────────────────────────────────────────────
def verify_key(x_api_key: str = Header(...)):
    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return x_api_key

# ── Default system prompt ────────────────────────────────────
def build_system_prompt(custom: Optional[str] = None) -> str:
    now_str = datetime.now().strftime('%A, %d %B %Y %H:%M:%S')
    if custom:
        return custom
    return (
        "You are Jarvis, a highly intelligent and witty personal AI assistant. "
        f"Current date and time: {now_str}. Current year: 2026. "
        "Be concise, direct, and helpful. Support Indonesian and English."
    )

# ════════════════════════════════════════════════════════════
# Provider functions
# ════════════════════════════════════════════════════════════

async def query_groq(message: str, system: str, max_tokens: int, temperature: float) -> dict:
    if not GROQ_KEY:
        raise Exception("GROQ_API_KEY not configured")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=GROQ_KEY, base_url="https://api.groq.com/openai/v1")
    models = [
        ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
        ("llama-3.1-8b-instant",    "Llama 3.1 8B"),
        ("gemma2-9b-it",            "Gemma 2 9B"),
    ]
    last_err = None
    for model_id, model_label in models:
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": message},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return {"answer": resp.choices[0].message.content, "model": model_label}
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("All Groq models failed")


async def query_gemini(message: str, system: str, max_tokens: int, temperature: float) -> dict:
    if not GEMINI_KEY:
        raise Exception("GEMINI_API_KEY not configured")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=GEMINI_KEY)
    models = [
        ("gemini-2.5-flash", "Gemini 2.5 Flash"),
        ("gemini-2.0-flash", "Gemini 2.0 Flash"),
    ]
    last_err = None
    for model_id, model_label in models:
        try:
            def _call(mid=model_id):
                return client.models.generate_content(
                    model=mid,
                    contents=message,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                    )
                ).text
            answer = await asyncio.to_thread(_call)
            return {"answer": answer, "model": model_label}
        except Exception as e:
            last_err = e
            continue
    raise last_err or Exception("All Gemini models failed")


async def query_deepseek(message: str, system: str, max_tokens: int, temperature: float) -> dict:
    if not DEEPSEEK_KEY:
        raise Exception("DEEPSEEK_API_KEY not configured")
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
    resp = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": message},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return {"answer": resp.choices[0].message.content, "model": "DeepSeek Chat"}


PROVIDERS = {
    "groq":     query_groq,
    "gemini":   query_gemini,
    "deepseek": query_deepseek,
}

# ════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════

@app.get("/")
def root():
    available = [p for p in PROVIDER_ORDER if {
        "groq": GROQ_KEY, "gemini": GEMINI_KEY, "deepseek": DEEPSEEK_KEY
    }.get(p)]
    return {
        "service": "Jarvis AI API",
        "version": "1.0.0",
        "status": "online",
        "providers_available": available,
        "endpoints": ["/chat", "/health", "/providers"]
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "providers": {
            "groq":     "configured" if GROQ_KEY     else "missing key",
            "gemini":   "configured" if GEMINI_KEY   else "missing key",
            "deepseek": "configured" if DEEPSEEK_KEY else "missing key",
        }
    }


@app.get("/providers")
def list_providers(_: str = Depends(verify_key)):
    return {
        "order": PROVIDER_ORDER,
        "available": {
            "groq":     bool(GROQ_KEY),
            "gemini":   bool(GEMINI_KEY),
            "deepseek": bool(DEEPSEEK_KEY),
        }
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, _: str = Depends(verify_key)):
    system  = build_system_prompt(req.system_prompt)
    start   = time.perf_counter()
    errors  = {}

    # Tentukan urutan provider yang akan dicoba
    if req.provider and req.provider != "auto":
        if req.provider not in PROVIDERS:
            raise HTTPException(400, f"Unknown provider '{req.provider}'. Use: groq, gemini, deepseek, auto")
        order = [req.provider]
    else:
        order = PROVIDER_ORDER  # fallback otomatis

    for provider_name in order:
        fn = PROVIDERS.get(provider_name)
        if not fn:
            continue
        try:
            result   = await fn(req.message, system, req.max_tokens, req.temperature)
            latency  = round((time.perf_counter() - start) * 1000)
            return ChatResponse(
                answer     = result["answer"],
                provider   = provider_name,
                model      = result["model"],
                latency_ms = latency,
                timestamp  = datetime.now().isoformat(),
            )
        except Exception as e:
            errors[provider_name] = str(e)
            print(f"[API] {provider_name} failed: {e}")
            continue

    # Semua provider gagal
    raise HTTPException(503, detail={"message": "All providers failed", "errors": errors})


# ── Entry point ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
