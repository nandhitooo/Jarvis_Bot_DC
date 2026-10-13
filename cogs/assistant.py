import discord
from discord.ext import commands, tasks
import datetime
import asyncio
import aiohttp
import psutil
import os
import platform
import re
import ast
from urllib.parse import quote

# Sapaan tetap untuk seluruh pesan pengguna
HONORIFIC = "Boss"

class Assistant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminders = []
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    def parse_duration(self, time_str, allowed_units):
        """Parse durasi seperti '10m' menjadi timedelta, atau None jika tidak valid."""
        match = re.match(r'^(\d+)([smhd])$', time_str.lower())
        if not match:
            return None
        amount = int(match.group(1))
        unit = match.group(2)
        if amount < 1 or unit not in allowed_units:
            return None
        unit_map = {'s': 'seconds', 'm': 'minutes', 'h': 'hours', 'd': 'days'}
        return datetime.timedelta(**{unit_map[unit]: amount})

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        to_remove = []
        for r in self.reminders:
            if r['time'] <= now:
                try:
                    user = await self.bot.fetch_user(r['user_id'])
                except discord.HTTPException:
                    user = None
                if user:
                    embed = discord.Embed(
                        title="⏰ Pengingat!",
                        description=f"{HONORIFIC}, ini pengingat untuk: **{r['task']}**",
                        color=0x00E5FF
                    )
                    try:
                        await user.send(embed=embed)
                    except discord.HTTPException:
                        pass
                to_remove.append(r)
        
        for r in to_remove:
            self.reminders.remove(r)

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

    @commands.command(name='remind', help='Setel pengingat (contoh: !j remind 10m beli kopi)')
    async def remind(self, ctx: commands.Context, time_str: str, *, task: str):
        """Set a reminder. Time format: <number>[s|m|h|d]"""
        delta = self.parse_duration(time_str, ('s', 'm', 'h', 'd'))
        if delta is None or delta > datetime.timedelta(days=30):
            return await ctx.send(f"Mohon maaf, {HONORIFIC}, format waktunya belum tepat. Gunakan `s` (detik), `m` (menit), `h` (jam), atau `d` (hari). Contoh: `10m`.")

        remind_time = datetime.datetime.now(datetime.timezone.utc) + delta
        self.reminders.append({
            'user_id': ctx.author.id,
            'task': task,
            'time': remind_time
        })

        embed = discord.Embed(
            description=f"✅ Dengan senang hati, {HONORIFIC}. Saya ingatkan kembali **{task}** dalam **{time_str}**.",
            color=0x00E5FF
        )
        await ctx.send(embed=embed)

    @commands.command(name='timer', help='Setel timer (contoh: !j timer 5m)')
    async def timer(self, ctx: commands.Context, time_str: str):
        """Set a timer. Time format: <number>[s|m|h]"""
        delta = self.parse_duration(time_str, ('s', 'm', 'h'))
        if delta is None or delta > datetime.timedelta(hours=6):
            return await ctx.send(f"Mohon maaf, {HONORIFIC}, format waktunya belum tepat. Gunakan `s`, `m`, atau `h`.")

        seconds = int(delta.total_seconds())
        msg = await ctx.send(f"⏲️ Timer berjalan, {HONORIFIC}: **{time_str}**")
        await asyncio.sleep(seconds)
        await ctx.send(f"🔔 {ctx.author.mention}, waktu yang ditentukan telah habis. (**{time_str}**)")

    @commands.command(name='weather', help='Cek cuaca di suatu kota')
    async def weather(self, ctx: commands.Context, *, city: str):
        url = f"https://wttr.in/{quote(city)}?format=j1"
        timeout = aiohttp.ClientTimeout(total=10)
        async with ctx.typing():
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return await ctx.send(f"Mohon maaf, {HONORIFIC}, data cuaca tidak dapat saya ambil. Pastikan nama kota sudah benar.")
                        data = await resp.json()

                current = data['current_condition'][0]
                temp = current['temp_C']
                desc = current['weatherDesc'][0]['value']
                hum = current['humidity']
                wind = current['windspeedKmph']

                embed = discord.Embed(title=f"🌡️ Laporan Cuaca — {city.title()}", color=0x00E5FF)
                embed.add_field(name="Suhu", value=f"{temp}°C", inline=True)
                embed.add_field(name="Kondisi", value=desc, inline=True)
                embed.add_field(name="Kelembapan", value=f"{hum}%", inline=True)
                embed.add_field(name="Angin", value=f"{wind} km/h", inline=True)
                embed.set_footer(text="Data provided by wttr.in")
                await ctx.send(embed=embed)
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError, ValueError):
                await ctx.send(f"Mohon maaf, {HONORIFIC}, data cuaca tidak dapat saya ambil. Pastikan nama kota sudah benar, lalu coba lagi.")

    @commands.command(name='calc', help='Kalkulator matematika')
    async def calc(self, ctx: commands.Context, *, expr: str):
        def _eval(node):
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return node.value
                raise ValueError("konstanta tidak diizinkan")
            if isinstance(node, ast.BinOp):
                left = _eval(node.left)
                right = _eval(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                if isinstance(node.op, ast.FloorDiv):
                    return left // right
                if isinstance(node.op, ast.Mod):
                    return left % right
                if isinstance(node.op, ast.Pow):
                    if abs(right) > 100:
                        raise ValueError("eksponen terlalu besar")
                    return left ** right
                raise ValueError("operator tidak diizinkan")
            if isinstance(node, ast.UnaryOp):
                operand = _eval(node.operand)
                if isinstance(node.op, ast.UAdd):
                    return +operand
                if isinstance(node.op, ast.USub):
                    return -operand
                raise ValueError("operator tidak diizinkan")
            raise ValueError("ekspresi tidak diizinkan")

        expr_clean = expr.replace('^', '**').strip()
        if len(expr_clean) > 100:
            return await ctx.send(f"Mohon maaf, {HONORIFIC}, ekspresi itu terlalu panjang — maksimal 100 karakter.")

        try:
            tree = ast.parse(expr_clean, mode='eval')
            result = _eval(tree)
        except ZeroDivisionError:
            return await ctx.send(f"Mohon maaf, {HONORIFIC}, pembagian dengan nol tidak diperbolehkan.")
        except Exception:
            return await ctx.send(f"Mohon maaf, {HONORIFIC}, ekspresi itu tidak valid. Gunakan hanya angka dan operator dasar.")

        embed = discord.Embed(
            title="🔢 Kalkulator",
            description=f"**Input:** `{expr}`\n**Hasil:** `{result}`",
            color=0x00E5FF
        )
        await ctx.send(embed=embed)

    @commands.command(name='sysinfo', help='Lihat statistik sistem host bot')
    @commands.is_owner()
    async def sysinfo(self, ctx: commands.Context):
        cpu_usage = await asyncio.to_thread(psutil.cpu_percent, interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        embed = discord.Embed(title="🖥️ Status Sistem", color=0x00E5FF)
        embed.add_field(name="OS", value=f"{platform.system()} {platform.release()}", inline=False)
        embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
        embed.add_field(name="RAM Usage", value=f"{ram.percent}% ({round(ram.used / (1024**3), 2)} GB / {round(ram.total / (1024**3), 2)} GB)", inline=False)
        embed.add_field(name="Disk Usage", value=f"{disk.percent}%", inline=True)
        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Assistant(bot))
