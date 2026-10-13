import discord
from discord.ext import commands
import yt_dlp
import asyncio
from collections import deque
import requests
from bs4 import BeautifulSoup
import re
import threading

# Sapaan tetap untuk seluruh pesan pengguna
HONORIFIC = "Boss"

# yt-dlp options
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'ignoreerrors': True,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'extract_flat': 'in_playlist',
    'source_address': '0.0.0.0',
    'socket_timeout': 30,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

ytdl_lock = threading.Lock()


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
        self.duration = data.get('duration')
        self.requester = requester

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream=True, requester=None):
        loop = loop or asyncio.get_event_loop()
        print(f"[yt-dlp] Extracting info for: {url}")

        def _extract():
            with ytdl_lock:
                return ytdl.extract_info(url, download=not stream)

        try:
            data = await loop.run_in_executor(None, _extract)
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
        # guild_id -> float (0.0 – 1.0), default 0.5
        self.guild_volumes: dict[int, float] = {}
        # guild ids currently transitioning between tracks
        self.transitioning: set[int] = set()

    def get_history(self, guild_id: int) -> deque[str]:
        if guild_id not in self.playing_histories:
            self.playing_histories[guild_id] = deque(maxlen=100)
        return self.playing_histories[guild_id]

    def get_volume(self, guild_id: int) -> float:
        """Return saved volume for a guild (default 0.5)."""
        return self.guild_volumes.get(guild_id, 0.5)

    def extract_song_metadata(self, data: dict) -> dict[str, str]:
        artist = data.get('artist') or data.get('creator') or data.get('track')
        album = data.get('album') or data.get('album_artist')
        if not artist:
            title = data.get('title', '')
            if ' - ' in title:
                left, _ = title.split(' - ', 1)
                if len(left) <= 40:
                    artist = left.strip()
        if not artist:
            artist = 'Unknown'
        if not album:
            album = 'Unknown'

        return {
            'artist': artist,
            'album': album,
            'uploader': data.get('uploader', 'Unknown'),
            'duration': format_duration(data.get('duration')),
            'extractor': data.get('extractor', 'Unknown').capitalize(),
        }

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

    async def _same_voice(self, ctx: commands.Context) -> bool:
        """True hanya jika author berada di voice channel yang sama dengan bot."""
        author_voice = getattr(ctx.author, "voice", None)
        if (
            author_voice is None
            or ctx.voice_client is None
            or author_voice.channel != ctx.voice_client.channel
        ):
            embed = discord.Embed(
                description=f"❌ Mohon maaf, {HONORIFIC}, Anda perlu berada di voice channel yang sama dengan saya.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return False
        return True

    async def _auto_disconnect(self, ctx: commands.Context):
        await asyncio.sleep(300)  # 5 minutes
        vc = ctx.voice_client
        if vc and not vc.is_playing() and not vc.is_paused() and not self.get_queue(ctx):
            await vc.disconnect()
            embed = discord.Embed(
                description=f"💤 Saya keluar dari voice channel setelah 5 menit tanpa aktivitas, {HONORIFIC}.",
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
            raise Exception(f"Metadata dari tautan Spotify ini tidak dapat saya ambil, {HONORIFIC}.")
        print(f"[Spotify] Resolved to: {metadata}")
        return f"ytsearch:{metadata}"

    def get_now_playing_embed(self, player, author):
        metadata = self.extract_song_metadata(player.data)
        embed = discord.Embed(
            title="🎶 Sedang Diputar",
            description=f"**[{player.title}]({player.webpage_url})**",
            color=0x00E5FF
        )
        thumbnail = player.data.get('thumbnail')
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        
        embed.add_field(name="Artis", value=metadata['artist'], inline=True)
        embed.add_field(name="Album", value=metadata['album'], inline=True)
        embed.add_field(name="Uploader", value=metadata['uploader'], inline=True)
        embed.add_field(name="Durasi", value=metadata['duration'], inline=True)
        embed.add_field(name="Sumber", value=metadata['extractor'], inline=True)
        
        if author:
            embed.set_footer(text=f"Atas permintaan {author.name}", icon_url=author.display_avatar.url)
        return embed

    def get_added_to_queue_embed(self, player, author, queue_len):
        metadata = self.extract_song_metadata(player.data)
        embed = discord.Embed(
            title="📥 Masuk ke Antrian",
            description=f"**[{player.title}]({player.webpage_url})**",
            color=0x2ecc71
        )
        thumbnail = player.data.get('thumbnail')
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
            
        embed.add_field(name="Artis", value=metadata['artist'], inline=True)
        embed.add_field(name="Album", value=metadata['album'], inline=True)
        embed.add_field(name="Uploader", value=metadata['uploader'], inline=True)
        embed.add_field(name="Durasi", value=metadata['duration'], inline=True)
        embed.add_field(name="Posisi Antrian", value=f"#{queue_len}", inline=True)
        
        if author:
            embed.set_footer(text=f"Atas permintaan {author.name}", icon_url=author.display_avatar.url)
        return embed

    # ------------------------------------------------------------------ #
    #  Playback core                                                       #
    # ------------------------------------------------------------------ #

    async def _send_empty_queue_message(self, ctx: commands.Context):
        embed = discord.Embed(
            description=f"🎵 Antrian sudah habis, {HONORIFIC}. Sistem kembali ke mode siaga.",
            color=0x00E5FF
        )
        await ctx.send(embed=embed)

    def play_next(self, ctx: commands.Context):
        """Called by discord.py after a track finishes (in a non-async thread)."""
        queue = self.get_queue(ctx)
        if queue:
            entry = queue.popleft()
            self.transitioning.add(ctx.guild.id)
            asyncio.run_coroutine_threadsafe(
                self._play_entry(ctx, entry), self.bot.loop
            )
            return True
        else:
            self.bot.loop.call_soon_threadsafe(self._schedule_disconnect, ctx)
            if ctx.voice_client and ctx.voice_client.is_connected():
                asyncio.run_coroutine_threadsafe(
                    self._send_empty_queue_message(ctx), self.bot.loop
                )
            return False

    async def _play_entry(self, ctx: commands.Context, entry: QueueEntry):
        """Resolve and play a single QueueEntry."""
        handed_off = False
        self._cancel_disconnect(ctx.guild.id)

        try:
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
                                description=f"❌ Mohon maaf, {HONORIFIC}, tidak ada lagu yang bisa diputar.",
                                color=0xff3333
                            )
                            await ctx.send(embed=embed)
                            handed_off = self.play_next(ctx)
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
                        player.volume = self.get_volume(ctx.guild.id)

                        if vc.is_playing():
                            # Audio masih berjalan — kembalikan ke antrian agar tidak ada lagu yang hilang
                            queue.appendleft(QueueEntry(first_url, first.get('title', first_url), entry.requester))
                            player.cleanup()
                            return
                        vc.play(player, after=lambda e: self._after_play(ctx, e))

                        # Update playing history
                        self.get_history(ctx.guild.id).append(player.title)

                        embed = self.get_now_playing_embed(player, entry.requester or ctx.author)
                        await ctx.send(embed=embed)
                    else:
                        player = result
                        player.volume = self.get_volume(ctx.guild.id)

                        if vc.is_playing():
                            # Audio masih berjalan — kembalikan ke antrian agar tidak ada lagu yang hilang
                            self.get_queue(ctx).appendleft(entry)
                            player.cleanup()
                            return
                        vc.play(player, after=lambda e: self._after_play(ctx, e))

                        # Update playing history
                        self.get_history(ctx.guild.id).append(player.title)

                        embed = self.get_now_playing_embed(player, entry.requester or ctx.author)
                        await ctx.send(embed=embed)

                except Exception as e:
                    print(f"[_play_entry] Error: {e}")
                    embed = discord.Embed(
                        title="⚠️ Gangguan Pemutaran",
                        description=f"Lagu gagal diputar: {e}. Saya lanjutkan ke lagu berikutnya.",
                        color=0xff3333
                    )
                    await ctx.send(embed=embed)
                    handed_off = self.play_next(ctx)
        finally:
            if not handed_off:
                self.transitioning.discard(ctx.guild.id)

    def _after_play(self, ctx: commands.Context, error):
        """Callback setelah setiap lagu selesai."""
        if error:
            print(f"[after_play] Playback error: {error}")
            embed = discord.Embed(
                description=f"⚠️ Mohon maaf, {HONORIFIC}, terjadi kendala saat memutar: {error}",
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
    @commands.guild_only()
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            embed = discord.Embed(
                description=f"❌ Mohon maaf, {HONORIFIC}, **{ctx.author.display_name}** belum berada di voice channel.",
                color=0xff3333
            )
            return await ctx.send(embed=embed)
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        embed = discord.Embed(
            description=f"🟢 Dengan senang hati, {HONORIFIC}. Saya bergabung ke **{channel.name}**.",
            color=0x2ecc71
        )
        await ctx.send(embed=embed)

    @commands.command(name='play', help='Putar lagu / playlist dari YouTube, Spotify, SoundCloud, atau cari berdasarkan judul')
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, search: str):
        # Auto-join voice channel
        if not ctx.author.voice:
            embed = discord.Embed(
                description=f"❌ Mohon maaf, {HONORIFIC}, silakan masuk ke voice channel terlebih dahulu.",
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
                description=f"🔍 Tautan Spotify terdeteksi, {HONORIFIC}. Saya carikan padanannya di YouTube...",
                color=0x1DB954
            )
            await ctx.send(embed=embed)

        async with ctx.typing():
            try:
                resolved = await self._resolve_search(search)
                result = await YTDLSource.from_url(resolved, loop=self.bot.loop, stream=True, requester=ctx.author)
            except Exception as e:
                embed = discord.Embed(
                    description=f"❌ Mohon maaf, {HONORIFIC}, terjadi kendala: {e}",
                    color=0xff3333
                )
                return await ctx.send(embed=embed)

        queue = self.get_queue(ctx)

        # A result with a single entry is really a single track — re-extract it fully
        if isinstance(result, dict) and 'entries' in result:
            single_candidates = [e for e in result.get('entries', []) if e is not None]
            if len(single_candidates) == 1:
                single = single_candidates[0]
                single_url = single.get('webpage_url') or single.get('url') or f"https://www.youtube.com/watch?v={single.get('id')}"
                try:
                    result = await YTDLSource.from_url(single_url, loop=self.bot.loop, stream=True, requester=ctx.author)
                except Exception as e:
                    embed = discord.Embed(
                        description=f"❌ Mohon maaf, {HONORIFIC}, terjadi kendala: {e}",
                        color=0xff3333
                    )
                    return await ctx.send(embed=embed)

        # --- Playlist ---
        if isinstance(result, dict) and 'entries' in result:
            entries = [e for e in result.get('entries', []) if e is not None]
            if not entries:
                embed = discord.Embed(
                    description=f"❌ Mohon maaf, {HONORIFIC}, playlist ini kosong atau tidak ada lagu yang bisa diputar.",
                    color=0xff3333
                )
                return await ctx.send(embed=embed)

            if vc.is_playing() or vc.is_paused() or ctx.guild.id in self.transitioning:
                for e in entries:
                    url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                    queue.append(QueueEntry(url, e.get('title', url), ctx.author))
                
                first_entry = entries[0]
                first_title = first_entry.get('title', 'Unknown Track')
                first_url = first_entry.get('webpage_url') or first_entry.get('url') or f"https://www.youtube.com/watch?v={first_entry.get('id')}"
                metadata = self.extract_song_metadata(first_entry)
                
                embed = discord.Embed(
                    title="🎶 Playlist Masuk Antrian",
                    description=(
                        f"Dengan senang hati, {HONORIFIC}. **{len(entries)}** lagu dari playlist sudah masuk antrian."
                        f"\n\nLagu pertamanya: **[{first_title}]({first_url})**"
                    ),
                    color=0x2ecc71
                )
                thumbnail = first_entry.get('thumbnail') or result.get('thumbnail')
                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)
                
                embed.add_field(name="Artis", value=metadata['artist'], inline=True)
                embed.add_field(name="Album", value=metadata['album'], inline=True)
                embed.add_field(name="Durasi", value=metadata['duration'], inline=True)
                embed.add_field(name="Total Lagu", value=f"{len(entries)}", inline=True)
                embed.add_field(name="Posisi Antrian", value=f"#{len(queue) - len(entries) + 1} s/d #{len(queue)}", inline=True)
                embed.set_footer(text=f"Atas permintaan {ctx.author.name} • Total antrian: {len(queue)}", icon_url=ctx.author.display_avatar.url)
                return await ctx.send(embed=embed)

            # Play first, queue the rest
            first = entries[0]
            first_url = first.get('webpage_url') or first.get('url') or f"https://www.youtube.com/watch?v={first.get('id')}"
            for e in entries[1:]:
                url = e.get('webpage_url') or e.get('url') or f"https://www.youtube.com/watch?v={e.get('id')}"
                queue.append(QueueEntry(url, e.get('title', url), ctx.author))

            try:
                player = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True, requester=ctx.author)
                player.volume = self.get_volume(ctx.guild.id)
                vc.play(player, after=lambda e: self._after_play(ctx, e))
                
                # Update playing history
                self.get_history(ctx.guild.id).append(player.title)

                metadata = self.extract_song_metadata(player.data)
                embed = discord.Embed(
                    title="🎶 Sedang Diputar (Playlist)",
                    description=f"**[{player.title}]({player.webpage_url})**",
                    color=0x00E5FF
                )
                thumbnail = player.data.get('thumbnail')
                if thumbnail:
                    embed.set_thumbnail(url=thumbnail)
                
                embed.add_field(name="Artis", value=metadata['artist'], inline=True)
                embed.add_field(name="Album", value=metadata['album'], inline=True)
                embed.add_field(name="Uploader", value=metadata['uploader'], inline=True)
                embed.add_field(name="Durasi", value=metadata['duration'], inline=True)
                embed.add_field(name="Playlist", value=f"Sisa **{len(entries) - 1}** lagu sudah saya antrikan.", inline=False)
                
                embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
                await ctx.send(embed=embed)
            except Exception as e:
                embed = discord.Embed(
                    description=f"❌ Mohon maaf, {HONORIFIC}, playlist gagal dijalankan: {e}",
                    color=0xff3333
                )
                await ctx.send(embed=embed)

        # --- Single track ---
        else:
            if vc.is_playing() or vc.is_paused() or ctx.guild.id in self.transitioning:
                # For single tracks that are not yet "YTDLSource" objects (still just data/metadata)
                # result here is the YTDLSource object because YTDLSource.from_url was called above
                player = result 
                queued_title = player.title
                queued_url = player.webpage_url or search
                player.cleanup()
                queue.append(QueueEntry(queued_url, queued_title, ctx.author))
                embed = self.get_added_to_queue_embed(player, ctx.author, len(queue))
                await ctx.send(embed=embed)
            else:
                player = result
                player.volume = self.get_volume(ctx.guild.id)
                vc.play(player, after=lambda e: self._after_play(ctx, e))
                
                # Update playing history
                self.get_history(ctx.guild.id).append(player.title)

                embed = self.get_now_playing_embed(player, ctx.author)
                await ctx.send(embed=embed)

    @commands.command(name='pause', help='Pause lagu yang sedang diputar')
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            title = getattr(ctx.voice_client.source, 'title', None)
            embed = discord.Embed(
                description=f"⏸️ Playback saya jeda — **{title}**" if title else f"⏸️ Playback saya jeda, {HONORIFIC}.",
                color=0xf1c40f
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=f"❌ Belum ada lagu yang diputar, {HONORIFIC}. Silakan beri perintah `!j play`.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='resume', help='Lanjutkan lagu yang dijeda')
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            title = getattr(ctx.voice_client.source, 'title', None)
            embed = discord.Embed(
                description=f"▶️ Playback saya lanjutkan — **{title}**" if title else f"▶️ Playback saya lanjutkan, {HONORIFIC}.",
                color=0x2ecc71
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=f"❌ Tidak ada lagu yang sedang dijeda, {HONORIFIC}.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='skip', help='Lewati lagu yang sedang diputar')
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()  # triggers _after_play → play_next
            embed = discord.Embed(
                description=f"⏭️ Lagu dilewati, {HONORIFIC}.",
                color=0x00E5FF
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=f"❌ Belum ada lagu yang bisa saya lewati, {HONORIFIC}.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='stop', help='Stop dan bot keluar dari voice channel')
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client is None:
            embed = discord.Embed(
                description=f"❌ Saya belum berada di voice channel, {HONORIFIC}.",
                color=0xff3333
            )
            return await ctx.send(embed=embed)
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client:
            self._cancel_disconnect(ctx.guild.id)
            self.get_queue(ctx).clear()
            await ctx.voice_client.disconnect()
            embed = discord.Embed(
                description=f"⏹️ Sudah saya laksanakan: saya keluar dan antrian dibersihkan, {HONORIFIC}.",
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=f"❌ Saya belum berada di voice channel, {HONORIFIC}.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='queue', help='Tampilkan antrian lagu saat ini')
    @commands.guild_only()
    async def queue(self, ctx: commands.Context):
        q = self.get_queue(ctx)
        vc = ctx.voice_client
        
        embed = discord.Embed(title="📋 Daftar Antrian", color=0x00E5FF)
        
        # Now playing
        if vc and (vc.is_playing() or vc.is_paused()) and hasattr(vc.source, 'title'):
            embed.description = f"**Sedang Diputar:**\n🎶 **{vc.source.title}**\n\n"
        else:
            embed.description = f"**Sedang Diputar:**\n💤 Belum ada lagu yang diputar.\n\n"
            
        # Up next
        if not q:
            embed.description += f"**Berikutnya:**\n📭 Antrian masih kosong, {HONORIFIC}."
        else:
            lines = []
            for i, entry in enumerate(q, 1):
                req_str = f" (atas permintaan {entry.requester.mention})" if entry.requester else ""
                lines.append(f"`{i}.` {entry.title}{req_str}")
            
            queue_text = "\n".join(lines[:15])
            if len(q) > 15:
                queue_text += f"\n... dan **{len(q) - 15}** lagu lainnya."
            
            embed.description += f"**Berikutnya:**\n{queue_text}"
            
        embed.set_footer(text=f"Total antrian: {len(q)} lagu", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='nowplaying', aliases=['np'], help='Tampilkan lagu yang sedang diputar')
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context):
        vc = ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()) and hasattr(vc.source, 'title'):
            requester = getattr(vc.source, 'requester', None) or ctx.author
            embed = self.get_now_playing_embed(vc.source, requester)
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=f"❌ Belum ada lagu yang diputar, {HONORIFIC}. Silakan beri perintah `!j play`.",
                color=0xff3333
            )
            await ctx.send(embed=embed)

    @commands.command(name='playinghistory', aliases=['ph'], help='Tampilkan history lagu yang sudah diputar')
    @commands.guild_only()
    async def playing_history(self, ctx: commands.Context):
        history = self.get_history(ctx.guild.id)
        if not history:
            embed = discord.Embed(
                description=f"📭 Belum ada lagu yang saya putar, {HONORIFIC}.",
                color=0x00E5FF
            )
            return await ctx.send(embed=embed)

        lines = [f"`{i}.` {title}" for i, title in enumerate(reversed(history), 1)]
        embed = discord.Embed(
            title="📜 Riwayat Pemutaran",
            description="\n".join(lines[:15]),
            color=0x00E5FF
        )
        if len(history) > 15:
            embed.description += f"\n... dan **{len(history) - 15}** lagu lainnya."
            
        embed.set_footer(text=f"Total riwayat: {len(history)} lagu", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='volume', help='Atur volume (0-100)')
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, vol: int):
        if not await self._same_voice(ctx):
            return
        if not (0 <= vol <= 100):
            embed = discord.Embed(
                description=f"❌ Mohon maaf, {HONORIFIC}, volume harus berada di antara 0 dan 100.",
                color=0xff3333
            )
            return await ctx.send(embed=embed)

        self.guild_volumes[ctx.guild.id] = vol / 100

        vc = ctx.voice_client
        if vc and hasattr(vc.source, 'volume'):
            vc.source.volume = vol / 100

        embed = discord.Embed(
            description=f"🔊 Volume sudah saya sesuaikan ke **{vol}%**, {HONORIFIC}.",
            color=0x00E5FF
        )
        await ctx.send(embed=embed)

    @commands.command(name='clearqueue', aliases=['cq'], help='Hapus semua lagu dalam antrian')
    @commands.guild_only()
    async def clearqueue(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        self.get_queue(ctx).clear()
        embed = discord.Embed(
            description=f"🗑️ Antrian sudah saya kosongkan, {HONORIFIC}.",
            color=0xe74c3c
        )
        await ctx.send(embed=embed)

    @commands.command(name='remove', help='Hapus lagu tertentu dari antrian berdasarkan nomor')
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, index: int):
        if not await self._same_voice(ctx):
            return
        q = self.get_queue(ctx)
        if 1 <= index <= len(q):
            removed = q[index - 1]
            del q[index - 1]
            embed = discord.Embed(
                description=f"🗑️ Sudah saya hapus dari antrian: {removed.title}",
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                description=f"❌ Mohon maaf, {HONORIFIC}, nomor lagu itu tidak ada dalam antrian.",
                color=0xff3333
            )
            await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
    