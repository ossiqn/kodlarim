import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import re
import sqlite3
import io
import aiohttp
import random
from PIL import Image, ImageDraw, ImageFont, ImageOps
from datetime import timedelta

conn = sqlite3.connect('sunucu.db')
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, xp INTEGER, level INTEGER)')
c.execute('CREATE TABLE IF NOT EXISTS invites (user_id INTEGER PRIMARY KEY, count INTEGER)')
c.execute('CREATE TABLE IF NOT EXISTS economy (user_id INTEGER PRIMARY KEY, coins INTEGER)')
conn.commit()

voice_sessions = {}
bot_invites = {}
yasakli_kelimeler = ["amk", "aq", "küfür1", "küfür2", "çöp", "berbat"]

class ReviewApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Onayla", style=discord.ButtonStyle.success, custom_id="approve_review")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = interaction.message.embeds[0]
        embed.title = "🌟 Yeni Kullanıcı Tavsiyesi"
        embed.color = 0x00ff80
        tavsiye_kanal = discord.utils.get(interaction.guild.text_channels, name="tavsiyeler")
        if tavsiye_kanal:
            await tavsiye_kanal.send(embed=embed)
        await interaction.message.delete()
        await interaction.response.send_message("✅ Yorum onaylandı ve paylaşıldı.", ephemeral=True)

    @discord.ui.button(label="❌ Reddet", style=discord.ButtonStyle.danger, custom_id="reject_review")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.message.delete()
        await interaction.response.send_message("❌ Yorum reddedildi.", ephemeral=True)

class ReviewModal(discord.ui.Modal, title="Tavsiye / Yorum Bırak"):
    review_text = discord.ui.TextInput(label="Yorumunuz", style=discord.TextStyle.paragraph, max_length=1000, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        text = self.review_text.value.lower()
        for kelime in yasakli_kelimeler:
            if kelime in text:
                return await interaction.response.send_message("❌ Yorumunuz güvenlik filtresine takıldı. Lütfen üslubunuza dikkat edin.", ephemeral=True)
        
        admin_kanal = discord.utils.get(interaction.guild.text_channels, name="yorum-onay")
        if admin_kanal:
            embed = discord.Embed(title="⏳ Onay Bekleyen Yorum", description=self.review_text.value, color=0xffaa00)
            if interaction.user.avatar:
                embed.set_author(name=interaction.user.name, icon_url=interaction.user.avatar.url)
            else:
                embed.set_author(name=interaction.user.name)
            await admin_kanal.send(embed=embed, view=ReviewApprovalView())
            await interaction.response.send_message("✅ Yorumunuz yetkili onayına gönderildi.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Onay kanalı bulunamadı. Yetkililer sistem kurulumunu yapmamış olabilir.", ephemeral=True)

class MarketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="VIP Rolü Al (5000 Coin)", style=discord.ButtonStyle.success, custom_id="btn_buy_vip")
    async def buy_vip(self, interaction: discord.Interaction, button: discord.ui.Button):
        c.execute('SELECT coins FROM economy WHERE user_id = ?', (interaction.user.id,))
        res = c.fetchone()
        bakiye = res[0] if res else 0

        if bakiye >= 5000:
            rol = discord.utils.get(interaction.guild.roles, name="VIP")
            if rol:
                await interaction.user.add_roles(rol)
                c.execute('UPDATE economy SET coins = ? WHERE user_id = ?', (bakiye - 5000, interaction.user.id))
                conn.commit()
                await interaction.response.send_message("✅ VIP rolünü başarıyla satın aldın!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ VIP rolü sunucuda bulunamadı.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Yetersiz bakiye. Mevcut Coin: {bakiye}", ephemeral=True)

class TicketKapatView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Talebi Kapat", style=discord.ButtonStyle.danger, custom_id="btn_close_ticket")
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⚠️ Destek talebi siliniyor...", ephemeral=False)
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketModal(discord.ui.Modal, title="Destek Talebi"):
    konu = discord.ui.TextInput(label="Konu Nedir?", style=discord.TextStyle.short, required=True, max_length=50)
    detay = discord.ui.TextInput(label="Açıklama", style=discord.TextStyle.paragraph, required=True, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        channel_name = f"destek-{user.name.lower()}"
        existing = discord.utils.get(guild.text_channels, name=channel_name)
        
        if existing:
            await interaction.response.send_message(f"❌ Zaten talebiniz var: {existing.mention}", ephemeral=True)
            return

        cat = discord.utils.get(guild.categories, name="📩 DESTEK TALEPLERİ")
        if not cat:
            cat = await guild.create_category("📩 DESTEK TALEPLERİ")

        ovs = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        tc = await guild.create_text_channel(name=channel_name, category=cat, overwrites=ovs)
        await interaction.response.send_message(f"✅ Talebiniz oluşturuldu: {tc.mention}", ephemeral=True)

        embed = discord.Embed(title=f"📩 {self.konu.value}", description=f"**Kullanıcı:** {user.mention}\n\n**Detay:**\n{self.detay.value}", color=0x2b2d31)
        await tc.send(content=f"{user.mention}", embed=embed, view=TicketKapatView())

class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Destek Talebi Oluştur", style=discord.ButtonStyle.primary, custom_id="btn_create_ticket")
    async def btn_create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketModal())

class KayitModal(discord.ui.Modal):
    def __init__(self, cinsiyet, s1, s2):
        super().__init__(title="Kayıt & Doğrulama")
        self.cinsiyet = cinsiyet
        self.s1 = s1
        self.s2 = s2
        self.isim = discord.ui.TextInput(label="İsminiz", style=discord.TextStyle.short, required=True, max_length=15)
        self.yas = discord.ui.TextInput(label="Yaşınız", style=discord.TextStyle.short, required=True, max_length=2)
        self.captcha = discord.ui.TextInput(label=f"Güvenlik: {s1} + {s2} kaçtır?", style=discord.TextStyle.short, required=True, max_length=3)
        self.add_item(self.isim)
        self.add_item(self.yas)
        self.add_item(self.captcha)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.captcha.value.isdigit() or int(self.captcha.value) != (self.s1 + self.s2):
            await interaction.response.send_message("❌ Captcha doğrulaması hatalı!", ephemeral=True)
            return

        g = interaction.guild
        u = interaction.user
        uye_r = discord.utils.get(g.roles, name="Üye")
        kayitsiz_r = discord.utils.get(g.roles, name="Kayıtsız")
        cin_r = discord.utils.get(g.roles, name=self.cinsiyet)
        
        if not (uye_r and kayitsiz_r and cin_r):
            await interaction.response.send_message("❌ Roller hatalı.", ephemeral=True)
            return

        try:
            await u.edit(nick=f"{self.isim.value} | {self.yas.value}")
            await u.add_roles(uye_r, cin_r)
            await u.remove_roles(kayitsiz_r)
            await interaction.response.send_message(f"✅ {self.cinsiyet} olarak kaydedildin.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Yetki hatası.", ephemeral=True)

class KayitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🚹 Erkek Kayıt", style=discord.ButtonStyle.primary, custom_id="btn_kayit_erkek")
    async def btn_erkek(self, interaction: discord.Interaction, button: discord.ui.Button):
        s1, s2 = random.randint(1, 10), random.randint(1, 10)
        await interaction.response.send_modal(KayitModal("Erkek", s1, s2))

    @discord.ui.button(label="🚺 Kadın Kayıt", style=discord.ButtonStyle.danger, custom_id="btn_kayit_kadin")
    async def btn_kadin(self, interaction: discord.Interaction, button: discord.ui.Button):
        s1, s2 = random.randint(1, 10), random.randint(1, 10)
        await interaction.response.send_modal(KayitModal("Kadın", s1, s2))

class DarqBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())

    async def setup_hook(self):
        self.add_view(TicketPanel())
        self.add_view(TicketKapatView())
        self.add_view(KayitView())
        self.add_view(MarketView())
        self.add_view(ReviewApprovalView())
        await self.tree.sync()

bot = DarqBot()
TOKEN = 'SENIN_BOT_TOKENIN_BURAYA'

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Satışa Hazır Sistem"))
    for g in bot.guilds:
        try: bot_invites[g.id] = await g.invites()
        except: bot_invites[g.id] = []
    print(f"{bot.user} Aktif!")

@bot.event
async def on_invite_create(invite):
    if invite.guild.id not in bot_invites: bot_invites[invite.guild.id] = []
    bot_invites[invite.guild.id].append(invite)

@bot.event
async def on_invite_delete(invite):
    if invite.guild.id in bot_invites:
        bot_invites[invite.guild.id] = [i for i in bot_invites[invite.guild.id] if i.id != invite.id]

@bot.event
async def on_member_join(member):
    g = member.guild
    inviter = None
    
    if g.id in bot_invites:
        old_i = bot_invites[g.id]
        try:
            new_i = await g.invites()
            for n in new_i:
                for o in old_i:
                    if n.id == o.id and n.uses > o.uses:
                        inviter = n.inviter
                        break
                if inviter: break
            bot_invites[g.id] = new_i
        except: pass

    if inviter:
        # Davet sayısını artır
        c.execute('SELECT count FROM invites WHERE user_id = ?', (inviter.id,))
        res = c.fetchone()
        if res: c.execute('UPDATE invites SET count = ? WHERE user_id = ?', (res[0]+1, inviter.id))
        else: c.execute('INSERT INTO invites (user_id, count) VALUES (?, ?)', (inviter.id, 1))
        
        # Davet edene Coin Ödülü (50 Coin)
        c.execute('SELECT coins FROM economy WHERE user_id = ?', (inviter.id,))
        eco_res = c.fetchone()
        if eco_res:
            c.execute('UPDATE economy SET coins = ? WHERE user_id = ?', (eco_res[0] + 50, inviter.id))
        else:
            c.execute('INSERT INTO economy (user_id, coins) VALUES (?, ?)', (inviter.id, 50))
        conn.commit()

    if (discord.utils.utcnow() - member.created_at).days < 7:
        try:
            await member.kick(reason="Anti-Raid")
            log_k = discord.utils.get(g.text_channels, name="güvenlik-log")
            if log_k: await log_k.send(f"🛡️ **Anti-Raid:** {member.mention} kicklendi. (Yeni hesap)")
        except: pass
        return

    kr = discord.utils.get(g.roles, name="Kayıtsız")
    if kr:
        try: await member.add_roles(kr)
        except: pass

    kk = discord.utils.get(g.text_channels, name="kayıt-odası")
    if kk:
        try:
            async with aiohttp.ClientSession() as ses:
                async with ses.get(str(member.display_avatar.replace(size=128, format="png"))) as r:
                    av_b = await r.read()
            
            av_i = Image.open(io.BytesIO(av_b)).convert("RGBA")
            m = Image.new("L", av_i.size, 0)
            d = ImageDraw.Draw(m)
            d.ellipse((0, 0, 128, 128), fill=255)
            av_i = ImageOps.fit(av_i, m.size, centering=(0.5, 0.5))
            av_i.putalpha(m)

            bg = Image.new("RGBA", (800, 250), (15, 15, 20, 255))
            bd = ImageDraw.Draw(bg)
            bd.rectangle([0, 0, 799, 249], outline=(0, 255, 128), width=3)
            bg.paste(av_i, (40, 60), av_i)
            
            try:
                f1 = ImageFont.truetype("arial.ttf", 35)
                f2 = ImageFont.truetype("arial.ttf", 20)
            except:
                f1 = ImageFont.load_default()
                f2 = ImageFont.load_default()

            bd.text((200, 80), f"Sisteme Giris: {member.name}", fill=(0, 255, 128), font=f1)
            if inviter: bd.text((200, 140), f"Davet Eden: {inviter.name} (+50 Coin Kazandı)", fill=(180, 180, 180), font=f2)
            
            buf = io.BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            fl = discord.File(buf, filename="w.png")
            
            emb = discord.Embed(title="Ağımıza Hoş Geldin", description=f"{member.mention}, doğrulamayı geçip kayıt ol.", color=0x00ff80)
            emb.set_image(url="attachment://w.png")
            await kk.send(content=f"{member.mention}", embed=emb, file=fl, view=KayitView())
        except:
            await kk.send(f"{member.mention} hoş geldin! Butonları kullanabilirsin.", view=KayitView())

@bot.event
async def on_message_delete(message):
    if message.author.bot: return
    if message.mentions:
        log_k = discord.utils.get(message.guild.text_channels, name="güvenlik-log")
        if log_k:
            mentions = ", ".join([m.mention for m in message.mentions])
            await log_k.send(f"👻 **Ghost Ping:** {message.author.mention} mesajını sildi!\nEtiketlenenler: {mentions}\nMesaj: `{message.content}`")

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    if not before.channel and after.channel:
        voice_sessions[member.id] = discord.utils.utcnow()
    elif before.channel and not after.channel:
        if member.id in voice_sessions:
            jt = voice_sessions.pop(member.id)
            f = (discord.utils.utcnow() - jt).total_seconds()
            xp_k = int(f / 60) * 10 
            coin_k = int(f / 60) * 5
            
            c.execute('SELECT xp, level FROM users WHERE user_id = ?', (member.id,))
            res = c.fetchone()
            if res:
                xp, lvl = res[0] + xp_k, res[1]
                c.execute('UPDATE users SET xp = ? WHERE user_id = ?', (xp, member.id))
            else:
                xp, lvl = xp_k, 0
                c.execute('INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)', (member.id, xp, lvl))
                
            c.execute('SELECT coins FROM economy WHERE user_id = ?', (member.id,))
            eco_res = c.fetchone()
            if eco_res:
                c.execute('UPDATE economy SET coins = ? WHERE user_id = ?', (eco_res[0] + coin_k, member.id))
            else:
                c.execute('INSERT INTO economy (user_id, coins) VALUES (?, ?)', (member.id, coin_k))
            conn.commit()

            nl = int(xp / 100)
            if nl > lvl:
                c.execute('UPDATE users SET level = ? WHERE user_id = ?', (nl, member.id))
                conn.commit()

@bot.event
async def on_message(message):
    if message.author.bot: return

    for kelime in yasakli_kelimeler:
        if kelime in message.content.lower():
            await message.delete()
            try:
                await message.author.timeout(timedelta(minutes=10), reason="Oto-Mod: Küfür kullanımı")
                log_k = discord.utils.get(message.guild.text_channels, name="güvenlik-log")
                if log_k: await log_k.send(f"🔨 **Oto-Mod:** {message.author.mention} küfür ettiği için 10 dakika susturuldu.\nMesaj: `{message.content}`")
                await message.channel.send(f"⚠️ {message.author.mention}, kelime filtremize takıldın!", delete_after=5)
            except: pass
            return

    if re.search(r"(http[s]?://|www\.)", message.content, re.IGNORECASE):
        if not message.author.guild_permissions.administrator:
            await message.delete()
            try:
                await message.author.timeout(timedelta(minutes=10), reason="Oto-Mod: Link paylaşımı")
                log_k = discord.utils.get(message.guild.text_channels, name="güvenlik-log")
                if log_k: await log_k.send(f"🔨 **Oto-Mod:** {message.author.mention} link paylaştığı için 10 dakika susturuldu.")
                await message.channel.send(f"⚠️ {message.author.mention}, link yasak!", delete_after=5)
            except: pass
            return

    c.execute('SELECT xp, level FROM users WHERE user_id = ?', (message.author.id,))
    res = c.fetchone()
    if res:
        xp, lvl = res[0] + 5, res[1]
        c.execute('UPDATE users SET xp = ? WHERE user_id = ?', (xp, message.author.id))
    else:
        xp, lvl = 5, 0
        c.execute('INSERT INTO users (user_id, xp, level) VALUES (?, ?, ?)', (message.author.id, xp, lvl))
        
    c.execute('SELECT coins FROM economy WHERE user_id = ?', (message.author.id,))
    eco_res = c.fetchone()
    if eco_res:
        c.execute('UPDATE economy SET coins = ? WHERE user_id = ?', (eco_res[0] + 2, message.author.id))
    else:
        c.execute('INSERT INTO economy (user_id, coins) VALUES (?, ?)', (message.author.id, 2))
    conn.commit()

    nl = int(xp / 100)
    if nl > lvl:
        c.execute('UPDATE users SET level = ? WHERE user_id = ?', (nl, message.author.id))
        conn.commit()
        lk = discord.utils.get(message.guild.text_channels, name="level-sorgulama")
        if lk: await lk.send(f"⚡ {message.author.mention} seviye atladı! Mevcut: **{nl}**")

    await bot.process_commands(message)

@bot.tree.command(name="tavsiye-yap", description="Sunucu için tavsiye veya yorum bırakırsınız.")
async def tavsiye_yap(interaction: discord.Interaction):
    await interaction.response.send_modal(ReviewModal())

@bot.tree.command(name="market", description="Sunucu marketini açar.")
async def market(interaction: discord.Interaction):
    c.execute('SELECT coins FROM economy WHERE user_id = ?', (interaction.user.id,))
    res = c.fetchone()
    bakiye = res[0] if res else 0
    embed = discord.Embed(title="🛒 Sunucu Marketi", description=f"**Mevcut Bakiye:** {bakiye} Coin\n\nAşağıdaki butonlardan ürün satın alabilirsiniz.", color=0xffaa00)
    await interaction.response.send_message(embed=embed, view=MarketView())

@bot.tree.command(name="level", description="Siberpunk estetikli profil kartını gösterir.")
async def level_sorgu(interaction: discord.Interaction):
    await interaction.response.defer()
    u = interaction.user
    c.execute('SELECT xp, level FROM users WHERE user_id = ?', (u.id,))
    res = c.fetchone()
    xp = res[0] if res else 0
    lvl = res[1] if res else 0
    
    c.execute('SELECT coins FROM economy WHERE user_id = ?', (u.id,))
    eco_res = c.fetchone()
    coins = eco_res[0] if eco_res else 0

    async with aiohttp.ClientSession() as ses:
        async with ses.get(str(u.display_avatar.replace(size=128, format="png"))) as r:
            av_b = await r.read()
            
    av_i = Image.open(io.BytesIO(av_b)).convert("RGBA")
    bg = Image.new("RGBA", (600, 200), (10, 10, 15, 255))
    bd = ImageDraw.Draw(bg)
    bd.rectangle([0, 0, 599, 199], outline=(0, 255, 128), width=2)
    bg.paste(av_i, (30, 36), av_i)
    
    try:
        f_b = ImageFont.truetype("arial.ttf", 30)
        f_k = ImageFont.truetype("arial.ttf", 18)
    except:
        f_b = ImageFont.load_default()
        f_k = ImageFont.load_default()

    bd.text((180, 40), f"{u.name}", fill=(0, 255, 128), font=f_b)
    bd.text((180, 85), f"Seviye: {lvl}  |  XP: {xp}/{ (lvl+1)*100 }", fill=(200, 200, 200), font=f_k)
    bd.text((180, 115), f"Bakiye: {coins} Coin", fill=(255, 215, 0), font=f_k)
    bd.rectangle([180, 150, 550, 165], outline=(50, 50, 50), fill=(20, 20, 20))
    prog = int(370 * (xp % 100) / 100)
    if prog > 0:
        bd.rectangle([180, 150, 180+prog, 165], fill=(0, 255, 128))

    buf = io.BytesIO()
    bg.save(buf, format="PNG")
    buf.seek(0)
    fl = discord.File(buf, filename="profile.png")
    
    await interaction.followup.send(file=fl)

@bot.tree.command(name="davetlerim", description="Davet istatistiklerinizi gösterir.")
async def davetlerim(interaction: discord.Interaction):
    c.execute('SELECT count FROM invites WHERE user_id = ?', (interaction.user.id,))
    res = c.fetchone()
    sayi = res[0] if res else 0
    await interaction.response.send_message(f"🔗 Şu ana kadar sunucuya **{sayi}** kişi davet ettin ve her biri için ödül kazandın!")

@bot.tree.command(name="siralama", description="En zenginleri ve en çok davet edenleri gösterir.")
async def siralama(interaction: discord.Interaction):
    embed = discord.Embed(title="🏆 Sunucu Liderlik Tablosu", color=0x00ff80)
    
    # En zengin 5 kişi
    c.execute('SELECT user_id, coins FROM economy ORDER BY coins DESC LIMIT 5')
    zenginler = c.fetchall()
    zengin_text = ""
    for idx, (uid, coins) in enumerate(zenginler, 1):
        zengin_text += f"**{idx}.** <@{uid}> - {coins} Coin\n"
    if not zengin_text: zengin_text = "Henüz veri yok."
    embed.add_field(name="💰 En Zenginler", value=zengin_text, inline=False)
    
    # En çok davet eden 5 kişi
    c.execute('SELECT user_id, count FROM invites ORDER BY count DESC LIMIT 5')
    davetciler = c.fetchall()
    davet_text = ""
    for idx, (uid, count) in enumerate(davetciler, 1):
        davet_text += f"**{idx}.** <@{uid}> - {count} Davet\n"
    if not davet_text: davet_text = "Henüz veri yok."
    embed.add_field(name="🔗 En Çok Davet Edenler", value=davet_text, inline=False)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="sunucu-kur", description="Her şeyi baştan sona kurar.")
async def sunucu_kur(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Yetkin yok.", ephemeral=True)
    await interaction.response.defer()
    g = interaction.guild
    roles = ["Kayıtsız", "Üye", "Erkek", "Kadın", "Aktif Üye", "VIP"]
    cr = {}
    for r in roles:
        rl = discord.utils.get(g.roles, name=r)
        if not rl: rl = await g.create_role(name=r)
        cr[r] = rl

    k_oku = {g.default_role: discord.PermissionOverwrite(read_messages=False), cr["Kayıtsız"]: discord.PermissionOverwrite(read_messages=True, send_messages=False)}
    k_kayit = {g.default_role: discord.PermissionOverwrite(read_messages=False), cr["Kayıtsız"]: discord.PermissionOverwrite(read_messages=True, send_messages=True), cr["Üye"]: discord.PermissionOverwrite(read_messages=False)}
    u_tam = {g.default_role: discord.PermissionOverwrite(read_messages=False), cr["Üye"]: discord.PermissionOverwrite(read_messages=True, send_messages=True, connect=True, speak=True)}
    a_oku = {g.default_role: discord.PermissionOverwrite(read_messages=False), g.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)}

    kats = {
        "📌 SUNUCU SİSTEMİ": {"k": ["duyuru", "kurallar", "roller", "güvenlik-log", "yorum-onay"], "y": k_oku},
        "🛡️ KAYIT ALANI": {"k": ["kayıt-odası"], "y": k_kayit},
        "🎫 DESTEK & TICKET": {"k": ["ticket-odası"], "y": u_tam},
        "ℹ️ SUNUCU BİLGİSİ": {"k": ["rol-isteme", "tavsiyeler", "kendini-tanıt", "level-sorgulama"], "y": u_tam},
        "💬 GENEL SOHBET": {"k": ["sohbet", "animanga-sohbet", "medya-link", "edit-odası", "oyun-sohbet"], "y": u_tam},
        "🎌 ANİME": {"k": ["anime-puanlama", "karşılaştırma", "anime-listeleri"], "y": u_tam},
        "🎮 EĞLENCE": {"k": ["sanat-odası", "anime-bilmece", "kelime-botu", "tuttu-tutmadı", "bot-kanalı", "mudae"], "y": u_tam}
    }

    for kat, veri in kats.items():
        kt = discord.utils.get(g.categories, name=kat)
        if not kt: kt = await g.create_category(kat, overwrites=veri["y"])
        for kn in veri["k"]:
            kanal = discord.utils.get(g.text_channels, name=kn)
            if not kanal:
                kanal = await g.create_text_channel(kn, category=kt)
                if kn == "kayıt-odası":
                    await kanal.send(embed=discord.Embed(title="Sistem", description="Cinsiyet seç.", color=0x2b2d31), view=KayitView())
                elif kn == "ticket-odası":
                    await kanal.send(embed=discord.Embed(title="Destek", description="Butona tıkla.", color=0x2b2d31), view=TicketPanel())
                elif kn in ["güvenlik-log", "yorum-onay"]:
                    await kanal.edit(sync_permissions=True, overwrites=a_oku)

    await interaction.followup.send("✅ Kurulum bitti. İtibar sistemi, Ekonomi ve Güvenlik tam operasyonel.")

bot.run(TOKEN)