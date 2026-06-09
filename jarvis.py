import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
 
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
 
 
class Jarvis(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=['!jarvis ', '!j ', '!jarvis', '!j'],
            intents=intents,
            case_insensitive=True,
            help_command=None,
        )
 
    async def setup_hook(self):
        cogs_dir = './cogs'
        if not os.path.isdir(cogs_dir):
            print(f"[Jarvis] Folder '{cogs_dir}' tidak ditemukan, melewati load cogs.")
            return
 
        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py'):
                ext = f'cogs.{filename[:-3]}'
                try:
                    await self.load_extension(ext)
                    print(f"[Jarvis] Loaded: {ext}")
                except Exception as e:
                    print(f"[Jarvis] Gagal load {ext}: {e}")
 
    async def on_ready(self):
        print(f"[Jarvis] {self.user} siap! ({self.user.id})")
        print(f"[Jarvis] Cogs aktif: {list(self.cogs.keys()) or 'Tidak ada'}")
 
        if not discord.opus.is_loaded():
            print("[Jarvis] Peringatan: Opus library belum dimuat. Fitur voice mungkin tidak berfungsi.")
 
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="!jarvis"
            )
        )
 
    async def on_message(self, message: discord.Message):
        if message.author == self.user:
            return
 
        # Tampilkan menu jika hanya mengetik "!jarvis" atau "!j" tanpa sub-command
        if message.content.lower().strip() in ["!jarvis", "!j"]:
            ctx = await self.get_context(message)
            await self._send_help_menu(ctx)
            return
 
        await self.process_commands(message)
 
    async def _send_help_menu(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🤖 Jarvis — Command Menu",
            description="Siap melayani, Boss! Berikut perintah yang tersedia:",
            color=discord.Color.blue(),
        )
 
        embed.add_field(
            name="🎵 Musik",
            value=(
                "`!jarvis play <judul/link>` — Putar dari YT, Spotify, dll.\n"
                "`!jarvis join` — Masuk ke voice channel kamu\n"
                "`!jarvis stop` — Stop dan keluar dari voice\n"
                "`!jarvis skip` — Lewati lagu sekarang\n"
                "`!jarvis pause` / `!jarvis resume` — Kontrol playback\n"
                "`!jarvis queue` — Lihat antrian lagu\n"
                "`!jarvis np` — Lagu yang sedang diputar\n"
                "`!jarvis volume <0-100>` — Atur volume\n"
                "`!jarvis clear` — Hapus semua antrian\n"
                "`!jarvis remove <nomor>` — Hapus lagu dari antrian"
            ),
            inline=False,
        )
 
        embed.add_field(
            name="🛠️ Utilitas",
            value=(
                "`!jarvis ping` — Cek latensi bot\n"
                "`!jarvis cogs` — Lihat cogs yang aktif"
            ),
            inline=False,
        )
 
        embed.set_footer(text="Still in development... Stay tuned for more features!")
        await ctx.send(embed=embed)
 
    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandNotFound):
            return  # Abaikan perintah yang tidak dikenal
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumen kurang: `{error.param.name}`. Ketik `!jarvis` untuk melihat bantuan.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumen tidak valid. Ketik `!jarvis` untuk melihat bantuan.")
            return
 
        # Log error teknis tanpa expose detail ke user
        print(f"[Error] Command '{ctx.command}': {error}")
        await ctx.send("⚠️ Terjadi kesalahan. Silakan coba lagi.")
 
    async def close(self):
        """Graceful shutdown: disconnect semua voice client."""
        print("[Jarvis] Mematikan bot...")
        for vc in self.voice_clients:
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
        await super().close()
 
 
bot = Jarvis()
 
 
@bot.command(name='cogs', help='Tampilkan cogs yang sedang aktif')
async def list_cogs(ctx: commands.Context):
    loaded = ', '.join(bot.cogs.keys()) if bot.cogs else 'Tidak ada'
    await ctx.send(f"📦 Cogs aktif: **{loaded}**")
 
 
@bot.command(name='ping', help='Cek latensi bot')
async def ping(ctx: commands.Context):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latensi: **{latency}ms**")
 
 
async def main():
    if not TOKEN:
        print("[Error] DISCORD_TOKEN tidak ditemukan di file .env")
        return
 
    async with bot:
        try:
            await bot.start(TOKEN)
        except discord.LoginFailure:
            print("[Error] Token Discord tidak valid. Periksa file .env kamu.")
        except Exception as e:
            print(f"[Error] Bot crash: {e}")
 
 
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[Jarvis] Bot dihentikan oleh user.")
