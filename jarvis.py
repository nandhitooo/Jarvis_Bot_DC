import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from config import HONORIFIC, TIMEZONE

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
                opus_path = './lib/libopus.dll' if os.name == 'nt' else 'libopus.so.0'
                discord.opus.load_opus(opus_path)
                print(f"[Jarvis] Opus library loaded successfully from {opus_path}")
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
        if message.author.bot:
            return
 
        # Tampilkan menu jika hanya mengetik "!jarvis" atau "!j" tanpa sub-command
        if message.content.lower().strip() in ["!jarvis", "!j"]:
            ctx = await self.get_context(message)
            await self._send_help_menu(ctx)
            return
 
        await self.process_commands(message)
 
    async def _send_help_menu(self, ctx: commands.Context):
        view = HelpView(ctx, self)
        await view.send_initial_help()

    async def on_command_error(self, ctx: commands.Context, error):
        if ctx.command and ctx.command.has_error_handler():
            return
        if ctx.cog and ctx.cog.has_error_handler():
            return
        if isinstance(error, commands.CommandNotFound):
            return  # Abaikan perintah yang tidak dikenal
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="❌ Argumen Kurang",
                description=f"Mohon maaf, {HONORIFIC}, parameter **`{error.param.name}`** masih dibutuhkan. Ketik `!jarvis` untuk melihat daftar perintah.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return
        if isinstance(error, commands.BadArgument):
            embed = discord.Embed(
                title="❌ Format Tidak Valid",
                description=f"Mohon maaf, {HONORIFIC}, argumen yang diberikan tidak sesuai format. Ketik `!jarvis` untuk melihat contoh penggunaan.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return
        if isinstance(error, commands.CommandOnCooldown):
            embed = discord.Embed(
                title="⏳ Tunggu Sebentar",
                description=f"Mohon bersabar, {HONORIFIC} — tunggu {error.retry_after:.0f} detik.",
                color=0xf1c40f
            )
            await ctx.send(embed=embed)
            return
        if isinstance(error, commands.NoPrivateMessage):
            embed = discord.Embed(
                title="❌ Hanya di Server",
                description="Perintah ini hanya dapat dijalankan di dalam server.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return

        if isinstance(error, (commands.NotOwner, commands.CheckFailure)):
            embed = discord.Embed(
                title="❌ Akses Ditolak",
                description=f"Mohon maaf, {HONORIFIC}, Anda tidak memiliki izin untuk perintah ini.",
                color=0xff3333
            )
            await ctx.send(embed=embed)
            return

        # Log error teknis tanpa expose detail ke user
        if isinstance(error, commands.CommandInvokeError):
            print(f"[Error] Command '{ctx.command}': {error.original}")
        else:
            print(f"[Error] Command '{ctx.command}': {error}")
        embed = discord.Embed(
            title="⚠️ Terjadi Kesalahan",
            description=f"Ada yang berjalan tidak semestinya, {HONORIFIC}. Silakan coba lagi.",
            color=0xf1c40f
        )
        await ctx.send(embed=embed)

class HelpView(discord.ui.View):
    def __init__(self, ctx: commands.Context, bot: commands.Bot):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.bot = bot
        self.current_category = "Main"

    async def send_initial_help(self):
        embed = self._get_main_embed()
        self.message = await self.ctx.send(embed=embed, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass

    def _get_main_embed(self):
        try:
            now = datetime.datetime.now(ZoneInfo(TIMEZONE)).strftime('%H:%M')
        except ZoneInfoNotFoundError:
            now = datetime.datetime.now().strftime('%H:%M')
        embed = discord.Embed(
            title="",
            description=(
                f"### 🤖 Jarvis — Asisten AI Pribadi\n"
                f"Dengan senang hati, **{self.ctx.author.display_name}**. Sekarang pukul {now} — ada yang bisa saya bantu?\n\n"
                f"Silakan pilih kategori di bawah ini, {HONORIFIC}."
            ),
            color=0x00E5FF,
        )
        if self.bot.user:
            embed.set_author(name="Jarvis Bot", icon_url=self.bot.user.display_avatar.url)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        embed.add_field(name="🎵 Musik", value="Kontrol pemutaran & antrian lagu", inline=True)
        embed.add_field(name="🤖 AI & Asisten", value="Tanya AI, ringkas PDF, pencarian", inline=True)
        embed.add_field(name="⚙️ Moderator", value="Kelola anggota & channel", inline=True)
        embed.add_field(name="🛠️ Utilitas", value="Info bot, statistik, waktu aktif", inline=True)
        
        embed.set_footer(
            text="Jarvis v2.5  •  Silakan pilih menu di bawah",
            icon_url=self.ctx.author.display_avatar.url
        )
        return embed

    @discord.ui.select(
        placeholder="Silakan pilih kategori perintah...",
        options=[
            discord.SelectOption(label="Menu Utama", value="Main", emoji="🏠", description="Kembali ke halaman utama"),
            discord.SelectOption(label="Musik", value="Music", emoji="🎵", description="Perintah pemutaran musik"),
            discord.SelectOption(label="AI & Asisten", value="AI", emoji="🤖", description="Fitur kecerdasan buatan"),
            discord.SelectOption(label="Moderator", value="Mod", emoji="⚙️", description="Perintah moderasi server"),
            discord.SelectOption(label="Utilitas", value="Util", emoji="🛠️", description="Informasi dan alat bantu"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message(f"Mohon maaf, hanya pemanggil menu ini yang dapat menggunakannya, {HONORIFIC}.", ephemeral=True)
        
        self.current_category = select.values[0]
        embed = None
        
        if self.current_category == "Main":
            embed = self._get_main_embed()
        elif self.current_category == "Music":
            embed = self._get_music_embed()
        elif self.current_category == "AI":
            embed = self._get_ai_embed()
        elif self.current_category == "Mod":
            embed = self._get_mod_embed()
        elif self.current_category == "Util":
            embed = self._get_util_embed()
            
        await interaction.response.edit_message(embed=embed, view=self)

    def _get_music_embed(self):
        embed = discord.Embed(title="🎵 Menu Musik", color=0x00E5FF)
        embed.add_field(
            name="Kontrol Dasar",
            value=(
                "`!j join` — Bergabung ke voice channel\n"
                "`!j play <tautan/judul>` — Putar lagu\n"
                "`!j stop` — Berhenti & keluar\n"
                "`!j pause` / `!j resume` — Jeda/Lanjut\n"
                "`!j skip` — Lewati lagu\n"
            ), inline=False
        )
        embed.add_field(
            name="Antrian & Info",
            value=(
                "`!j queue` — Lihat daftar putar\n"
                "`!j np` — Lagu yang sedang diputar\n"
                "`!j ph` — Riwayat pemutaran\n"
                "`!j clearqueue` (alias `cq`) — Hapus antrian\n"
                "`!j remove <no>` — Hapus lagu tertentu\n"
                "`!j volume <0-100>` — Atur volume\n"
            ), inline=False
        )
        return embed

    def _get_ai_embed(self):
        embed = discord.Embed(title="🤖 AI & Asisten", color=0x00E5FF)
        embed.add_field(
            name="Kecerdasan Buatan",
            value=(
                "`!j ask <tanya>` — Bercakap dengan Jarvis\n"
                "`!j search <query>` — Cari informasi\n"
                "`!j image <deskripsi>` — Generate gambar AI\n"
                "`!j summarize <pdf>` — Ringkas dokumen\n"
            ), inline=False
        )
        embed.add_field(
            name="Asisten Pribadi",
            value=(
                "`!j remind <waktu> <tugas>` — Setel pengingat\n"
                "`!j timer <waktu>` — Setel timer\n"
                "`!j weather <kota>` — Cek cuaca\n"
                "`!j calc <ekspresi>` — Kalkulator matematika\n"
                "`!j sysinfo` — Cek status sistem host\n"
                "`!j model` — Lihat model yang aktif\n"
            ), inline=False
        )
        return embed

    def _get_mod_embed(self):
        embed = discord.Embed(title="⚙️ Menu Moderator", color=0x00E5FF)
        embed.add_field(
            name="Sanksi",
            value=(
                "`!j kick <user>` | `!j ban <user>`\n"
                "`!j timeout <user> <menit>`\n"
                "`!j warn <user>` | `!j warnings <user>`\n"
            ), inline=True
        )
        embed.add_field(
            name="Channel",
            value=(
                "`!j clear <jumlah>` — Hapus pesan\n"
                "`!j lock` / `!j unlock` — Kunci channel\n"
                "`!j slowmode <detik>` — Set slowmode\n"
            ), inline=True
        )
        return embed

    def _get_util_embed(self):
        embed = discord.Embed(title="🛠️ Menu Utilitas", color=0x00E5FF)
        embed.add_field(
            name="Bot Info",
            value=(
                "`!j ping` — Cek latensi\n"
                "`!j uptime` — Waktu aktif\n"
                "`!j stats` — Statistik bot\n"
                "`!j info` — Tentang Jarvis\n"
            ), inline=True
        )
        embed.add_field(
            name="Server & User",
            value=(
                "`!j userinfo <user>`\n"
                "`!j serverinfo` — Info server\n"
                "`!j invite` — Link invite\n"
            ), inline=True
        )
        return embed

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
