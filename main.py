import asyncio, re, os, random, logging
from datetime import datetime, timezone
from threading import Thread
from flask import Flask, request, jsonify
from telethon import TelegramClient, events, Button as TButton
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from supabase import create_client, Client

# ==================== CẤU HÌNH HỆ THỐNG CƠ BẢN ====================
SUPABASE_URL = "https://npjjarsmvmqvhdnkvtxc.supabase.co" 
SUPABASE_KEY = "sb_publishable_gVXyT92FL0XpsiiEcerYFQ_RXE3n0ke"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

API_ID = 36437338
API_HASH = "18d34c7efc396d277f3db62baa078efc"
BOT_TOKEN = "8654764187:AAFTnwinFmQbJNIQiAwCN54Zi-1KZn5UJRw"

STK_MSB = "96886693002613"
ADMIN_ID = 7816353760 

logging.basicConfig(level=logging.INFO)
bot = TelegramClient(StringSession(), API_ID, API_HASH)

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ==================== HELPER FUNCTIONS & DATABASE ====================
def db_get_user(uid):
    res = supabase.table("users").select("*").eq("user_id", uid).execute()
    if not res.data:
        supabase.table("users").insert({"user_id": uid, "balance": 0}).execute()
        return {"user_id": uid, "balance": 0}
    return res.data[0]

def db_get_setting(key, default_value):
    res = supabase.table("settings").select("value").eq("key", key).execute()
    if not res.data:
        supabase.table("settings").insert({"key": key, "value": str(default_value)}).execute()
        return str(default_value)
    return res.data[0]['value']

def db_set_setting(key, value):
    res = supabase.table("settings").select("value").eq("key", key).execute()
    if not res.data:
        supabase.table("settings").insert({"key": key, "value": str(value)}).execute()
    else:
        supabase.table("settings").update({"value": str(value)}).eq("key", key).execute()

# ==================== LOGIC ĐẬP HỘP ĐA DANH MỤC ====================
async def worker_grab_loop(client, phone):
    try:
        if not client.is_connected(): await client.connect()
        if not await client.is_user_authorized():
            logging.error(f"Clone {phone} die session.")
            return

        try:
            cats = supabase.table("categories").select("target_bot").execute().data
            if cats:
                for c in cats:
                    if c.get('target_bot'):
                        try:
                            await client.send_message(c['target_bot'], "/start")
                            await asyncio.sleep(1.5) 
                        except Exception as start_err:
                            logging.warning(f"Clone {phone} không thể start {c['target_bot']}: {start_err}")
        except Exception as e:
            logging.error(f"Lỗi khi auto-start bot mục tiêu cho {phone}: {e}")

        @client.on(events.NewMessage())
        @client.on(events.MessageEdited())
        async def handler(ev):
            if not ev.reply_markup: return
            
            chat = await ev.get_chat()
            chat_username = getattr(chat, 'username', '')
            if not chat_username: return

            cats_res = supabase.table("categories").select("*").execute()
            if not cats_res.data: return
            
            matched_cat = next((c for c in cats_res.data if c.get('target_bot') and c['target_bot'].lower() == chat_username.lower()), None)
            
            if matched_cat:
                for row in ev.reply_markup.rows:
                    for btn in row.buttons:
                        if btn.text and "đập" in btn.text.lower():
                            await asyncio.sleep(random.uniform(0.1, 0.4))
                            try:
                                click_res = await ev.click(text=btn.text)
                                code_found = None
                                
                                if click_res and getattr(click_res, 'message', None):
                                    if "là:" in click_res.message:
                                        m_search = re.search(r'là:\s*([A-Z0-9]+)', click_res.message)
                                        if m_search: code_found = m_search.group(1)
                                
                                if not code_found:
                                    await asyncio.sleep(1.0)
                                    msgs = await client.get_messages(chat.id, limit=2)
                                    for m in msgs:
                                        if m.message and "Mã code của bạn là:" in m.message:
                                            m_match = re.search(r'là:\s*\n?([A-Z0-9]+)', m.message)
                                            if m_match: code_found = m_match.group(1)

                                if code_found:
                                    supabase.table("codes").insert({
                                        "code": code_found, 
                                        "status": "available", 
                                        "source_phone": phone,
                                        "category_id": matched_cat['id']
                                    }).execute()
                                    
                                    await bot.send_message(
                                        ADMIN_ID, 
                                        f"🎊 **NHẬN CODE MỚI!** \n🎮 Danh mục: **{matched_cat['name']}** \n📱 Clone: `{phone}`\n🔑 Code: `{code_found}`"
                                    )
                                    return
                            except Exception as e:
                                logging.error(f"Lỗi click {phone}: {e}")
        
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Worker {phone} dừng: {e}")

# ==================== GIAO DIỆN NGƯỜI DÙNG ====================
def main_menu_text(user):
    bot_intro = db_get_setting("BOT_INTRO", "Chào mừng bạn đến với hệ thống bán code tự động!")
    return (
        f"🤖 **HỆ THỐNG CỬA HÀNG CODE VIP** 🤖\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 ID Của Bạn: `{user['user_id']}`\n"
        f"💰 Số dư: **{user['balance']:,} VNĐ** \n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 {bot_intro}"
    )

def main_btns(uid):
    btns = [
        [TButton.inline("🛒 DANH MỤC GAME", b"list_categories")],
        [TButton.inline("🏦 NẠP TIỀN", b"dep_menu"), TButton.inline("🕒 LỊCH SỬ MUA", b"history")],
    ]
    if uid == ADMIN_ID:
        btns.append([TButton.inline("👑 QUẢN TRỊ ADMIN", b"admin_menu")])
    return btns

@bot.on(events.NewMessage(pattern="/start"))
async def start(e):
    user = db_get_user(e.sender_id)
    await e.respond(main_menu_text(user), buttons=main_btns(e.sender_id))

@bot.on(events.CallbackQuery)
async def cb_handler(e):
    uid, data = e.sender_id, e.data.decode()

    if data == "back":
        await e.edit(main_menu_text(db_get_user(uid)), buttons=main_btns(uid))

    elif data == "admin_menu":
        if uid != ADMIN_ID: return
        btns = [
            [TButton.inline("📂 QUẢN LÝ DANH MỤC", b"admin_cats"), TButton.inline("📱 QUẢN LÝ CLONE", b"admin_clones")],
            [TButton.inline("⚙️ CÀI ĐẶT CHUNG", b"admin_settings"), TButton.inline("💰 CỘNG/TRỪ TIỀN", b"admin_money")],
            [TButton.inline("🔙 TRANG CHỦ", b"back")]
        ]
        await e.edit("👨‍💻 **BẢNG ĐIỀU KHIỂN ADMIN** ", buttons=btns)

    elif data == "admin_clones":
        if uid != ADMIN_ID: return
        res = supabase.table("my_clones").select("*").execute()
        btns = [[TButton.inline("➕ THÊM CLONE MỚI", b"add_clone")]]
        if res.data:
            for c in res.data:
                btns.append([TButton.inline(f"🗑 Xóa {c['phone']}", f"del_clone_{c['id']}")])
        btns.append([TButton.inline("🔙 QUAY LẠI", b"admin_menu")])
        await e.edit(f"📱 **QUẢN LÝ CLONE ({len(res.data)} acc)** ", buttons=btns)

    elif data.startswith("del_clone_"):
        cid = data.split("_")[2]
        supabase.table("my_clones").delete().eq("id", cid).execute()
        await e.answer("✅ Đã xóa clone!", alert=True)
        res = supabase.table("my_clones").select("*").execute()
        btns = [[TButton.inline("➕ THÊM CLONE MỚI", b"add_clone")]]
        if res.data:
            for c in res.data:
                btns.append([TButton.inline(f"🗑 Xóa {c['phone']}", f"del_clone_{c['id']}")])
        btns.append([TButton.inline("🔙 QUAY LẠI", b"admin_menu")])
        await e.edit(f"📱 **QUẢN LÝ CLONE ({len(res.data)} acc)** ", buttons=btns)

    elif data == "admin_settings":
        if uid != ADMIN_ID: return
        intro = db_get_setting("BOT_INTRO", "Chưa cài đặt")
        channel = db_get_setting("NOTIFY_CHANNEL_ID", "Chưa cài đặt")
        txt = (f"⚙️ **CÀI ĐẶT HỆ THỐNG** \n\n"
               f"1️⃣ **Lời chào:** {intro}\n"
               f"2️⃣ **ID Kênh thông báo:** `{channel}`")
        btns = [
            [TButton.inline("SỬA LỜI CHÀO", b"set_intro"), TButton.inline("SỬA KÊNH THÔNG BÁO", b"set_channel")],
            [TButton.inline("🔙 QUAY LẠI", b"admin_menu")]
        ]
        await e.edit(txt, buttons=btns)

    elif data == "set_intro":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("📝 Nhập lời chào mới:")
            db_set_setting("BOT_INTRO", (await conv.get_response()).text.strip())
            await conv.send_message("✅ Đã cập nhật!", buttons=[[TButton.inline("🔙 CÀI ĐẶT", b"admin_settings")]])

    elif data == "set_channel":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("📢 Nhập ID Kênh (Ví dụ: -100xxx):")
            db_set_setting("NOTIFY_CHANNEL_ID", (await conv.get_response()).text.strip())
            await conv.send_message("✅ Đã cập nhật!", buttons=[[TButton.inline("🔙 CÀI ĐẶT", b"admin_settings")]])

    # [FIXED] Quản lý danh mục với count='exact' kết hợp limit(1) để không bị treo
    elif data == "admin_cats":
        if uid != ADMIN_ID: return
        cats = supabase.table("categories").select("*").execute().data
        if not cats:
            txt = "📂 **DANH SÁCH GAME CỦA SHOP** \n\n❌ Hiện tại kho chưa có game nào. Hãy thêm mới!"
        else:
            txt = "📂 **DANH SÁCH GAME CỦA SHOP** \n━━━━━━━━━━━━━━━━━━\n"
            for c in cats:
                count_res = supabase.table("codes").select("id", count='exact').eq("category_id", c['id']).eq("status", "available").limit(1).execute()
                stock = count_res.count if count_res.count is not None else 0
                txt += f"🔸 **ID: `{c['id']}`** | **{c['name']}**\n"
                txt += f"   ┣ 💵 Giá bán: {c['price']:,}đ\n"
                txt += f"   ┣ 🤖 Bot check: @{c['target_bot']}\n"
                txt += f"   ┗ 📦 Tồn kho: {stock} code\n"
                txt += "━━━━━━━━━━━━━━━━━━\n"
        btns = [
            [TButton.inline("➕ THÊM GAME MỚI", b"add_cat"), TButton.inline("📦 THÊM CODE TAY", b"add_manual_codes")],
            [TButton.inline("✏️ SỬA GIÁ BÁN", b"edit_cat_price"), TButton.inline("🗑 XÓA GAME", b"del_cat")],
            [TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]
        ]
        await e.edit(txt, buttons=btns)

    elif data == "add_cat":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("🎮 Nhập Tên Game Mới:")
            name = (await conv.get_response()).text.strip()
            await conv.send_message("💰 Nhập Giá bán (Số):")
            try:
                price = int((await conv.get_response()).text.strip())
                await conv.send_message("🤖 Username Bot Đập Hộp (Bỏ @):")
                bot_target = (await conv.get_response()).text.strip().replace("@", "")
                await conv.send_message("📝 Mô tả ngắn gọn:")
                desc = (await conv.get_response()).text.strip()
                supabase.table("categories").insert({"name": name, "price": price, "target_bot": bot_target, "description": desc}).execute()
                await conv.send_message(f"✅ Đã tạo: **{name}**", buttons=[[TButton.inline("🔙 DANH MỤC", b"admin_cats")]])
            except:
                await conv.send_message("❌ Lỗi dữ liệu!", buttons=[[TButton.inline("🔙 DANH MỤC", b"admin_cats")]])

    elif data == "edit_cat_price":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("✏️ Nhập ID game cần sửa giá:")
            try:
                cid = int((await conv.get_response()).text.strip())
                await conv.send_message("💰 Nhập GIÁ MỚI:")
                new_price = int((await conv.get_response()).text.strip())
                supabase.table("categories").update({"price": new_price}).eq("id", cid).execute()
                await conv.send_message("✅ Đã cập nhật giá!", buttons=[[TButton.inline("🔙 DANH MỤC", b"admin_cats")]])
            except: await conv.send_message("❌ Lỗi!")

    elif data == "del_cat":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("🗑 Nhập ID game cần XÓA:")
            try:
                cid = int((await conv.get_response()).text.strip())
                supabase.table("codes").delete().eq("category_id", cid).execute()
                supabase.table("categories").delete().eq("id", cid).execute()
                await conv.send_message("✅ Đã xóa game!", buttons=[[TButton.inline("🔙 DANH MỤC", b"admin_cats")]])
            except: await conv.send_message("❌ Lỗi!")

    elif data == "add_manual_codes":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("📦 Nhập ID Danh mục để thêm code:")
            try:
                cat_id = int((await conv.get_response()).text.strip())
                await conv.send_message("👉 Gửi danh sách code (Mỗi code 1 dòng):")
                codes_msg = await conv.get_response()
                raw_codes = codes_msg.text.strip().split('\n')
                insert_data = [{"code": c.strip(), "status": "available", "source_phone": "Admin", "category_id": cat_id} for c in raw_codes if c.strip()]
                if insert_data:
                    supabase.table("codes").insert(insert_data).execute()
                    await conv.send_message(f"✅ Đã nạp {len(insert_data)} code!", buttons=[[TButton.inline("🔙 DANH MỤC", b"admin_cats")]])
            except: await conv.send_message("❌ Lỗi!")

    elif data == "admin_money":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("👤 Nhập ID khách:")
            try:
                tid = int((await conv.get_response()).text.strip())
                await conv.send_message("💰 Số tiền (VD: 5000 hoặc -5000):")
                amt = int((await conv.get_response()).text.strip())
                user = db_get_user(tid)
                supabase.table("users").update({"balance": user['balance'] + amt}).eq("user_id", tid).execute()
                await conv.send_message("✅ Thành công!", buttons=[[TButton.inline("🔙 ADMIN", b"admin_menu")]])
            except: await conv.send_message("❌ Lỗi!")

    # ==================== MENU KHÁCH HÀNG ====================
    elif data == "history":
        await e.edit("🕒 Tìm tin nhắn `MUA THÀNH CÔNG` để xem lại code.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])

    elif data == "list_categories":
        cats = supabase.table("categories").select("*").execute().data
        if not cats: return await e.answer("Chưa có danh mục!", alert=True)
        btns = []
        for c in cats:
            count_res = supabase.table("codes").select("id", count='exact').eq("category_id", c['id']).eq("status", "available").limit(1).execute()
            stock = count_res.count if count_res.count is not None else 0
            status = f"Kho: {stock}" if stock > 0 else "🔴 HẾT HÀNG"
            btns.append([TButton.inline(f"🎮 {c['name']} - {c['price']:,}đ ({status})", f"vcat_{c['id']}")])
        btns.append([TButton.inline("🔙 QUAY LẠI", b"back")])
        await e.edit("🛒 **DANH SÁCH GAME ĐANG BÁN:**", buttons=btns)

    elif data.startswith("vcat_"):
        cid = int(data.split("_")[1])
        cat = supabase.table("categories").select("*").eq("id", cid).execute().data[0]
        count_res = supabase.table("codes").select("id", count='exact').eq("category_id", cid).eq("status", "available").limit(1).execute()
        stock = count_res.count if count_res.count is not None else 0
        txt = (f"🎮 **{cat['name']}** \n━━━━━━━━━━━━\n📝 {cat['description']}\n\n"
               f"💵 Giá: **{cat['price']:,}đ** \n📦 Tồn kho: **{stock}** code")
        btns = [[TButton.inline("🛒 MUA 1 CODE", f"buy_{cid}_1")],
                [TButton.inline("🛒 MUA NHIỀU", f"buycustom_{cid}")],
                [TButton.inline("🔙 DANH MỤC", b"list_categories")]]
        await e.edit(txt, buttons=btns)

    elif data.startswith("buycustom_"):
        cid = int(data.split("_")[1])
        cat = supabase.table("categories").select("*").eq("id", cid).execute().data[0]
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message(f"🛒 Game: **{cat['name']}**. Nhập số lượng cần mua:")
            try:
                qty = int((await conv.get_response()).text.strip())
                user = db_get_user(uid)
                cost = cat['price'] * qty
                if user['balance'] < cost: return await conv.send_message("❌ Không đủ tiền!", buttons=[[TButton.inline("🔙 DANH MỤC", b"list_categories")]])
                stock_data = supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute().data
                if len(stock_data) < qty: return await conv.send_message("❌ Kho không đủ!", buttons=[[TButton.inline("🔙 DANH MỤC", b"list_categories")]])
                supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute()
                res_text = f"✅ **MUA THÀNH CÔNG {qty} CODE!**\n"
                for c in stock_data:
                    supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute()
                    res_text += f"`{c['code']}`\n"
                await conv.send_message(res_text, buttons=[[TButton.inline("🔙 TRANG CHỦ", b"back")]])
            except: await conv.send_message("❌ Lỗi số lượng!")

    elif data.startswith("buy_"):
        _, cid, qty = data.split("_")
        cid, qty = int(cid), int(qty)
        cat = supabase.table("categories").select("*").eq("id", cid).execute().data[0]
        user = db_get_user(uid)
        cost = cat['price'] * qty
        if user['balance'] < cost: return await e.answer("❌ Không đủ tiền!", alert=True)
        stock = supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute().data
        if len(stock) < qty: return await e.answer("❌ Hết hàng!", alert=True)
        supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute()
        res_text = f"✅ **MUA THÀNH CÔNG!**\n"
        for c in stock:
            supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute()
            res_text += f"`{c['code']}`\n"
        await e.delete()
        await bot.send_message(uid, res_text, buttons=[[TButton.inline("🔙 TRANG CHỦ", b"back")]])

    elif data == "dep_menu":
        btns = [[TButton.inline(f"💸 {a:,}đ", f"p_{a}") for a in [10000, 50000, 100000]], [TButton.inline("🔙 QUAY LẠI", b"back")]]
        await e.edit("🏦 **CHỌN MỨC NẠP:** ", buttons=btns)

    elif data.startswith("p_"):
        amt = data.split("_")[1]
        qr = f"https://img.vietqr.io/image/MSB-{STK_MSB}-compact2.png?amount={amt}&addInfo=NAP%20{uid}"
        await e.edit(f"📥 CK **{int(amt):,}đ**. ND: `{uid}`", buttons=[[TButton.url("MỞ QR", qr)], [TButton.inline("🔙 QUAY LẠI", b"back")]])

# ==================== LOGIC THÊM CLONE ====================
@bot.on(events.CallbackQuery(data=b"add_clone"))
async def add_clone_process(e):
    uid = e.sender_id
    if uid != ADMIN_ID: return
    async with bot.conversation(uid) as conv:
        await conv.send_message("📞 Số điện thoại (+84...):")
        phone = (await conv.get_response()).text.strip()
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        await client.send_code_request(phone)
        await conv.send_message("📩 Nhập OTP:")
        otp = (await conv.get_response()).text.strip()
        try:
            await client.sign_in(phone, otp)
        except SessionPasswordNeededError:
            await conv.send_message("🔐 Nhập 2FA:")
            await client.sign_in(password=(await conv.get_response()).text.strip())
        ss = client.session.save()
        supabase.table("my_clones").insert({"phone": phone, "session": ss}).execute()
        await conv.send_message("✅ Đã thêm clone!")
        asyncio.create_task(worker_grab_loop(client, phone))

# ==================== WEBHOOK & MAIN ====================
app = Flask(__name__)
@app.route('/sepay-webhook', methods=['POST'])
def webhook():
    d = request.json
    m = re.search(r'(\d{8,12})', d.get("content", "").upper())
    if m:
        uid, amt = int(m.group(1)), int(d.get("transferAmount", 0))
        user = db_get_user(uid)
        supabase.table("users").update({"balance": user['balance'] + amt}).eq("user_id", uid).execute()
        asyncio.run_coroutine_threadsafe(bot.send_message(uid, f"✅ Nạp +{amt:,}đ thành công!"), loop)
    return jsonify({"status": "ok"}), 200

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    print("--- BOT STARTED ---")
    clones = supabase.table("my_clones").select("*").execute().data
    for c in clones:
        try:
            cl = TelegramClient(StringSession(c['session']), API_ID, API_HASH)
            asyncio.create_task(worker_grab_loop(cl, c['phone']))
        except: pass
    await bot.run_until_disconnected()

if __name__ == '__main__':
    Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    loop.run_until_complete(main())
