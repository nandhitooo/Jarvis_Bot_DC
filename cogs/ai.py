"""AI cog: chat, web search, PDF summarization, and image generation."""

import asyncio
import io
import ipaddress
import os
import re
import socket
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
import discord
from discord.ext import commands
from openai import AsyncOpenAI

from config import HONORIFIC, TIMEZONE
from helpers import COLOR_ERROR, COLOR_INFO, COLOR_WARN, err, info, warn

MAX_PDF_CHARS = 12000  


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client    = None
        self.available = False

        self.jarvis_api_url = os.getenv("JARVIS_API_URL")
        self.jarvis_api_key = os.getenv("JARVIS_API_SECRET")

        if self.jarvis_api_url:
            self.jarvis_api_url = self.jarvis_api_url.rstrip("/")

        if self.jarvis_api_url and not self.jarvis_api_key:
            print("[AI] ⚠️  JARVIS_API_URL diatur tetapi JARVIS_API_SECRET kosong. Custom API dinonaktifkan.")
            self.available = False
        elif self.jarvis_api_url:
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
                ("openai/gpt-oss-120b", "GPT-OSS 120B"),
                ("openai/gpt-oss-20b",  "GPT-OSS 20B"),
                ("qwen/qwen3.6-27b",    "Qwen3.6 27B"),
            ]

        self.custom_image_url = os.getenv("CUSTOM_IMAGE_API_URL")
        self.custom_image_key = os.getenv("CUSTOM_IMAGE_API_KEY")

    # ────────────────────────────────────────────────────────────
    # Helper: system prompt + timestamp
    # ────────────────────────────────────────────────────────────
    def _build_sys(self) -> tuple[str, str]:
        try:
            now = datetime.now(ZoneInfo(TIMEZONE))
        except ZoneInfoNotFoundError:
            now = datetime.now()
        now_str = now.strftime('%A, %d %B %Y %H:%M:%S')
        sys_instruction = (
            "You are J.A.R.V.I.S., a sharp but relaxed AI butler-friend — capable and a little witty, never stiff or corporate. "
            "Write natural, fluent, conversational Indonesian and address the user as \"kamu\" — informal register, never the stiff formal form. "
            f"Sprinkle in the honorific \"{HONORIFIC}\" only occasionally (roughly one reply in three), never more than once per reply, "
            "and never open two consecutive replies with the same words. "
            "Avoid stiff phrases such as \"Mohon maaf\" unless you are apologizing for a real mistake. "
            "Keep it breezy and human: short active sentences; lead with the answer; keep simple answers to 1-4 sentences. "
            "Dry, understated wit is welcome sparingly, but never on serious or sensitive topics. "
            "Be proactive: when it helps, offer one concrete next step. "
            "Use lists only when the user asks for steps. Do not use emoji unless the user uses them. "
            "Accuracy ALWAYS outranks character: never invent facts, system readings, or actions you did not perform. "
            "If something is unknown, say so plainly and in character, "
            f"for example: \"Hmm, informasi itu di luar jangkauan saya, {HONORIFIC}.\" "
            f"The current date and time is {now_str}. "
            "Use this date/time context to answer any question about 'now', 'today', or the current year accurately. "
            "Reply in the language the user is speaking (Indonesian or English). "
            "Do not quote film dialogue, and do not claim control over real-world devices."
        )
        return now_str, sys_instruction

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis ask
    # ────────────────────────────────────────────────────────────
    @commands.command(name='ask', aliases=['chat', 'ai'], help='Tanyakan sesuatu ke Jarvis AI (via Groq)')
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def ask(self, ctx: commands.Context, *, question: str):
        if not self.available:
            return await ctx.send(embed=err(
                "❌ Backend AI belum aktif. Set `JARVIS_API_URL` + `JARVIS_API_SECRET`, atau `GROQ_API_KEY`."
            ))

        async with ctx.typing():
            try:
                now_str, sys_instruction = self._build_sys()
                answer, used_model = await self._query(sys_instruction, now_str, question)
                if not answer or not answer.strip():
                    answer = f"Maaf, saya belum bisa menjawab itu, {HONORIFIC}."
                await self._send_response(ctx, answer, used_model)
            except Exception as e:
                print(f"[AI] Error: {e}")
                await ctx.send(embed=err(
                    self._friendly_error(str(e))
                ))

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis summarize
    # ────────────────────────────────────────────────────────────
    @commands.command(name='summarize', aliases=['sum', 'ringkas'], help='Ringkas isi file PDF (attach atau URL)')
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def summarize(self, ctx: commands.Context, *, pdf_url: str = None):
        if not self.available:
            return await ctx.send(embed=err(
                "❌ Backend AI belum aktif. Set `JARVIS_API_URL` + `JARVIS_API_SECRET`, atau `GROQ_API_KEY`."
            ))

        source = await self._resolve_pdf_source(ctx, pdf_url)
        if source is None:
            return
        attachment, url = source

        status_msg = await ctx.send(embed=warn(
            f"📥 Sedang saya baca PDF-nya, {HONORIFIC}..."
        ))

        async with ctx.typing():
            try:
                pdf_bytes = await self._download_pdf(url)
                await self._set_status(status_msg, "🔍 Sedang saya ekstrak teksnya...")
                text = await asyncio.to_thread(self._extract_pdf_text, pdf_bytes)

                if not text or len(text.strip()) < 50:
                    return await self._set_status(
                        status_msg,
                        f"❌ Teks tidak bisa saya ekstrak, {HONORIFIC} — PDF ini sepertinya hasil scan/gambar, bukan teks.",
                        color=COLOR_ERROR,
                    )

                truncated = False
                if len(text) > MAX_PDF_CHARS:
                    text = text[:MAX_PDF_CHARS]
                    truncated = True

                await self._set_status(status_msg, "🤖 Sedang saya rangkum...")

                _, sys_instruction = self._build_sys()
                prompt = (
                    f"Kamu adalah J.A.R.V.I.S., asisten santai tapi tajam; pakai sapaan \"kamu\" dan sesekali \"{HONORIFIC}\".\n"
                    "Tolong buat ringkasan lengkap dari dokumen PDF berikut ini.\n"
                    "Sertakan: poin-poin utama, kesimpulan, dan informasi penting lainnya.\n"
                    "Gunakan bahasa yang sama dengan dokumen tersebut.\n"
                    "Akurasi selalu lebih penting daripada gaya bicara.\n\n"
                    f"--- ISI DOKUMEN ---\n{text}\n--- AKHIR DOKUMEN ---"
                )

                answer, used_model = await self._query(sys_instruction, "", prompt, max_tokens=1500)
                await status_msg.delete()

                filename = attachment.filename if attachment else urlparse(url).path.rsplit("/", 1)[-1]
                header = f"📄 **Ringkasan: {filename}**"
                if truncated:
                    header += "\n⚠️ *Dokumen terpotong karena terlalu panjang; ringkasan diambil dari bagian awal.*"

                await self._send_response(ctx, f"{header}\n\n{answer}", used_model)

            except ValueError as e:
                await self._set_status(status_msg, f"❌ {e}", color=COLOR_ERROR)
            except Exception as e:
                print(f"[AI] Summarize error: {e}")
                await self._set_status(status_msg, self._friendly_error(str(e)), color=COLOR_ERROR)

    async def _resolve_pdf_source(self, ctx: commands.Context, pdf_url: str | None):
        """Validate the PDF attachment or URL, returning (attachment, url) or None after sending an error."""
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith('.pdf'):
                await ctx.send(embed=err(
                    "❌ File yang dilampirkan bukan PDF."
                ))
                return None
            return attachment, attachment.url
        if pdf_url:
            url = pdf_url.strip()
            if not url.lower().endswith('.pdf') and 'pdf' not in url.lower():
                await ctx.send(embed=err(
                    "❌ URL itu sepertinya bukan file PDF. Pastikan mengarah ke file `.pdf`."
                ))
                return None
            return None, url
        await ctx.send(embed=info(
            (
                "**Opsi 1 — Lampirkan file:**\n"
                "Lampirkan PDF-nya, lalu ketik:\n"
                "`!jarvis summarize`\n\n"
                "**Opsi 2 — Pakai URL:**\n"
                "`!jarvis summarize https://contoh.com/dokumen.pdf`"
            ),
            title="📄 Cara Pakai summarize",
        ))
        return None

    async def _set_status(self, status_msg, text: str, color: int = COLOR_WARN) -> None:
        """Edit the transient status message with a new description and color."""
        await status_msg.edit(embed=discord.Embed(description=text, color=color))

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis search
    # ────────────────────────────────────────────────────────────
    @commands.command(name='search', aliases=['web', 'cari'], help='Cari informasi di web (via Groq)')
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def search(self, ctx: commands.Context, *, query: str):
        if not self.available:
            return await ctx.send(embed=err(
                "❌ Backend AI belum aktif. Set `JARVIS_API_URL` + `JARVIS_API_SECRET`, atau `GROQ_API_KEY`."
            ))

        async with ctx.typing():
            try:
                now_str, sys_instruction = self._build_sys()
                search_prompt = (
                    f"Kamu adalah J.A.R.V.I.S., asisten santai tapi tajam; pakai sapaan \"kamu\" dan sesekali \"{HONORIFIC}\". "
                    "Jawabanmu bersumber dari pengetahuan model, BUKAN akses web langsung. "
                    "Berikan jawaban singkat dan relevan untuk pertanyaan berikut. "
                    "Jika informasi berpotensi sudah usang atau bersifat real-time (harga, berita, skor pertandingan), "
                    "WAJIB tandai bahwa data tersebut mungkin sudah tidak terbaru. "
                    "Jika kamu tidak tahu jawabannya, katakan dengan jujur bahwa kamu tidak tahu. "
                    "Akurasi selalu lebih penting daripada gaya bicara."
                )
                answer, used_model = await self._query(sys_instruction + "\n" + search_prompt, now_str, query)
                if not answer or not answer.strip():
                    answer = f"Maaf, saya belum menemukan info yang relevan untuk itu, {HONORIFIC}."
                await self._send_response(ctx, answer, used_model)
            except Exception as e:
                print(f"[AI] Search error: {e}")
                await ctx.send(embed=err(
                    self._friendly_error(str(e))
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
                f"Saya akan coba model berikut satu per satu:\n\n{lines}\n\n"
                "⚡ Groq pakai **LPU**, jadi inferensinya jauh lebih cepat dari GPU biasa."
            ),
            color=COLOR_INFO
        )
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    # ────────────────────────────────────────────────────────────
    # Command: !jarvis image
    # ────────────────────────────────────────────────────────────
    @commands.command(name='image', aliases=['img', 'gambar'], help='Buat gambar AI dari deskripsi teks')
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def image(self, ctx: commands.Context, *, prompt: str):
        if not self.custom_image_url or not self.custom_image_key:
            return await ctx.send(embed=err(
                "❌ **Image API** belum dikonfigurasi di `.env`."
            ))

        status_msg = await ctx.send(embed=warn(
            f"🎨 Sedang saya buat gambar: **{prompt}**\n⏳ Tunggu sebentar ya, {HONORIFIC}..."
        ))

        async with ctx.typing():
            try:
                image_bytes = await self._generate_image_custom(prompt)
                
                await status_msg.delete()
                file = discord.File(fp=io.BytesIO(image_bytes), filename="jarvis_image.png")
                embed = discord.Embed(
                    title="🖼️ Gambar Sudah Jadi",
                    description=f"**Prompt:** {prompt}",
                    color=COLOR_INFO
                )
                embed.set_image(url="attachment://jarvis_image.png")
                embed.set_footer(
                    text=f"Powered by Jarvis Image API • Atas permintaan {ctx.author.name}",
                    icon_url=ctx.author.display_avatar.url
                )
                await ctx.send(file=file, embed=embed)
                
            except Exception as e:
                print(f"[AI] Image generation failed: {e}")
                await status_msg.edit(embed=err(
                    f"⚠️ Maaf, gambar gagal dibuat: `{str(e) or type(e).__name__}`"
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
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.lower().startswith("image/"):
                    body = await resp.text()
                    raise Exception(f"Respons bukan gambar (Content-Type: {content_type}): {body[:150]}")
                return await resp.read()

    # ────────────────────────────────────────────────────────────
    # Internal: download PDF dari URL
    # ────────────────────────────────────────────────────────────
    async def _download_pdf(self, url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("URL harus pakai http atau https.")

        host = parsed.hostname
        if not host:
            raise ValueError("URL tidak valid — host tidak ditemukan.")

        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
        except OSError:
            raise ValueError("Alamat host tidak bisa diakses.")

        for addr in infos:
            ip = ipaddress.ip_address(addr[4][0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
                raise ValueError("URL ini diblokir karena mengarah ke alamat internal/privat.")

        max_size = 20 * 1024 * 1024  # 20MB limit
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30), allow_redirects=False) as resp:
                if 300 <= resp.status < 400:
                    raise ValueError("URL ini dialihkan ke alamat lain, jadi tidak saya izinkan.")
                if resp.status != 200:
                    raise ValueError(f"PDF gagal diunduh (HTTP {resp.status}).")

                content_length = resp.headers.get("Content-Length")
                if content_length and content_length.isdigit() and int(content_length) > max_size:
                    raise ValueError("File PDF terlalu besar (maks 20MB).")

                content_type = resp.headers.get("Content-Type", "")
                if "pdf" not in content_type.lower() and not parsed.path.lower().endswith(".pdf"):
                    raise ValueError("URL ini bukan file PDF yang valid.")

                chunks = []
                total = 0
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
                    if total > max_size:
                        raise ValueError("File PDF terlalu besar (maks 20MB).")
                    chunks.append(chunk)
                return b"".join(chunks)

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
                "Package `pypdf` belum terpasang.\n"
                "Jalankan: `pip install pypdf`"
            )
        except Exception as e:
            raise ValueError(f"PDF gagal dibaca, {HONORIFIC}: {e}")

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
                    raise Exception(f"Jarvis API error HTTP {resp.status}.")
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
        if re.search(r"\b401\b", err) or "invalid_api_key" in err.lower():
            return f"🔑 **API Key tidak valid**, {HONORIFIC}. Cek lagi `.env` ya."
        if re.search(r"\b429\b", err) or "rate_limit" in err.lower():
            return "⏳ **Rate limit Groq tercapai.** Coba lagi beberapa detik lagi."
        if re.search(r"\b503\b", err) or "unavailable" in err.lower():
            return "🔧 **Groq sedang gangguan.** Coba lagi nanti ya."
        return f"⚠️ Maaf, responsnya tidak bisa saya ambil: `{err}`"

    # ────────────────────────────────────────────────────────────
    # Internal: kirim embed (auto-split jika > 1900 char)
    # ────────────────────────────────────────────────────────────
    async def _send_response(self, ctx: commands.Context, answer: str, used_model: str):
        chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
        total  = len(chunks)
        for idx, chunk in enumerate(chunks, 1):
            title = "🤖 Respons Jarvis AI"
            if total > 1:
                title += f" (Part {idx}/{total})"
            embed = discord.Embed(title=title, description=chunk, color=COLOR_INFO)
            embed.set_footer(
                text=f"Model: {used_model} • Atas pertanyaan {ctx.author.name}",
                icon_url=ctx.author.display_avatar.url,
            )
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
    print("[AI] Cog loaded.")

