import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import datetime
 
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
        self.start_time = datetime.datetime.now(datetime.timezone.utc)
 
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
        # Load opus library dari folder lib
        if not discord.opus.is_loaded():
            try:
                discord.opus.load_opus('./lib/libopus.dll')
                print("[Jarvis] Opus library loaded successfully from ./lib/libopus.dll")
            except Exception as e:
                print(f"[Jarvis] Gagal load Opus: {e}")

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
        now = __import__('datetime').datetime.now().strftime('%H:%M')
        embed = discord.Embed(
            title="",
            description=(
                f"### 🤖 Jarvis — Personal AI Assistant\n"
                f"Siap melayani, **{ctx.author.display_name}**. Pukul {now} — ada yang bisa saya bantu?"
            ),
            color=0x00E5FF,
        )
        if self.user:
            embed.set_author(name="Jarvis Bot", icon_url=self.user.display_avatar.url)
            embed.set_thumbnail(url=self.user.display_avatar.url)

        embed.add_field(
            name="🎵 Musik",
            value=(
                "`!jarvis play <judul/link>` — Putar musik.\n"
                "`!jarvis join` — Masuk ke voice channel kamu\n"
                "`!jarvis stop` — Stop dan keluar dari voice\n"
                "`!jarvis skip` — Lewati lagu sekarang\n"
                "`!jarvis pause` / `!jarvis resume` — Kontrol playback\n"
                "`!jarvis queue` — Lihat antrian lagu\n"
                "`!jarvis np` — Lagu yang sedang diputar\n"
                "`!jarvis ph` — Tampilkan playing history\n"
                "`!jarvis volume <0-100>` — Atur volume\n"
                "`!jarvis clear` — Hapus semua antrian\n"
                "`!jarvis remove <nomor antrian>` — Hapus lagu dari antrian\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="🤖 AI & Asisten",
            value=(
                "`!jarvis ask <pertanyaan>` — Tanya ke AI\n"
                "`!jarvis summarize <pdf>` — Ringkas file pdf\n"
                "`!jarvis search <query>` — Cari di web\n"
                "`!jarvis image <deskripsi>` — Buat gambar AI\n"
                "`!jarvis model` — Lihat daftar model AI yang tersedia\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="🛠️ Utilitas",
            value=(
                "`!jarvis ping` — Cek latensi bot\n"
                "`!jarvis info` — Lihat info bot\n"
                "`!jarvis help` — Tampilkan menu bantuan\n"
                "`!jarvis invite` — Dapatkan link invite bot\n"
                "`!jarvis uptime` — Lihat berapa lama bot sudah online\n"
                "`!jarvis stats` — Statistik penggunaan bot\n"
                "`!jarvis userinfo <@user>` — Lihat informasi user\n"
                "`!jarvis serverinfo` — Lihat informasi server\n"
                "`!jarvis cogs` — Lihat cogs yang aktif\n"
            ),
            inline=False,
        )

        embed.set_footer(
            text=f"Jarvis v2.0  •  Powered by Groq LPU  •  {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url
        )
        await ctx.send(embed=embed)

    async def on_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.CommandNotFound):
            return  # Abaikan perintah yang tidak dikenal
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="❌ Argumen Kurang",
                description=f"Parameter **`{error.param.name}`** diperlukan. > Ketik `!jarvis` untuk melihat daftar perintah.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return
        if isinstance(error, commands.BadArgument):
            embed = discord.Embed(
                title="❌ Format Tidak Valid",
                description="Argumen yang diberikan tidak sesuai format. > Ketik `!jarvis` untuk melihat contoh penggunaan.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return

        # Log error teknis tanpa expose detail ke user
        print(f"[Error] Command '{ctx.command}': {error}")
        embed = discord.Embed(
            title="⚠️ Terjadi Kesalahan",
            description="Sesuatu berjalan tidak semestinya, Boss. Silakan coba lagi.",
            color=0xf1c40f
        )
        await ctx.send(embed=embed)

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
async def main():
    if not TOKEN:
        print("[Error] DISCORD_TOKEN tidak ditemukan di file .env")
        return
    
    keep_alive()
 
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
        print("[Jarvis] Bot dihentikan oleh author.")
