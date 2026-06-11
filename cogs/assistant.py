import discord
from discord.ext import commands, tasks
import datetime
import asyncio
import aiohttp
import psutil
import os
import platform

class Assistant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminders = []
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        to_remove = []
        for r in self.reminders:
            if r['time'] <= now:
                user = self.bot.get_user(r['user_id'])
                if user:
                    embed = discord.Embed(
                        title="⏰ Pengingat!",
                        description=f"Boss, ini pengingat untuk: **{r['task']}**",
                        color=0x00E5FF
                    )
                    try:
                        await user.send(embed=embed)
                    except:
                        pass
                to_remove.append(r)
        
        for r in to_remove:
            self.reminders.remove(r)

    @commands.command(name='remind', help='Setel pengingat (contoh: !j remind 10m beli kopi)')
    async def remind(self, ctx: commands.Context, time_str: str, *, task: str):
        """Set a reminder. Time format: <number>[s|m|h|d]"""
        amount = int(time_str[:-1])
        unit = time_str[-1].lower()
        
        delta = None
        if unit == 's': delta = datetime.timedelta(seconds=amount)
        elif unit == 'm': delta = datetime.timedelta(minutes=amount)
        elif unit == 'h': delta = datetime.timedelta(hours=amount)
        elif unit == 'd': delta = datetime.timedelta(days=amount)
        else:
            return await ctx.send("Format waktu salah! Gunakan `s` (detik), `m` (menit), `h` (jam), atau `d` (hari). Contoh: `10m`.")

        remind_time = datetime.datetime.now(datetime.timezone.utc) + delta
        self.reminders.append({
            'user_id': ctx.author.id,
            'task': task,
            'time': remind_time
        })

        embed = discord.Embed(
            description=f"✅ Siap, Boss. Saya akan ingatkan untuk **{task}** dalam **{time_str}**.",
            color=0x00E5FF
        )
        await ctx.send(embed=embed)

    @commands.command(name='timer', help='Setel timer (contoh: !j timer 5m)')
    async def timer(self, ctx: commands.Context, time_str: str):
        """Set a timer. Time format: <number>[s|m|h]"""
        amount = int(time_str[:-1])
        unit = time_str[-1].lower()
        
        seconds = 0
        if unit == 's': seconds = amount
        elif unit == 'm': seconds = amount * 60
        elif unit == 'h': seconds = amount * 3600
        else:
            return await ctx.send("Format waktu salah! Gunakan `s`, `m`, atau `h`.")

        msg = await ctx.send(f"⏲️ Timer dimulai: **{time_str}**")
        await asyncio.sleep(seconds)
        await ctx.send(f"🔔 {ctx.author.mention}, waktu habis! (**{time_str}**)")

    @commands.command(name='weather', help='Cek cuaca di suatu kota')
    async def weather(self, ctx: commands.Context, *, city: str):
        url = f"https://wttr.in/{city}?format=j1"
        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await ctx.send("Gagal mengambil data cuaca. Pastikan nama kota benar.")
                    data = await resp.json()
                    
                    current = data['current_condition'][0]
                    temp = current['temp_C']
                    desc = current['weatherDesc'][0]['value']
                    hum = current['humidity']
                    wind = current['windspeedKmph']
                    
                    embed = discord.Embed(title=f"🌡️ Cuaca di {city.capitalize()}", color=0x00E5FF)
                    embed.add_field(name="Suhu", value=f"{temp}°C", inline=True)
                    embed.add_field(name="Kondisi", value=desc, inline=True)
                    embed.add_field(name="Kelembapan", value=f"{hum}%", inline=True)
                    embed.add_field(name="Angin", value=f"{wind} km/h", inline=True)
                    embed.set_footer(text="Data provided by wttr.in")
                    await ctx.send(embed=embed)

    @commands.command(name='calc', help='Kalkulator matematika')
    async def calc(self, ctx: commands.Context, *, expr: str):
        # Basic safety: allow only math characters
        allowed = "0123456789+-*/(). "
        if not all(c in allowed for c in expr):
            return await ctx.send("Ekspresi tidak valid! Hanya gunakan angka dan operator dasar.")
        
        try:
            result = eval(expr, {"__builtins__": None}, {})
            embed = discord.Embed(
                title="🔢 Kalkulator",
                description=f"**Input:** `{expr}`\n**Hasil:** `{result}`",
                color=0x00E5FF
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Gagal menghitung: `{e}`")

    @commands.command(name='sysinfo', help='Lihat statistik sistem host bot')
    async def sysinfo(self, ctx: commands.Context):
        cpu_usage = psutil.cpu_percent()
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        embed = discord.Embed(title="🖥️ System Information", color=0x00E5FF)
        embed.add_field(name="OS", value=f"{platform.system()} {platform.release()}", inline=False)
        embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
        embed.add_field(name="RAM Usage", value=f"{ram.percent}% ({round(ram.used / (1024**3), 2)} GB / {round(ram.total / (1024**3), 2)} GB)", inline=False)
        embed.add_field(name="Disk Usage", value=f"{disk.percent}%", inline=True)
        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Assistant(bot))
