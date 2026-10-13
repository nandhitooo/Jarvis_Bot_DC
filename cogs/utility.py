"""Utility cog: bot info, latency, uptime, and server/user details."""

import datetime
import time

import discord
from discord.ext import commands

from helpers import COLOR_DANGER, COLOR_INFO, COLOR_OK, COLOR_WARN


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='ping', help='Cek latensi bot')
    async def ping(self, ctx: commands.Context):
        ws_latency = round(self.bot.latency * 1000)

        start = time.perf_counter()
        msg = await ctx.send("🏓 Mengukur latensi...")
        roundtrip = round((time.perf_counter() - start) * 1000)

        if roundtrip < 100:
            color = COLOR_OK   # hijau
            status = "🟢 Sangat baik"
        elif roundtrip < 200:
            color = COLOR_WARN   # kuning
            status = "🟡 Baik"
        elif roundtrip < 400:
            color = 0xe67e22   # oranye
            status = "🟠 Sedang"
        else:
            color = COLOR_DANGER   # merah
            status = "🔴 Lambat"

        embed = discord.Embed(title="🏓 Semua sistem responsif", color=color)
        embed.add_field(name="📡 WebSocket",  value=f"`{ws_latency}ms`",  inline=True)
        embed.add_field(name="↩️ Round-trip", value=f"`{roundtrip}ms`",   inline=True)
        embed.add_field(name="📊 Status",     value=status,               inline=True)
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)

        await msg.edit(content=None, embed=embed)

    @commands.command(name='cogs', help='Tampilkan cogs yang sedang aktif')
    async def list_cogs(self, ctx: commands.Context):
        loaded = ', '.join(self.bot.cogs.keys()) if self.bot.cogs else 'Belum ada'
        embed = discord.Embed(
            title="📦 Modul Aktif (Cogs)",
            description=f"**{loaded}**",
            color=COLOR_INFO
        )
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='info', help='Lihat info bot')
    async def info(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🤖 Jarvis Bot",
            description="Asisten serbaguna buat berbagai kebutuhan server kamu.",
            color=COLOR_INFO
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(
            name="✨ Fitur Utama",
            value=(
                "✅ Responsif dan sigap\n"
                "✅ Mudah digunakan lewat prefix `!jarvis` / `!j`\n"
            ),
            inline=False
        )
        embed.add_field(
            name="📌 Informasi",
            value=(
                f"**ID:** {self.bot.user.id}\n"
                f"**Dibuat:** {self.bot.user.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                "**Created By:** @nandhitooo\n"
                "**Prefix:** `!jarvis` atau `!j`\n"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name='help', help='Tampilkan menu bantuan')
    async def help_command(self, ctx: commands.Context):
        if hasattr(self.bot, '_send_help_menu'):
            await self.bot._send_help_menu(ctx)
        else:
            await ctx.send("Menu bantuan lagi tidak tersedia ya.")

    @commands.command(name='invite', help='Dapatkan link invite bot')
    async def invite(self, ctx: commands.Context):
        perms = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            connect=True,
            speak=True,
            manage_messages=True,
            kick_members=True,
            ban_members=True,
            moderate_members=True,
            manage_roles=True,
            manage_channels=True,
        )
        invite_link = discord.utils.oauth_url(self.bot.user.id, permissions=perms, scopes=("bot", "applications.commands"))
        embed = discord.Embed(
            title="📨 Invite Jarvis",
            description=f"Klik [di sini]({invite_link}) buat mengundang saya ke server kamu.",
            color=COLOR_INFO
        )
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='uptime', help='Lihat berapa lama bot sudah online')
    async def uptime(self, ctx: commands.Context):
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - self.bot.start_time
        
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        uptime_str = []
        if days > 0: uptime_str.append(f"{days} hari")
        if hours > 0: uptime_str.append(f"{hours} jam")
        if minutes > 0: uptime_str.append(f"{minutes} menit")
        if seconds > 0: uptime_str.append(f"{seconds} detik")

        embed = discord.Embed(
            title="🕒 Waktu Aktif",
            description=f"Saya sudah aktif selama **{', '.join(uptime_str) if uptime_str else '0 detik'}**.",
            color=COLOR_INFO
        )
        embed.set_footer(text=f"Aktif sejak: {self.bot.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        await ctx.send(embed=embed)

    @commands.command(name='stats', help='Statistik penggunaan bot')
    async def stats(self, ctx: commands.Context):
        guild_count = len(self.bot.guilds)
        user_count = sum(guild.member_count or 0 for guild in self.bot.guilds)
        latency = round(self.bot.latency * 1000)

        embed = discord.Embed(
            title="📊 Statistik Jarvis",
            color=COLOR_INFO
        )
        embed.add_field(name="🌐 Servers", value=f"`{guild_count}`", inline=True)
        embed.add_field(name="👥 Users", value=f"`{user_count}`", inline=True)
        embed.add_field(name="⚡ Latency", value=f"`{latency}ms`", inline=True)
        embed.add_field(name="⚙️ discord.py", value=f"`{discord.__version__}` (discord.py)", inline=False)
        
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='userinfo', aliases=['user', 'whois'], help='Lihat informasi user')
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        
        roles = [role.mention for role in member.roles[1:]] # exclude @everyone
        roles_value = " ".join(roles) if roles else "None"
        if len(roles_value) > 1024:
            roles_value = roles_value[:1021] + "..."
        
        embed = discord.Embed(title=f"👤 Info Pengguna — {member.name}", color=member.color)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
        embed.add_field(name="Akun Dibuat", value=member.created_at.strftime("%d %b %Y"), inline=True)
        embed.add_field(name="Join Server", value=member.joined_at.strftime("%d %b %Y") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name=f"Roles ({len(roles)})", value=roles_value, inline=False)
        
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='serverinfo', aliases=['server'], help='Lihat informasi server')
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        
        embed = discord.Embed(title=f"🏰 Info Server — {guild.name}", color=COLOR_INFO)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
            
        embed.add_field(name="Owner", value=guild.owner, inline=True)
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Dibuat Pada", value=guild.created_at.strftime("%d %b %Y"), inline=True)
        embed.add_field(name="Member", value=f"👥 {guild.member_count}", inline=True)
        embed.add_field(name="Channel", value=f"💬 {len(guild.text_channels)} Text | 🔊 {len(guild.voice_channels)} Voice", inline=True)
        embed.add_field(name="Roles", value=f"🛡️ {len(guild.roles)}", inline=True)
        
        embed.set_footer(text=f"Atas permintaan {ctx.author.name}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Utility(bot))
