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
    def __init__(self, url: str, title: str = None, requester: discord.Member = None):
        self.url = url
        self.title = title or url
        self.requester = requester

    def __str__(self):
        return self.title


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5, requester=None):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url', '')
        self.requester = requester

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream=True, requester=None):
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
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, requester=requester)


def format_duration(seconds):
    if not seconds:
        return "Live / Unknown"
    minutes = int(seconds) // 60
    seconds = int(seconds) % 60
    hours = minutes // 60
    minutes = minutes % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> deque[QueueEntry]
        self.queues: dict[int, deque[QueueEntry]] = {}
        # guild_id -> asyncio.Task
        self.disconnect_tasks: dict[int, asyncio.Task] = {}
        # guild_id -> deque[str]
        self.playing_histories: dict[int, deque[str]] = {}

    def get_history(self, guild_id: int) -> deque[str]:
        if guild_id not in self.playing_histories:
            self.playing_histories[guild_id] = deque(maxlen=100)
        return self.playing_histories[guild_id]

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
            embed = discord.Embed(
                description="💤 **Disconnected** karena 5 menit tidak ada aktivitas.",
                color=0xf1c40f
            )
            await ctx.send(embed=embed)
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

    def get_now_playing_embed(self, player, author):
        embed = discord.Embed(
            title="🎶 Now Playing",
            description=f"**[{player.title}]({player.webpage_url})**",
            color=0x00E5FF
        )
        thumbnail = player.data.get('thumbnail')
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        uploader = player.data.get('uploader', 'Unknown')
        duration = format_duration(player.data.get('duration'))
        
        embed.add_field(name="Uploader", value=uploader, inline=True)
        embed.add_field(name="Duration", value=duration, inline=True)
        
        if author:
            embed.set_footer(text=f"Diminta oleh {author.name}", icon_url=author.display_avatar.url)
        return embed

    def get_added_to_queue_embed(self, player, author, queue_len):
        embed = discord.Embed(
            title="📥 Added to Queue",
            description=f"**[{player.title}]({player.webpage_url})**",
            color=0x2ecc71
        )
        thumbnail = player.data.get('thumbnail')
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
            
        uploader = player.data.get('uploader', 'Unknown')
        duration = format_duration(player.data.get('duration'))
        
        embed.add_field(name="Uploader", value=uploader, inline=True)
        embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Posisi Antrian", value=f"#{queue_len}", inline=True)
        
        if author:
            embed.set_footer(text=f"Diminta oleh {author.name}", icon_url=author.display_avatar.url)
        return embed

    # ------------------------------------------------------------------ #
    #  Playback core                                                       #
    # ------------------------------------------------------------------ #

    async def _send_empty_queue_message(self, ctx: commands.Context):
        embed = discord.Embed(
            description="🎵 **Antrian lagu telah habis.** Memulai mode standby...",
            color=0x00E5FF
        )
        await ctx.send(embed=embed)

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
            if ctx.voice_client and ctx.voice_client.is_connected():
                asyncio.run_coroutine_threadsafe(
                    self._send_empty_queue_message(ctx), self.bot.loop
                )

    async def _play_entry(self, ctx: commands.Context, entry: QueueEntry):
        """Resolve and play a single QueueEntry."""
        self._cancel_disconnect(ctx.guild.id)

        vc = ctx.voice_client
        if vc is None:
            return  # Bot left the channel already

        async with ctx.typing():
            try:
                resolved_url = await self._resolve_search(entry.url)
                result = await YTDLSource.from_url(resolved_url, loop=self.bot.loop, stream=True, requester=entry.requester)

                if isinstance(result, dict) and 'entries' in result:
                    # Unexpectedly got a playlist (e.g. a ytsearch that expanded)
                    entries = [e for e in result.get('entries', []) if e is not None]
                    if not entries:
                        embed = discord.Embed(
                            description="❌ Tidak ada lagu yang bisa diputar.",
                            color=0xff3333
                        )
                        await ctx.send(embed=embed)
                        self.play_next(ctx)
                        return

                    # Enqueue the rest at the front of the queue
                    queue = self.get_queue(ctx)
                    for e in reversed(entries[1:]):
                        url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                        queue.appendleft(QueueEntry(url, e.get('title', url), entry.requester))

                    # Play the first entry
                    first = entries[0]
                    first_url = first.get('webpage_url') or first.get('url') or f"https://www.youtube.com/watch?v={first.get('id')}"
                    player = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True, requester=entry.requester)
                    vc.play(player, after=lambda e: self._after_play(ctx, e))

                    # Update playing history
                    self.get_history(ctx.guild.id).append(player.title)

                    embed = self.get_now_playing_embed(player, entry.requester or ctx.author)
                    await ctx.send(embed=embed)
                else:
                    player = result
                    vc.play(player, after=lambda e: self._after_play(ctx, e))

                    # Update playing history
                    self.get_history(ctx.guild.id).append(player.title)

                    embed = self.get_now_playing_embed(player, entry.requester or ctx.author)
                    await ctx.send(embed=embed)

            except Exception as e:
                print(f"[_play_entry] Error: {e}")
                embed = discord.Embed(
                    title="⚠️ Playback Error",
                    description=f"Gagal memutar lagu: {e}\nMelanjutkan ke lagu berikutnya...",
                    color=0xff3333
                )
                await ctx.send(embed=embed)
                self.play_next(ctx)

    def _after_play(self, ctx: commands.Context, error):
        """Callback setelah setiap lagu selesai."""
        if error:
            print(f"[after_play] Playback error: {error}")
            embed = discord.Embed(
                description=f"⚠️ Terjadi kesalahan saat memutar: {error}",
                color=0xf1c40f
            )
            asyncio.run_coroutine_threadsafe(
                ctx.send(embed=embed),
                self.bot.loop
            )
        self.play_next(ctx)

    # ------------------------------------------------------------------ #
    #  Commands                                                            #
    # ------------------------------------------------------------------ #

    @commands.command(name='join', help='Bot masuk ke voice channel kamu')
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            embed = discord.Embed(
                description=f"❌ **{ctx.author.display_name}** tidak sedang di voice channel!",
                color=0xff3333
            )
            return await ctx.send(embed=embed)
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        embed = discord.Embed(
            description=f"🟢 Bergabung ke voice channel: **{channel.name}**",
            color=0x2ecc71
        )
        await ctx.send(embed=embed)

    @commands.command(name='play', help='Putar lagu / playlist dari YouTube, Spotify, SoundCloud, atau cari berdasarkan judul')
    async def play(self, ctx: commands.Context, *, search: str):
        # Auto-join voice channel
        if not ctx.author.voice:
            embed = discord.Embed(
                description="❌ Kamu harus masuk ke voice channel terlebih dahulu.",
                color=0xff3333
            )
            return await ctx.send(embed=embed)
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)

        vc = ctx.voice_client

        # Notify for Spotify early
        if 'spotify.com' in search:
            embed = discord.Embed(
                description="🔍 **Link Spotify terdeteksi.** Mencari lagu di YouTube...",
                color=0x1DB954
            )
            await ctx.send(embed=embed)

        async with ctx.typing():
            try:
                resolved = await self._resolve_search(search)
                result = await YTDLSource.from_url(resolved, loop=self.bot.loop, stream=True, requester=ctx.author)
            except Exception as e:
                embed = discord.Embed(
                    description=f"❌ Error: {e}",
                    color=0xff3333
                )
                return await ctx.send(embed=embed)

        queue = self.get_queue(ctx)

        # --- Playlist ---
        if isinstance(result, dict) and 'entries' in result:
            entries = [e for e in result.get('entries', []) if e is not None]
            if not entries:
                embed = discord.Embed(
                    description="❌ Playlist kosong atau tidak ada lagu yang bisa diputar.",
                    color=0xff3333
                )
                return await ctx.send(embed=embed)

            if vc.is_playing() or vc.is_paused():
                for e in entries:
                    url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                    queue.append(QueueEntry(url, e.get('title', url), ctx.author))
                
                embed = discord.Embed(
                    title="🎶 Playlist Added to Queue",
                    description=f"Berhasil menambahkan **{len(entries)}** lagu dari playlist ke antrian.",
                    color=0x2ecc71
                )
                embed.set_footer(text=f"Diminta oleh {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
                return await ctx.send(embed=embed)

            # Play first, queue the rest
            first = entries[0]
            first_url = first.get('webpage_url') or first.get('url') or f"https://www.youtube.com/watch?v={first.get('id')}"
            for e in entries[1:]:
                url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                queue.append(QueueEntry(url, e.get('title', url), ctx.author))

            try:
                player = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True, requester=ctx.author)
                vc.play(player, after=lambda e: self._after_play(ctx, e))
                
                # Update playing history
                self.get_history(ctx.guild.id).append(player.title)

                embed = discord.Embed(
                    title="🎶 Now Playing (Playlist)",
                    description=f"**[{player.title}]({player.webpage_url})**",
                    color=0x00E5FF
                )
                thumbnail = player.data.get('thumbnail')
                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)
                
                uploader = player.data.get('uploader', 'Unknown')
                duration = format_duration(player.data.get('duration'))
                
                embed.add_field(name="Uploader", value=uploader, inline=True)
                embed.add_field(name="Duration", value=duration, inline=True)
                embed.add_field(name="Playlist", value=f"Menambahkan **{len(entries) - 1}** lagu lainnya ke antrian.", inline=False)
                
                embed.set_footer(text=f"Diminta oleh {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
                await ctx.send(embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    description=f"❌ Gagal memulai playlist: {e}",
                    color=0xff3333
                )
                await ctx.send(embed=embed)

        # --- Single track ---
        else:
            player = result
            if vc.is_playing() or vc.is_paused():
                queue.append(QueueEntry(player.webpage_url or search, player.title, ctx.author))
                embed = self.get_added_to_queue_embed(player, ctx.author, len(queue))
                await ctx.send(embed=embed)
            else:
                vc.play(player, after=lambda e: self._after_play(ctx, e))
                
                # Update playing history
                self.get_history(ctx.guild.id).append(player.title)

                embed = self.get_now_playing_embed(player, ctx.author)
                await ctx.send(embed=embed)

    @commands.command(name='pause', help='Pause lagu yang sedang diputar')
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            pos_text = ""
            if hasattr(ctx.voice_client, 'position'):
                pos_text = f" dijeda"
            embed = discord.Embed(
                description=f"⏸️ **Playback dijeda** di menit **{ctx.voice_client.position // 60}:{ctx.voice_client.position % 60:02d}** {pos_text}.",
                color=0xf1c40f
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Tidak ada lagu yang sedang diputar.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='resume', help='Lanjutkan lagu yang dijeda')
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            pos_text = ""
            if hasattr(ctx.voice_client, 'position'):
                pos_text = f" dilanjutkan"
            embed = discord.Embed(
                description=f"▶️ **Playback dilanjutkan** di menit **{ctx.voice_client.position // 60}:{ctx.voice_client.position % 60:02d}** {pos_text}.",
                color=0x2ecc71
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Lagu tidak sedang dijeda.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='skip', help='Lewati lagu yang sedang diputar')
    async def skip(self, ctx: commands.Context):
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()  # triggers _after_play → play_next
            embed = discord.Embed(
                description="⏭️ **Lagu dilewati.**",
                color=0x00E5FF
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Tidak ada lagu yang bisa dilewati.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='stop', help='Stop dan bot keluar dari voice channel')
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client:
            self._cancel_disconnect(ctx.guild.id)
            self.get_queue(ctx).clear()
            await ctx.voice_client.disconnect()
            embed = discord.Embed(
                description="⏹️ **Bot keluar dan antrian dihapus.**",
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Bot tidak ada di voice channel.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='queue', help='Tampilkan antrian lagu saat ini')
    async def queue(self, ctx: commands.Context):
        q = self.get_queue(ctx)
        vc = ctx.voice_client
        
        embed = discord.Embed(title="📋 Antrian Lagu", color=0x00E5FF)
        
        # Now playing
        if vc and vc.is_playing() and hasattr(vc.source, 'title'):
            embed.description = f"**Sekarang Memutar:**\n🎶 **{vc.source.title}**\n\n"
        else:
            embed.description = "**Sekarang Memutar:**\n💤 Tidak ada lagu yang sedang diputar.\n\n"
            
        # Up next
        if not q:
            embed.description += "**Antrian Selanjutnya:**\n📭 Antrian kosong."
        else:
            lines = []
            for i, entry in enumerate(q, 1):
                req_str = f" (diminta oleh {entry.requester.mention})" if entry.requester else ""
                lines.append(f"`{i}.` {entry.title}{req_str}")
            
            queue_text = "\n".join(lines[:15])
            if len(q) > 15:
                queue_text += f"\n... dan **{len(q) - 15}** lagu lainnya."
            
            embed.description += f"**Antrian Selanjutnya:**\n{queue_text}"
            
        embed.set_footer(text=f"Total lagu dalam antrian: {len(q)}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='nowplaying', aliases=['np'], help='Tampilkan lagu yang sedang diputar')
    async def nowplaying(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc and vc.is_playing() and hasattr(vc.source, 'title'):
            requester = getattr(vc.source, 'requester', None) or ctx.author
            embed = self.get_now_playing_embed(vc.source, requester)
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Tidak ada lagu yang sedang diputar.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='playinghistory', aliases=['ph'], help='Tampilkan history lagu yang sudah diputar')
    async def playing_history(self, ctx: commands.Context):
        history = self.get_history(ctx.guild.id)
        if not history:
            embed = discord.Embed(
                description="📭 Belum ada lagu yang diputar.",
                color=0x00E5FF
            )
            return await ctx.send(embed=embed)

        lines = [f"`{i}.` {title}" for i, title in enumerate(reversed(history), 1)]
        embed = discord.Embed(
            title="📜 Playing History",
            description="\n".join(lines[:15]),
            color=0x00E5FF
        )
        if len(history) > 15:
            embed.description += f"\n... dan **{len(history) - 15}** lagu lainnya."
            
        embed.set_footer(text=f"Total history: {len(history)} lagu", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='volume', help='Atur volume (0-100)')
    async def volume(self, ctx: commands.Context, vol: int):
        if not (0 <= vol <= 100):
            embed = discord.Embed(
                description="❌ Volume harus antara 0 dan 100.",
                color=0xff3333
            )
            return await ctx.send(embed=embed)
        vc = ctx.voice_client
        if vc and hasattr(vc.source, 'volume'):
            vc.source.volume = vol / 100
            embed = discord.Embed(
                description=f"🔊 **Volume diatur ke {vol}%**",
                color=0x00E5FF
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Tidak ada audio yang sedang diputar.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='clear', help='Hapus semua lagu dalam antrian')
    async def clear(self, ctx: commands.Context):
        self.get_queue(ctx).clear()
        embed = discord.Embed(
            description="🗑️ **Antrian telah dihapus.**",
            color=0xe74c3c
        )
        await ctx.send(embed=embed)

    @commands.command(name='remove', help='Hapus lagu tertentu dari antrian berdasarkan nomor')
    async def remove(self, ctx: commands.Context, index: int):
        q = self.get_queue(ctx)
        if 1 <= index <= len(q):
            removed = q[index - 1]
            del q[index - 1]
            embed = discord.Embed(
                description=f"🗑️ **Dihapus dari antrian:** {removed.title}",
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description="❌ Nomor lagu tidak valid dalam antrian.",
                color=0xff3333
            )
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
