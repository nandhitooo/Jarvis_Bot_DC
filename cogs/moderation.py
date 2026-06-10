import discord
from discord.ext import commands
import asyncio
from datetime import timedelta


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Helper: cek hierarki role ────────────────────────────────
    def _can_moderate(self, ctx: commands.Context, target: discord.Member) -> str | None:
        """Return error string jika tidak bisa moderasi, None jika bisa."""
        if target == ctx.author:
            return "❌ Kamu tidak bisa moderasi diri sendiri."
        if target == ctx.guild.owner:
            return "❌ Tidak bisa moderasi owner server."
        if target.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return "❌ Role kamu tidak cukup tinggi untuk moderasi user ini."
        if target.top_role >= ctx.guild.me.top_role:
            return "❌ Role bot tidak cukup tinggi untuk moderasi user ini."
        return None

    def _mod_embed(self, title: str, desc: str, color: int = 0xFF3333) -> discord.Embed:
        return discord.Embed(title=title, description=desc, color=color)

    # ────────────────────────────────────────────────────────────
    # BAN
    # ────────────────────────────────────────────────────────────
    @commands.command(name='ban', help='Ban user dari server')
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan"):
        err = self._can_moderate(ctx, member)
        if err:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", err))

        await member.ban(reason=f"{reason} | Oleh: {ctx.author}")
        embed = discord.Embed(title="🔨 Member Dibanned", color=0xFF3333)
        embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Alasan", value=reason, inline=False)
        embed.add_field(name="Oleh",   value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='unban', help='Unban user dari server')
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, *, user_id: int):
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            embed = discord.Embed(title="✅ Member Diunban", color=0x2ecc71)
            embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=False)
            embed.add_field(name="Oleh", value=ctx.author.mention, inline=False)
            await ctx.send(embed=embed)
        except discord.NotFound:
            await ctx.send(embed=self._mod_embed("❌ Gagal", "User tidak ditemukan atau tidak dalam daftar ban."))

    # ────────────────────────────────────────────────────────────
    # KICK
    # ────────────────────────────────────────────────────────────
    @commands.command(name='kick', help='Kick user dari server')
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan"):
        err = self._can_moderate(ctx, member)
        if err:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", err))

        await member.kick(reason=f"{reason} | Oleh: {ctx.author}")
        embed = discord.Embed(title="👢 Member Dikick", color=0xE67E22)
        embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Alasan", value=reason, inline=False)
        embed.add_field(name="Oleh",   value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    # ────────────────────────────────────────────────────────────
    # TIMEOUT (Mute sementara — built-in Discord)
    # ────────────────────────────────────────────────────────────
    @commands.command(name='timeout', help='Timeout user (menit). Contoh: !jarvis timeout @user 10 spam')
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx: commands.Context, member: discord.Member, durasi: int = 10, *, reason: str = "Tidak ada alasan"):
        err = self._can_moderate(ctx, member)
        if err:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", err))

        if durasi < 1 or durasi > 40320:  # maks 28 hari (limit Discord)
            return await ctx.send(embed=self._mod_embed("❌ Gagal", "Durasi harus antara 1–40320 menit (maks 28 hari)."))

        until = discord.utils.utcnow() + timedelta(minutes=durasi)
        await member.timeout(until, reason=f"{reason} | Oleh: {ctx.author}")

        embed = discord.Embed(title="🔇 Member Di-timeout", color=0xF1C40F)
        embed.add_field(name="User",    value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Durasi",  value=f"{durasi} menit", inline=True)
        embed.add_field(name="Berakhir", value=f"<t:{int(until.timestamp())}:R>", inline=True)
        embed.add_field(name="Alasan",  value=reason, inline=False)
        embed.add_field(name="Oleh",    value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='untimeout', help='Hapus timeout user')
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx: commands.Context, member: discord.Member):
        await member.timeout(None)
        embed = discord.Embed(title="🔊 Timeout Dihapus", color=0x2ecc71)
        embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Oleh", value=ctx.author.mention, inline=False)
        await ctx.send(embed=embed)

    # ────────────────────────────────────────────────────────────
    # PURGE (hapus banyak pesan sekaligus)
    # ────────────────────────────────────────────────────────────
    @commands.command(name='purge', aliases=['clear'], help='Hapus pesan. Contoh: !jarvis purge 10')
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, jumlah: int, member: discord.Member = None):
        if jumlah < 1 or jumlah > 100:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", "Jumlah pesan harus antara 1–100."))

        await ctx.message.delete()

        if member:
            def check(m): return m.author == member
            deleted = await ctx.channel.purge(limit=jumlah * 3, check=check, bulk=True)
            deleted = deleted[:jumlah]
        else:
            deleted = await ctx.channel.purge(limit=jumlah, bulk=True)

        msg = await ctx.send(embed=discord.Embed(
            description=f"🗑️ **{len(deleted)} pesan** dihapus oleh {ctx.author.mention}.",
            color=0x2ecc71
        ))
        await asyncio.sleep(4)
        await msg.delete()

    # ────────────────────────────────────────────────────────────
    # WARN (simpan di memory, reset saat bot restart)
    # ────────────────────────────────────────────────────────────
    @commands.command(name='warn', help='Beri peringatan ke user')
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan"):
        err = self._can_moderate(ctx, member)
        if err:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", err))

        if not hasattr(self.bot, '_warnings'):
            self.bot._warnings = {}

        key = (ctx.guild.id, member.id)
        self.bot._warnings.setdefault(key, [])
        self.bot._warnings[key].append({"reason": reason, "by": str(ctx.author)})
        count = len(self.bot._warnings[key])

        embed = discord.Embed(title="⚠️ Member Diperingatkan", color=0xF1C40F)
        embed.add_field(name="User",        value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Alasan",      value=reason, inline=False)
        embed.add_field(name="Total Warn",  value=f"**{count}x**", inline=True)
        embed.add_field(name="Oleh",        value=ctx.author.mention, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='warnings', aliases=['warnlist'], help='Lihat daftar warning user')
    @commands.has_permissions(kick_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        warnings = getattr(self.bot, '_warnings', {}).get((ctx.guild.id, member.id), [])
        if not warnings:
            return await ctx.send(embed=discord.Embed(
                description=f"✅ {member.mention} tidak memiliki warning.",
                color=0x2ecc71
            ))
        embed = discord.Embed(title=f"⚠️ Warnings — {member.name}", color=0xF1C40F)
        for i, w in enumerate(warnings, 1):
            embed.add_field(name=f"#{i}", value=f"**Alasan:** {w['reason']}\n**Oleh:** {w['by']}", inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='clearwarns', help='Hapus semua warning user')
    @commands.has_permissions(administrator=True)
    async def clearwarns(self, ctx: commands.Context, member: discord.Member):
        if hasattr(self.bot, '_warnings'):
            self.bot._warnings.pop((ctx.guild.id, member.id), None)
        await ctx.send(embed=discord.Embed(
            description=f"✅ Semua warning {member.mention} telah dihapus.",
            color=0x2ecc71
        ))

    # ────────────────────────────────────────────────────────────
    # SLOWMODE
    # ────────────────────────────────────────────────────────────
    @commands.command(name='slowmode', help='Set slowmode channel (detik). 0 untuk matikan.')
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx: commands.Context, detik: int):
        if detik < 0 or detik > 21600:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", "Slowmode harus antara 0–21600 detik."))
        await ctx.channel.edit(slowmode_delay=detik)
        msg = f"✅ Slowmode **dimatikan**." if detik == 0 else f"✅ Slowmode diset ke **{detik} detik**."
        await ctx.send(embed=discord.Embed(description=msg, color=0x2ecc71))

    # ────────────────────────────────────────────────────────────
    # LOCK / UNLOCK channel
    # ────────────────────────────────────────────────────────────
    @commands.command(name='lock', help='Kunci channel agar member tidak bisa mengirim pesan')
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=discord.Embed(
            description=f"🔒 Channel **{ctx.channel.name}** dikunci oleh {ctx.author.mention}.",
            color=0xFF3333
        ))

    @commands.command(name='unlock', help='Buka kunci channel')
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = True
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=discord.Embed(
            description=f"🔓 Channel **{ctx.channel.name}** dibuka oleh {ctx.author.mention}.",
            color=0x2ecc71
        ))

    @commands.command(name='mute', help='Mute user')
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, *, reason: str = "Tidak ada alasan"):
        err = self._can_moderate(ctx, member)
        if err:
            return await ctx.send(embed=self._mod_embed("❌ Gagal", err))

        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await ctx.guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False))
            for channel in ctx.guild.channels:
                await channel.set_permissions(muted_role, send_messages=False)

        await member.add_roles(muted_role, reason=f"{reason} | Oleh: {ctx.author}")
        embed = discord.Embed(title="🔇 Member Dimute", color=0xF1C40F)
        embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Alasan", value=reason, inline=False)
        embed.add_field(name="Oleh",   value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name='unmute', help='Unmute user')
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if muted_role and muted_role in member.roles:
            await member.remove_roles(muted_role, reason=f"Oleh: {ctx.author}")
            embed = discord.Embed(title="🔊 Member Diunmute", color=0x2ecc71)
            embed.add_field(name="User", value=f"{member} (`{member.id}`)", inline=False)
            embed.add_field(name="Oleh", value=ctx.author.mention, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=self._mod_embed("❌ Gagal", "User ini tidak sedang dimute."))

    # ────────────────────────────────────────────────────────────
    # ERROR HANDLER — permission errors
    # ────────────────────────────────────────────────────────────
    @ban.error
    @kick.error
    @timeout.error
    @untimeout.error
    @purge.error
    @warn.error
    @warnings.error
    @clearwarns.error
    @slowmode.error
    @lock.error
    @unlock.error
    @unban.error
    async def mod_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._mod_embed(
                "❌ Akses Ditolak",
                f"Kamu tidak memiliki permission: `{'`, `'.join(error.missing_permissions)}`"
            ))
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send(embed=self._mod_embed("❌ Gagal", "Member tidak ditemukan."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=self._mod_embed(
                "❌ Argumen Kurang",
                f"Argumen `{error.param.name}` diperlukan. Ketik `!jarvis` untuk bantuan."
            ))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=self._mod_embed("❌ Argumen Salah", "Pastikan format perintah sudah benar."))
        else:
            print(f"[Mod] Error: {error}")
            await ctx.send(embed=self._mod_embed("⚠️ Error", f"`{error}`"))


async def setup(bot):
    await bot.add_cog(Moderation(bot))
    print("[Moderation] Cog loaded.")
    