import os
import discord
from discord.ext import commands
from datetime import datetime
from openai import AsyncOpenAI


# Model fallback: dari yang paling capable ke paling ringan
GROQ_MODELS = [
    ("llama-3.3-70b-versatile",  "Llama 3.3 70B"),
    ("llama-3.1-8b-instant",     "Llama 3.1 8B"),
    ("gemma2-9b-it",             "Gemma 2 9B"),
]


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client    = None
        self.available = False

        api_key = os.getenv("GROQ_API_KEY")
        if api_key:
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
            )
            self.available = True
            print("[AI] ✅ Groq API configured.")
        else:
            print("[AI] ⚠️  GROQ_API_KEY not found in .env")

    # ────────────────────────────────────────────────────────────
    # Helper: system prompt + timestamp
    # ────────────────────────────────────────────────────────────
    def _build_sys(self) -> tuple[str, str]:
        now_str = datetime.now().strftime('%A, %d %B %Y %H:%M:%S')
        sys_instruction = (
            "You are Jarvis, a polite, highly advanced butler AI. "
            f"The current date and time is {now_str}. "
            "Use this date/time context to answer any question about 'now', 'today', or the current year accurately. "
            "If asked about the current year, the answer is 2026. "
            "Jika ditanya tahun berapa sekarang, jawabannya adalah 2026. "
            "Support the language the user is speaking (Indonesian/English) politely."
        )
        return now_str, sys_instruction

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis ask
    # ────────────────────────────────────────────────────────────
    @commands.command(name='ask', aliases=['chat', 'ai'], help='Tanyakan sesuatu ke Jarvis AI (via Groq)')
    async def ask(self, ctx: commands.Context, *, question: str):
        if not self.available:
            return await ctx.send(embed=discord.Embed(
                description="❌ **GROQ_API_KEY** tidak ditemukan di file `.env`.",
                color=0xFF3333
            ))

        async with ctx.typing():
            try:
                now_str, sys_instruction = self._build_sys()
                answer, used_model = await self._query(sys_instruction, now_str, question)
                if not answer or not answer.strip():
                    answer = "Maaf, saya tidak bisa memberikan jawaban untuk pertanyaan itu."
                await self._send_response(ctx, answer, used_model)
            except Exception as e:
                print(f"[AI] Error: {e}")
                await ctx.send(embed=discord.Embed(
                    description=self._friendly_error(str(e)),
                    color=0xFF3333
                ))

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis model
    # ────────────────────────────────────────────────────────────
    @commands.command(name='model', aliases=['models'], help='Lihat daftar model AI yang tersedia')
    async def list_models(self, ctx: commands.Context):
        lines = "\n".join(
            f"`{i+1}.` {label} — `{mid}`"
            for i, (mid, label) in enumerate(GROQ_MODELS)
        )
        embed = discord.Embed(
            title="🧠 Model AI (Groq)",
            description=(
                f"Bot akan mencoba model berikut secara berurutan:\n\n{lines}\n\n"
                "⚡ Groq menggunakan **LPU** — inferensi jauh lebih cepat dari GPU biasa."
            ),
            color=0x00E5FF
        )
        embed.set_footer(text=f"Diminta oleh {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ────────────────────────────────────────────────────────────
    # Internal: query Groq dengan fallback antar model
    # ────────────────────────────────────────────────────────────
    async def _query(self, sys_instruction: str, now_str: str, question: str):
        enriched   = f"[Context: {now_str}]\n{question}"
        last_error = None

        for model_id, model_label in GROQ_MODELS:
            try:
                print(f"[AI] Trying model: {model_id}")
                response = await self.client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": sys_instruction},
                        {"role": "user",   "content": enriched},
                    ],
                    max_tokens=1000,
                    temperature=0.7,
                )
                answer = response.choices[0].message.content
                print(f"[AI] Success: {model_id}")
                return answer, model_label

            except Exception as e:
                err_str = str(e)
                print(f"[AI] {model_id} failed: {err_str}")
                # Jangan fallback kalau masalah auth — semua model pasti gagal
                if "401" in err_str or "invalid_api_key" in err_str.lower():
                    raise Exception("🔑 **API Key Groq tidak valid.** Periksa kembali file `.env`.")
                last_error = e
                continue

        raise last_error or Exception("Semua model Groq gagal merespons.")

    # ────────────────────────────────────────────────────────────
    # Internal: pesan error yang ramah
    # ────────────────────────────────────────────────────────────
    def _friendly_error(self, err: str) -> str:
        if "401" in err or "invalid_api_key" in err.lower():
            return "🔑 **API Key tidak valid.** Periksa kembali file `.env`."
        if "429" in err or "rate_limit" in err.lower():
            return "⏳ **Rate limit Groq tercapai.** Coba lagi dalam beberapa detik."
        if "503" in err or "unavailable" in err.lower():
            return "🔧 **Groq sedang gangguan.** Coba lagi nanti."
        return f"⚠️ Gagal mendapatkan respons: `{err}`"

    # ────────────────────────────────────────────────────────────
    # Internal: kirim embed (auto-split jika > 1900 char)
    # ────────────────────────────────────────────────────────────
    async def _send_response(self, ctx: commands.Context, answer: str, used_model: str):
        chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
        total  = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            title = "🤖 Jarvis AI Response"
            if total > 1:
                title += f" (Part {idx}/{total})"
            embed = discord.Embed(title=title, description=chunk, color=0x00E5FF)
            embed.set_footer(
                text=f"Model: {used_model} • Ditanyakan oleh {ctx.author.name}",
                icon_url=ctx.author.display_avatar.url,
            )
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
    print("[AI] Cog loaded.")
