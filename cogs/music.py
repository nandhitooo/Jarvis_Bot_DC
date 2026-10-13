"""Music cog: voice playback, queue management, and playback history."""

import asyncio
import re
import threading
from collections import deque

import discord
import requests
import yt_dlp
from bs4 import BeautifulSoup
from discord.ext import commands

from config import HONORIFIC
from helpers import COLOR_DANGER, COLOR_INFO, COLOR_OK, err, info, ok, warn


def _entry_url(entry: dict) -> str:
    """Return the best playable URL for a yt-dlp entry dict."""
    return entry.get('webpage_url') or entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"


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
            await ctx.send(embed=err(
                "❌ Kamu harus ada di voice channel yang sama dengan saya."
            ))
            return False
        return True

    async def _auto_disconnect(self, ctx: commands.Context):
        await asyncio.sleep(300)  # 5 minutes
        vc = ctx.voice_client
        if vc and not vc.is_playing() and not vc.is_paused() and not self.get_queue(ctx):
            await vc.disconnect()
            await ctx.send(embed=warn(
                f"💤 Sudah 5 menit sepi, saya keluar dulu ya, {HONORIFIC}."
            ))
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
            raise Exception("Metadata dari tautan Spotify-nya tidak bisa saya ambil.")
        print(f"[Spotify] Resolved to: {metadata}")
        return f"ytsearch:{metadata}"

    def get_now_playing_embed(self, player, author):
        metadata = self.extract_song_metadata(player.data)
        embed = discord.Embed(
            title="🎶 Sedang Diputar",
            description=f"**[{player.title}]({player.webpage_url})**",
            color=COLOR_INFO
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
            color=COLOR_OK
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
        await ctx.send(embed=info(
            "🎵 Antrian habis. Sunyi sekali di sini, kabari saya kalau mau putar lagi."
        ))

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

    async def _start_player(self, ctx: commands.Context, vc: discord.VoiceClient, player: YTDLSource, requester: discord.Member | None) -> None:
        """Apply the guild volume, start playback, record history, and announce now playing."""
        player.volume = self.get_volume(ctx.guild.id)
        vc.play(player, after=lambda e: self._after_play(ctx, e))

        # Update playing history
        self.get_history(ctx.guild.id).append(player.title)

        embed = self.get_now_playing_embed(player, requester)
        await ctx.send(embed=embed)

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
                            await ctx.send(embed=err(
                                "❌ Tidak ada lagu yang bisa diputar."
                            ))
                            handed_off = self.play_next(ctx)
                            return

                        # Enqueue the rest at the front of the queue
                        queue = self.get_queue(ctx)
                        for e in reversed(entries[1:]):
                            url = _entry_url(e)
                            queue.appendleft(QueueEntry(url, e.get('title', url), entry.requester))

                        # Play the first entry
                        first = entries[0]
                        first_url = _entry_url(first)
                        player = await YTDLSource.from_url(first_url, loop=self.bot.loop, stream=True, requester=entry.requester)

                        if vc.is_playing():
                            # Audio masih berjalan — kembalikan ke antrian agar tidak ada lagu yang hilang
                            queue.appendleft(QueueEntry(first_url, first.get('title', first_url), entry.requester))
                            player.cleanup()
                            return
                        await self._start_player(ctx, vc, player, entry.requester or ctx.author)
                    else:
                        player = result

                        if vc.is_playing():
                            # Audio masih berjalan — kembalikan ke antrian agar tidak ada lagu yang hilang
                            self.get_queue(ctx).appendleft(entry)
                            player.cleanup()
                            return
                        await self._start_player(ctx, vc, player, entry.requester or ctx.author)

                except Exception as e:
                    print(f"[_play_entry] Error: {e}")
                    await ctx.send(embed=err(
                        f"Maaf, lagunya gagal diputar: {e}. Saya lanjut ke lagu berikutnya, {HONORIFIC}.",
                        title="⚠️ Gangguan Pemutaran"
                    ))
                    handed_off = self.play_next(ctx)
        finally:
            if not handed_off:
                self.transitioning.discard(ctx.guild.id)

    def _after_play(self, ctx: commands.Context, error):
        """Callback setelah setiap lagu selesai."""
        if error:
            print(f"[after_play] Playback error: {error}")
            embed = warn(
                f"⚠️ Maaf, ada gangguan saat memutar: {error}"
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
            return await ctx.send(embed=err(
                f"❌ **{ctx.author.display_name}** belum masuk voice channel."
            ))
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(embed=ok(
            f"🟢 Siap, {HONORIFIC}. Gabung ke **{channel.name}**."
        ))

    async def _join_author_channel(self, ctx: commands.Context) -> bool:
        """Auto-join the author's voice channel, sending an error and returning False on failure."""
        if not ctx.author.voice:
            await ctx.send(embed=err(
                "❌ Masuk ke voice channel dulu ya."
            ))
            return False
        if ctx.voice_client is None:
            await ctx.author.voice.channel.connect()
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        return True

    @commands.command(name='play', help='Putar lagu / playlist dari YouTube, Spotify, SoundCloud, atau cari berdasarkan judul')
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, search: str):
        if not await self._join_author_channel(ctx):
            return

        vc = ctx.voice_client

        # Notify for Spotify early
        if 'spotify.com' in search:
            embed = discord.Embed(
                description=f"🔍 Spotify terdeteksi, {HONORIFIC}. Saya cari padanannya di YouTube...",
                color=0x1DB954
            )
            await ctx.send(embed=embed)

        async with ctx.typing():
            try:
                resolved = await self._resolve_search(search)
                result = await YTDLSource.from_url(resolved, loop=self.bot.loop, stream=True, requester=ctx.author)
            except Exception as e:
                return await ctx.send(embed=err(f"❌ Maaf, lagunya gagal diputar: {e}"))

        queue = self.get_queue(ctx)

        # A result with a single entry is really a single track — re-extract it fully
        if isinstance(result, dict) and 'entries' in result:
            single_candidates = [e for e in result.get('entries', []) if e is not None]
            if len(single_candidates) == 1:
                single = single_candidates[0]
                single_url = _entry_url(single)
                try:
                    result = await YTDLSource.from_url(single_url, loop=self.bot.loop, stream=True, requester=ctx.author)
                except Exception as e:
                    return await ctx.send(embed=err(f"❌ Maaf, lagunya gagal diputar: {e}"))

        # --- Playlist ---
        if isinstance(result, dict) and 'entries' in result:
            entries = [e for e in result.get('entries', []) if e is not None]
            await self._handle_playlist(ctx, vc, queue, entries, result.get('thumbnail'))
        # --- Single track ---
        else:
            await self._handle_single(ctx, vc, queue, result, search)

    async def _handle_playlist(self, ctx: commands.Context, vc: discord.VoiceClient, queue: deque[QueueEntry], entries: list[dict], playlist_thumbnail: str | None = None) -> None:
        """Queue a playlist or start its first track, preserving the existing messages."""
        if not entries:
            return await ctx.send(embed=err(
                f"❌ Playlist-nya kosong atau tidak ada lagu yang bisa diputar, {HONORIFIC}."
            ))

        if vc.is_playing() or vc.is_paused() or ctx.guild.id in self.transitioning:
            for e in entries:
                url = _entry_url(e)
                queue.append(QueueEntry(url, e.get('title', url), ctx.author))

            first_entry = entries[0]
            first_title = first_entry.get('title', 'Unknown Track')
            first_url = _entry_url(first_entry)
            metadata = self.extract_song_metadata(first_entry)

            embed = discord.Embed(
                title="🎶 Playlist Masuk Antrian",
                description=(
                    f"**{len(entries)}** lagu dari playlist sudah masuk antrian, {HONORIFIC}."
                    f"\n\nPertama: **[{first_title}]({first_url})**"
                ),
                color=COLOR_OK
            )
            thumbnail = first_entry.get('thumbnail') or playlist_thumbnail
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
        first_url = _entry_url(first)
        for e in entries[1:]:
            url = _entry_url(e)
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
                color=COLOR_INFO
            )
            thumbnail = player.data.get('thumbnail')
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)

            embed.add_field(name="Artis", value=metadata['artist'], inline=True)
            embed.add_field(name="Album", value=metadata['album'], inline=True)
            embed.add_field(name="Uploader", value=metadata['uploader'], inline=True)
            embed.add_field(name="Durasi", value=metadata['duration'], inline=True)
            embed.add_field(name="Playlist", value=f"Sisa **{len(entries) - 1}** lagu sudah antri.", inline=False)

            embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=err(
                f"❌ Maaf, playlist-nya gagal dijalankan, {HONORIFIC}: {e}"
            ))

    async def _handle_single(self, ctx: commands.Context, vc: discord.VoiceClient, queue: deque[QueueEntry], player: YTDLSource, search: str) -> None:
        """Queue or start a single track, preserving the existing messages."""
        if vc.is_playing() or vc.is_paused() or ctx.guild.id in self.transitioning:
            # For single tracks that are not yet "YTDLSource" objects (still just data/metadata)
            # result here is the YTDLSource object because YTDLSource.from_url was called above
            queued_title = player.title
            queued_url = player.webpage_url or search
            player.cleanup()
            queue.append(QueueEntry(queued_url, queued_title, ctx.author))
            embed = self.get_added_to_queue_embed(player, ctx.author, len(queue))
            await ctx.send(embed=embed)
        else:
            await self._start_player(ctx, vc, player, ctx.author)

    @commands.command(name='pause', help='Pause lagu yang sedang diputar')
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            title = getattr(ctx.voice_client.source, 'title', None)
            await ctx.send(embed=warn(
                f"⏸️ Lagu dijeda — **{title}**" if title else f"⏸️ Lagu dijeda, {HONORIFIC}."
            ))
        else:
            await ctx.send(embed=err(
                "❌ Belum ada lagu yang diputar. Coba `!j play` dulu."
            ))

    @commands.command(name='resume', help='Lanjutkan lagu yang dijeda')
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            title = getattr(ctx.voice_client.source, 'title', None)
            await ctx.send(embed=ok(
                f"▶️ Lagu dilanjutkan — **{title}**" if title else f"▶️ Lagu dilanjutkan, {HONORIFIC}."
            ))
        else:
            await ctx.send(embed=err(
                "❌ Tidak ada lagu yang sedang dijeda."
            ))

    @commands.command(name='skip', help='Lewati lagu yang sedang diputar')
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()  # triggers _after_play → play_next
            await ctx.send(embed=info(
                "⏭️ Lagu dilewati."
            ))
        else:
            await ctx.send(embed=err(
                "❌ Belum ada lagu yang bisa dilewati."
            ))

    @commands.command(name='stop', help='Stop dan bot keluar dari voice channel')
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        if ctx.voice_client is None:
            return await ctx.send(embed=err(
                "❌ Saya belum masuk voice channel."
            ))
        if not await self._same_voice(ctx):
            return
        if ctx.voice_client:
            self._cancel_disconnect(ctx.guild.id)
            self.get_queue(ctx).clear()
            await ctx.voice_client.disconnect()
            embed = discord.Embed(
                description="⏹️ Oke, saya keluar dan antrian sudah dibersihkan.",
                color=COLOR_DANGER
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=err(
                "❌ Saya belum masuk voice channel."
            ))

    @commands.command(name='queue', help='Tampilkan antrian lagu saat ini')
    @commands.guild_only()
    async def queue(self, ctx: commands.Context):
        q = self.get_queue(ctx)
        vc = ctx.voice_client
        
        embed = discord.Embed(title="📋 Daftar Antrian", color=COLOR_INFO)
        
        # Now playing
        if vc and (vc.is_playing() or vc.is_paused()) and hasattr(vc.source, 'title'):
            embed.description = f"**Sedang Diputar:**\n🎶 **{vc.source.title}**\n\n"
        else:
            embed.description = "**Sedang Diputar:**\n💤 Belum ada lagu yang diputar.\n\n"
            
        # Up next
        if not q:
            embed.description += "**Berikutnya:**\n📭 Antrian masih kosong."
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
            await ctx.send(embed=err(
                "❌ Belum ada lagu yang diputar. Coba `!j play` dulu."
            ))

    @commands.command(name='playinghistory', aliases=['ph'], help='Tampilkan history lagu yang sudah diputar')
    @commands.guild_only()
    async def playing_history(self, ctx: commands.Context):
        history = self.get_history(ctx.guild.id)
        if not history:
            return await ctx.send(embed=info(
                "📭 Belum ada lagu yang pernah diputar."
            ))

        lines = [f"`{i}.` {title}" for i, title in enumerate(reversed(history), 1)]
        embed = discord.Embed(
            title="📜 Riwayat Pemutaran",
            description="\n".join(lines[:15]),
            color=COLOR_INFO
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
            return await ctx.send(embed=err(
                "❌ Volume harus di antara 0 dan 100."
            ))

        self.guild_volumes[ctx.guild.id] = vol / 100

        vc = ctx.voice_client
        if vc and hasattr(vc.source, 'volume'):
            vc.source.volume = vol / 100

        await ctx.send(embed=info(
            f"🔊 Volume diatur ke **{vol}%**, {HONORIFIC}."
        ))

    @commands.command(name='clearqueue', aliases=['cq'], help='Hapus semua lagu dalam antrian')
    @commands.guild_only()
    async def clearqueue(self, ctx: commands.Context):
        if not await self._same_voice(ctx):
            return
        self.get_queue(ctx).clear()
        embed = discord.Embed(
            description=f"🗑️ Antrian sudah dikosongkan, {HONORIFIC}.",
            color=COLOR_DANGER
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
                description=f"🗑️ Dihapus dari antrian, {HONORIFIC}: {removed.title}",
                color=COLOR_DANGER
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=err(
                "❌ Nomor lagu itu tidak ada di antrian."
            ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
    