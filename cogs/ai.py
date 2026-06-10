import os
import io
import aiohttp
import discord
from discord.ext import commands
from datetime import datetime
from openai import AsyncOpenAI


MAX_PDF_CHARS = 12000  # ~3000 token, aman untuk semua model


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client    = None
        self.available = False

        # ── Cek apakah pakai Jarvis Custom API atau langsung Groq ──
        self.jarvis_api_url = os.getenv("JARVIS_API_URL")   # e.g. http://localhost:8000
        self.jarvis_api_key = os.getenv("JARVIS_API_SECRET", "jarvis-secret-key")

        if self.jarvis_api_url:
            self.available = True
            print(f"[AI] ✅ Jarvis Custom API: {self.jarvis_api_url}")
        else:
            # Fallback: langsung ke Groq
            api_key = os.getenv("GROQ_API_KEY")
            if api_key:
                self.client = AsyncOpenAI(
                    api_key=api_key,
                    base_url="https://api.groq.com/openai/v1",
                )
                self.available = True
                print("[AI] ✅ Groq API configured (direct).")
            else:
                print("[AI] ⚠️  No AI backend configured (set JARVIS_API_URL or GROQ_API_KEY)")

        # Load models from .env
        self.models = []
        for i in range(1, 4):
            mid = os.getenv(f"GROQ_MODEL_{i}")
            label = os.getenv(f"GROQ_MODEL_LABEL_{i}")
            if mid and label:
                self.models.append((mid, label))
        if not self.models:
            self.models = [
                ("llama-3.3-70b-versatile", "Llama 3.3 70B"),
                ("llama-3.1-8b-instant",    "Llama 3.1 8B"),
                ("gemma2-9b-it",            "Gemma 2 9B"),
            ]

        self.custom_image_url = os.getenv("CUSTOM_IMAGE_API_URL")
        self.custom_image_key = os.getenv("CUSTOM_IMAGE_API_KEY")

    # ────────────────────────────────────────────────────────────
    # Helper: system prompt + timestamp
    # ────────────────────────────────────────────────────────────
    def _build_sys(self) -> tuple[str, str]:
        now_str = datetime.now().strftime('%A, %d %B %Y %H:%M:%S')
        sys_instruction = (
            "You are Jarvis, a polite, highly advanced butler AI. "
            f"The current date and time is {now_str}. "
            "Use this date/time context to answer any question about 'now', 'today', or the current year accurately. "
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
    # Command: !jarvis summarize
    # ────────────────────────────────────────────────────────────
    @commands.command(name='summarize', aliases=['sum', 'ringkas'], help='Ringkas isi file PDF (attach atau URL)')
    async def summarize(self, ctx: commands.Context, *, pdf_url: str = None):
        if not self.available:
            return await ctx.send(embed=discord.Embed(
                description="❌ **GROQ_API_KEY** tidak ditemukan di file `.env`.",
                color=0xFF3333
            ))

        attachment = None
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith('.pdf'):
                return await ctx.send(embed=discord.Embed(
                    description="❌ File yang dilampirkan bukan PDF.",
                    color=0xFF3333
                ))
            url = attachment.url
        elif pdf_url:
            url = pdf_url.strip()
            if not url.lower().endswith('.pdf') and 'pdf' not in url.lower():
                return await ctx.send(embed=discord.Embed(
                    description="❌ URL tidak terlihat seperti file PDF. Pastikan URL mengarah ke file `.pdf`.",
                    color=0xFF3333
                ))
        else:
            return await ctx.send(embed=discord.Embed(
                title="📄 Cara pakai summarize",
                description=(
                    "**Opsi 1 — Attach file:**\n"
                    "Lampirkan file PDF ke pesan, lalu ketik:\n"
                    "`!jarvis summarize`\n\n"
                    "**Opsi 2 — URL:**\n"
                    "`!jarvis summarize https://contoh.com/dokumen.pdf`"
                ),
                color=0x00E5FF
            ))

        status_msg = await ctx.send(embed=discord.Embed(
            description="📥 Mengunduh dan membaca PDF...",
            color=0xf1c40f
        ))

        async with ctx.typing():
            try:
                pdf_bytes = await self._download_pdf(url)
                await status_msg.edit(embed=discord.Embed(
                    description="🔍 Mengekstrak teks dari PDF...",
                    color=0xf1c40f
                ))
                text = self._extract_pdf_text(pdf_bytes)

                if not text or len(text.strip()) < 50:
                    return await status_msg.edit(embed=discord.Embed(
                        description="❌ Gagal mengekstrak teks. PDF mungkin berupa scan/gambar (bukan teks).",
                        color=0xFF3333
                    ))

                truncated = False
                if len(text) > MAX_PDF_CHARS:
                    text = text[:MAX_PDF_CHARS]
                    truncated = True

                await status_msg.edit(embed=discord.Embed(
                    description="🤖 Merangkum dengan AI...",
                    color=0xf1c40f
                ))

                _, sys_instruction = self._build_sys()
                prompt = (
                    "Tolong buat ringkasan lengkap dari dokumen PDF berikut ini.\n"
                    "Sertakan: poin-poin utama, kesimpulan, dan informasi penting lainnya.\n"
                    "Gunakan bahasa yang sama dengan dokumen tersebut.\n\n"
                    f"--- ISI DOKUMEN ---\n{text}\n--- AKHIR DOKUMEN ---"
                )

                answer, used_model = await self._query(sys_instruction, "", prompt, max_tokens=1500)
                await status_msg.delete()

                filename = attachment.filename if attachment else url.split('/')[-1]
                header = f"📄 **Ringkasan: {filename}**"
                if truncated:
                    header += "\n⚠️ *Dokumen terpotong (terlalu panjang), ringkasan berdasarkan bagian awal.*"

                await self._send_response(ctx, f"{header}\n\n{answer}", used_model)

            except ValueError as e:
                await status_msg.edit(embed=discord.Embed(
                    description=f"❌ {e}",
                    color=0xFF3333
                ))
            except Exception as e:
                print(f"[AI] Summarize error: {e}")
                await status_msg.edit(embed=discord.Embed(
                    description=self._friendly_error(str(e)),
                    color=0xFF3333
                ))

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis search
    # ────────────────────────────────────────────────────────────
    @commands.command(name='search', aliases=['web', 'cari'], help='Cari informasi di web (via Groq)')
    async def search(self, ctx: commands.Context, *, query: str):
        if not self.available:
            return await ctx.send(embed=discord.Embed(
                description="❌ **GROQ_API_KEY** tidak ditemukan di file `.env`.",
                color=0xFF3333
            ))

        async with ctx.typing():
            try:
                now_str, sys_instruction = self._build_sys()
                search_prompt = (
                    "Kamu adalah asisten pencarian web yang sangat cerdas. "
                    "Berikan jawaban singkat dan relevan untuk pertanyaan berikut, berdasarkan pengetahuan umum dan data yang tersedia hingga tahun 2026. "
                    "Jika kamu tidak tahu jawabannya, katakan dengan jujur bahwa kamu tidak tahu."
                )
                enriched_query = f"{query}\n\n[Context: {now_str}]"
                answer, used_model = await self._query(sys_instruction + "\n" + search_prompt, now_str, enriched_query)
                if not answer or not answer.strip():
                    answer = "Maaf, saya tidak bisa menemukan informasi yang relevan untuk pertanyaan itu."
                await self._send_response(ctx, answer, used_model)
            except Exception as e:
                print(f"[AI] Search error: {e}")
                await ctx.send(embed=discord.Embed(
                    description=self._friendly_error(str(e)),
                    color=0xFF3333
                ))

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis model
    # ────────────────────────────────────────────────────────────
    @commands.command(name='model', aliases=['models'], help='Lihat daftar model AI yang tersedia')
    async def list_models(self, ctx: commands.Context):
        if not self.models:
            return await ctx.send("Tidak ada model AI yang terkonfigurasi di `.env`.")
            
        lines = "\n".join(
            f"`{i+1}.` {label} — `{mid}`"
            for i, (mid, label) in enumerate(self.models)
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
    # Command: !jarvis image
    # ────────────────────────────────────────────────────────────
    @commands.command(name='image', aliases=['img', 'gambar'], help='Buat gambar AI dari deskripsi teks')
    async def image(self, ctx: commands.Context, *, prompt: str):
        if not self.custom_image_url or not self.custom_image_key:
            return await ctx.send(embed=discord.Embed(
                description="❌ **Image API** tidak terkonfigurasi di file `.env`.",
                color=0xFF3333
            ))

        status_msg = await ctx.send(embed=discord.Embed(
            description=f"🎨 Membuat gambar untuk: **{prompt}**\n⏳ Harap tunggu sebentar...",
            color=0xf1c40f
        ))

        async with ctx.typing():
            try:
                image_bytes = await self._generate_image_custom(prompt)
                
                await status_msg.delete()
                file = discord.File(fp=io.BytesIO(image_bytes), filename="jarvis_image.png")
                embed = discord.Embed(
                    title="🖼️ Gambar Dibuat!",
                    description=f"**Prompt:** {prompt}",
                    color=0x00E5FF
                )
                embed.set_image(url="attachment://jarvis_image.png")
                embed.set_footer(
                    text=f"Powered by Jarvis Image API • Diminta oleh {ctx.author.name}",
                    icon_url=ctx.author.display_avatar.url
                )
                await ctx.send(file=file, embed=embed)
                
            except Exception as e:
                print(f"[AI] Image generation failed: {e}")
                await status_msg.edit(embed=discord.Embed(
                    description=f"⚠️ Gagal membuat gambar: `{e}`",
                    color=0xFF3333
                ))

    # ────────────────────────────────────────────────────────────
    # Internal: Custom Image API (from image_gen.js)
    # ────────────────────────────────────────────────────────────
    async def _generate_image_custom(self, prompt: str) -> bytes:
        headers = {
            "Authorization": f"Bearer {self.custom_image_key}",
            "Content-Type": "application/json",
        }
        payload = {"prompt": prompt}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.custom_image_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Image API HTTP {resp.status}: {text[:150]}")
                return await resp.read()

    # ────────────────────────────────────────────────────────────
    # Internal: download PDF dari URL
    # ────────────────────────────────────────────────────────────
    async def _download_pdf(self, url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    raise ValueError(f"Gagal mengunduh PDF (HTTP {resp.status}).")
                content_type = resp.headers.get("Content-Type", "")
                if "pdf" not in content_type and not url.lower().endswith(".pdf"):
                    raise ValueError("URL bukan file PDF yang valid.")
                data = await resp.read()
                if len(data) > 20 * 1024 * 1024:  # 20MB limit
                    raise ValueError("File PDF terlalu besar (maks 20MB).")
                return data

    # ────────────────────────────────────────────────────────────
    # Internal: extract teks dari bytes PDF menggunakan pypdf
    # ────────────────────────────────────────────────────────────
    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            pages  = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
            return "\n\n".join(pages)
        except ImportError:
            raise ValueError(
                "Package `pypdf` belum terinstall.\n"
                "Jalankan: `pip install pypdf`"
            )
        except Exception as e:
            raise ValueError(f"Gagal membaca PDF: {e}")

    # ────────────────────────────────────────────────────────────
    # Internal: query — otomatis pilih Jarvis API atau Groq direct
    # ────────────────────────────────────────────────────────────
    async def _query(self, sys_instruction: str, now_str: str, question: str, max_tokens: int = 1000):
        enriched = f"[Context: {now_str}]\n{question}" if now_str else question

        if self.jarvis_api_url:
            return await self._query_jarvis_api(enriched, sys_instruction, max_tokens)
        else:
            return await self._query_groq_direct(enriched, sys_instruction, max_tokens)

    async def _query_jarvis_api(self, message: str, system: str, max_tokens: int):
        """Kirim request ke Jarvis Custom API (api_server.py)."""
        payload = {
            "message":       message,
            "system_prompt": system,
            "provider":      "auto",
            "max_tokens":    max_tokens,
            "temperature":   0.7,
        }
        headers = {
            "x-api-key":    self.jarvis_api_key,
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.jarvis_api_url}/chat",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 401:
                    raise Exception("🔑 **JARVIS_API_SECRET** tidak valid.")
                if resp.status == 503:
                    data = await resp.json()
                    raise Exception(f"Semua provider gagal: {data.get('detail', {}).get('errors', {})}")
                if resp.status != 200:
                    raise Exception(f"Jarvis API error HTTP {resp.status}")
                data = await resp.json()
                model_label = f"{data['provider'].capitalize()} — {data['model']} ({data['latency_ms']}ms)"
                return data["answer"], model_label

    async def _query_groq_direct(self, message: str, system: str, max_tokens: int):
        """Fallback: query langsung ke Groq tanpa custom API."""
        last_error = None
        for model_id, model_label in self.models:
            try:
                print(f"[AI] Trying Groq model: {model_id}")
                response = await self.client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": message},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.7,
                )
                return response.choices[0].message.content, model_label
            except Exception as e:
                err_str = str(e)
                print(f"[AI] {model_id} failed: {err_str}")
                if "401" in err_str or "invalid_api_key" in err_str.lower():
                    raise Exception("🔑 **API Key Groq tidak valid.**")
                last_error = e
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
