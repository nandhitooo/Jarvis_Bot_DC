import discord
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
import requests
from bs4 import BeautifulSoup
import re

# yt-dlp options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'socket_timeout': 30,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class QueueEntry:
    """Represents a single item in the queue with both URL and display title."""
    def __init__(self, url: str, title: str = None):
        self.url = url
        self.title = title or url

    def __str__(self):
        return self.title


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url', '')

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream=True):
        loop = loop or asyncio.get_event_loop()
        print(f"[yt-dlp] Extracting info for: {url}")

        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(url, download=not stream)
            )
        except yt_dlp.utils.DownloadError as e:
            raise Exception(f"yt-dlp download error: {e}") from e

        if data is None:
            raise Exception("yt-dlp returned no data — the URL may be invalid or unavailable.")

        # Playlist / multiple entries
        if 'entries' in data:
            return data

        # Single track
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> deque[QueueEntry]
        self.queues: dict[int, deque[QueueEntry]] = {}
        # guild_id -> asyncio.Task
        self.disconnect_tasks: dict[int, asyncio.Task] = {}

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def get_queue(self, ctx: commands.Context) -> deque[QueueEntry]:
        if ctx.guild.id not in self.queues:
            self.queues[ctx.guild.id] = deque()
        return self.queues[ctx.guild.id]

    def _cancel_disconnect(self, guild_id: int):
        task = self.disconnect_tasks.pop(guild_id, None)
        if task:
            task.cancel()

    def _schedule_disconnect(self, ctx: commands.Context):
        self._cancel_disconnect(ctx.guild.id)
        self.disconnect_tasks[ctx.guild.id] = self.bot.loop.create_task(
            self._auto_disconnect(ctx)
        )

    async def _auto_disconnect(self, ctx: commands.Context):
        await asyncio.sleep(300)  # 5 minutes
        vc = ctx.voice_client
        if vc and not vc.is_playing() and not self.get_queue(ctx):
            await vc.disconnect()
            await ctx.send("💤 Disconnected karena 5 menit tidak ada aktivitas.")
            print(f"[Jarvis] Auto-disconnect dari {ctx.guild.name}")

    async def get_spotify_metadata(self, url: str) -> str | None:
        """Scrape Open Graph metadata from a Spotify URL and return a search query."""
        try:
            # Normalize regional URLs, e.g. spotify.com/id-id/ → spotify.com/
            url = re.sub(r'spotify\.com/[a-z]{2}(?:-[a-z]{2})?/', 'spotify.com/', url)

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.get(url, headers=headers, timeout=15)
            )

            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find('meta', property='og:title')
            desc_tag = soup.find('meta', property='og:description')

            if not title_tag:
                return None

            title = title_tag['content'].strip()
            if desc_tag:
                desc = desc_tag['content']
                if ' · ' in desc:
                    parts = desc.split(' · ')
                    artist = parts[1].replace('Album by ', '').strip()
                    return f"{title} {artist}"
            return title

        except Exception as e:
            print(f"[Spotify scrape] Error: {e}")
            return None

    async def _resolve_search(self, search: str) -> str:
        """
        If search is a Spotify link, resolve it to a YouTube search string.
        Returns the (possibly modified) search string.
        Raises Exception if Spotify metadata cannot be fetched.
        """
        if 'spotify.com' not in search:
            return search

        metadata = await self.get_spotify_metadata(search)
        if not metadata:
            raise Exception("Tidak bisa mengambil metadata dari link Spotify ini.")
        print(f"[Spotify] Resolved to: {metadata}")
        return f"ytsearch:{metadata}"

    # ------------------------------------------------------------------ #
    #  Playback core                                                       #
    # ------------------------------------------------------------------ #

    def play_next(self, ctx: commands.Context):
        """Called by discord.py after a track finishes (in a non-async thread)."""
        queue = self.get_queue(ctx)
        if queue:
            entry = queue.popleft()
            asyncio.run_coroutine_threadsafe(
                self._play_entry(ctx, entry), self.bot.loop
            )
        else:
            self._schedule_disconnect(ctx)

    async def _play_entry(self, ctx: commands.Context, entry: QueueEntry):
        """Resolve and play a single QueueEntry."""
        self._cancel_disconnect(ctx.guild.id)

        vc = ctx.voice_client
        if vc is None:
            return  # Bot left the channel already

        async with ctx.typing():
            try:
                resolved_url = await self._resolve_search(entry.url)
                result = await YTDLSource.from_url(resolved_url, loop=self.bot.loop, stream=True)

                if isinstance(result, dict) and 'entries' in result:
                    # Unexpectedly got a playlist (e.g. a ytsearch that expanded)
                    entries = [e for e in result.get('entries', []) if e is not None]
                    if not entries:
                        await ctx.send("❌ Tidak ada lagu yang bisa diputar.")
                        self.play_next(ctx)
                        return

                    # Enqueue the rest at the front of the queue
                    queue = self.get_queue(ctx)
                    for e in reversed(entries[1:]):
                        url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                        queue.appendleft(QueueEntry(url, e.get('title', url)))

                    # Play the first entry
                    first = entries[0]
                    first_url = first.get('webpage_url') or first.get('url') or f"https://www.youtube.com/watch?v={first.get('id')}"
                    player = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True)
                    vc.play(player, after=lambda e: self._after_play(ctx, e))
                    await ctx.send(f"🎶 Now playing: **{player.title}**")
                else:
                    player = result
                    vc.play(player, after=lambda e: self._after_play(ctx, e))
                    await ctx.send(f"🎶 Now playing: **{player.title}**")

            except Exception as e:
                print(f"[_play_entry] Error: {e}")
                await ctx.send(f"❌ Gagal memutar lagu: {e}\nMelanjutkan ke lagu berikutnya...")
                self.play_next(ctx)

    def _after_play(self, ctx: commands.Context, error):
        """Callback setelah setiap lagu selesai."""
        if error:
            print(f"[after_play] Playback error: {error}")
            asyncio.run_coroutine_threadsafe(
                ctx.send(f"⚠️ Terjadi kesalahan saat memutar: {error}"),
                self.bot.loop
            )
        self.play_next(ctx)

    # ------------------------------------------------------------------ #
    #  Commands                                                            #
    # ------------------------------------------------------------------ #

    @commands.command(name='join', help='Bot masuk ke voice channel kamu')
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send(f"❌ {ctx.author.display_name} tidak sedang di voice channel!")
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(f"✅ Bergabung ke **{channel.name}**")

    @commands.command(name='play', help='Putar lagu / playlist dari YouTube, Spotify, SoundCloud, atau cari berdasarkan judul')
    async def play(self, ctx: commands.Context, *, search: str):
        # Auto-join voice channel
        if not ctx.author.voice:
            return await ctx.send("❌ Kamu harus masuk ke voice channel terlebih dahulu.")
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)

        vc = ctx.voice_client

        # Notify for Spotify early
        if 'spotify.com' in search:
            await ctx.send("🔍 Link Spotify terdeteksi. Mencari lagu di YouTube...")

        async with ctx.typing():
            try:
                resolved = await self._resolve_search(search)
                result = await YTDLSource.from_url(resolved, loop=self.bot.loop, stream=True)
            except Exception as e:
                return await ctx.send(f"❌ Error: {e}")

        queue = self.get_queue(ctx)

        # --- Playlist ---
        if isinstance(result, dict) and 'entries' in result:
            entries = [e for e in result.get('entries', []) if e is not None]
            if not entries:
                return await ctx.send("❌ Playlist kosong atau tidak ada lagu yang bisa diputar.")

            if vc.is_playing() or vc.is_paused():
                for e in entries:
                    url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                    queue.append(QueueEntry(url, e.get('title', url)))
                return await ctx.send(f"🎶 Ditambahkan **{player.title}** lagu dari playlist ke antrian.")

            # Play first, queue the rest
            first = entries[0]
            first_url = first.get('webpage_url') or first.get('url') or f"https://www.youtube.com/watch?v={first.get('id')}"
            for e in entries[1:]:
                url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                queue.append(QueueEntry(url, e.get('title', url)))

            try:
                player = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True)
                vc.play(player, after=lambda e: self._after_play(ctx, e))
                await ctx.send(
                    f"🎶 Playlist terdeteksi! Menambahkan **{len(entries)}** lagu ke antrian.\n"
                    f"Sekarang memutar: **{player.title}**"
                )
            except Exception as e:
                await ctx.send(f"❌ Gagal memulai playlist: {e}")

        # --- Single track ---
        else:
            player = result
            if vc.is_playing() or vc.is_paused():
                queue.append(QueueEntry(player.webpage_url or search, player.title))
                await ctx.send(f"✅ Ditambahkan ke antrian: **{player.title}**")
            else:
                vc.play(player, after=lambda e: self._after_play(ctx, e))
                await ctx.send(f"🎶 Sekarang memutar: **{player.title}**")

    @commands.command(name='pause', help='Pause lagu yang sedang diputar')
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send(f"⏸️ Dijeda di menit {ctx.voice_client.position // 60}:{ctx.voice_client.position % 60:02d}.")
        else:
            await ctx.send("❌ Tidak ada lagu yang sedang diputar.")

    @commands.command(name='resume', help='Lanjutkan lagu yang dijeda')
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send(f"▶️ Dilanjutkan di menit {ctx.voice_client.position // 60}:{ctx.voice_client.position % 60:02d}.")
        else:
            await ctx.send("❌ Lagu tidak sedang dijeda.")

    @commands.command(name='skip', help='Lewati lagu yang sedang diputar')
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()  # triggers _after_play → play_next
            await ctx.send("⏭️ Lagu dilewati.")
        else:
            await ctx.send("❌ Tidak ada lagu yang bisa dilewati.")

    @commands.command(name='stop', help='Stop dan bot keluar dari voice channel')
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client:
            self._cancel_disconnect(ctx.guild.id)
            self.get_queue(ctx).clear()
            await ctx.voice_client.disconnect()
            await ctx.send("⏹️ Bot keluar dan antrian dihapus.")
        else:
            await ctx.send("❌ Bot tidak ada di voice channel.")

    @commands.command(name='queue', help='Tampilkan antrian lagu saat ini')
    async def queue(self, ctx: commands.Context):
        q = self.get_queue(ctx)
        if not q:
            return await ctx.send("📭 Antrian kosong.")

        lines = [f"`{i}.` {entry.title}" for i, entry in enumerate(q, 1)]
        # Discord message limit guard
        message = "**📋 Antrian Lagu:**\n" + "\n".join(lines[:20])
        if len(q) > 20:
            message += f"\n... dan **{len(q) - 20}** lagu lainnya."
        await ctx.send(message)

    @commands.command(name='nowplaying', aliases=['np'], help='Tampilkan lagu yang sedang diputar')
    async def nowplaying(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc and vc.is_playing() and hasattr(vc.source, 'title'):
            await ctx.send(f"🎵 Sedang memutar: **{vc.source.title}**")
        else:
            await ctx.send("❌ Tidak ada lagu yang sedang diputar.")

    @commands.command(name='volume', help='Atur volume (0-100)')
    async def volume(self, ctx: commands.Context, vol: int):
        if not (0 <= vol <= 100):
            return await ctx.send("❌ Volume harus antara 0 dan 100.")
        vc = ctx.voice_client
        if vc and hasattr(vc.source, 'volume'):
            vc.source.volume = vol / 100
            await ctx.send(f"🔊 Volume diatur ke **{vol}%**")
        else:
            await ctx.send("❌ Tidak ada audio yang sedang diputar.")

    @commands.command(name='clear', help='Hapus semua lagu dalam antrian')
    async def clear(self, ctx: commands.Context):
        self.get_queue(ctx).clear()
        await ctx.send("🗑️ Antrian telah dihapus.")

    @commands.command(name='remove', help='Hapus lagu tertentu dari antrian berdasarkan nomor')
    async def remove(self, ctx: commands.Context, index: int):
        q = self.get_queue(ctx)
        if 1 <= index <= len(q):
            removed = q[index - 1]
            del q[index - 1]
            await ctx.send(f"❌ Dihapus dari antrian: **{removed.title}**")
        else:
            await ctx.send("❌ Nomor lagu tidak valid dalam antrian.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
