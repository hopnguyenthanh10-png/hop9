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

# ==================== LOGIC ĐẬP HỘP ĐA DANH MỤC (PHÂN LOẠI BOT) ====================
async def worker_grab_loop(client, phone):
    try:
        if not client.is_connected(): await client.connect()
        if not await client.is_user_authorized():
            logging.error(f"Clone {phone} die session.")
            return

        @client.on(events.NewMessage())
        @client.on(events.MessageEdited())
        async def handler(ev):
            if not ev.reply_markup: return
            
            chat = await ev.get_chat()
            chat_username = getattr(chat, 'username', '')
            if not chat_username: return

            # Lấy danh sách danh mục để biết bot này thuộc game nào
            cats_res = supabase.table("categories").select("*").execute()
            if not cats_res.data: return
            
            # Tìm danh mục khớp với username bot đang gửi tin nhắn
            matched_cat = next((c for c in cats_res.data if c.get('target_bot') and c['target_bot'].lower() == chat_username.lower()), None)
            
            if matched_cat:
                for row in ev.reply_markup.rows:
                    for btn in row.buttons:
                        if btn.text and "đập" in btn.text.lower():
                            await asyncio.sleep(random.uniform(0.1, 0.4))
                            try:
                                click_res = await ev.click(text=btn.text)
                                code_found = None
                                
                                # Cách 1: Bắt từ Popup
                                if click_res and getattr(click_res, 'message', None):
                                    if "là:" in click_res.message:
                                        m_search = re.search(r'là:\s*([A-Z0-9]+)', click_res.message)
                                        if m_search: code_found = m_search.group(1)
                                
                                # Cách 2: Bắt từ tin nhắn mới nhất
                                if not code_found:
                                    await asyncio.sleep(1.0)
                                    msgs = await client.get_messages(chat.id, limit=2)
                                    for m in msgs:
                                        if m.message and "Mã code của bạn là:" in m.message:
                                            m_match = re.search(r'là:\s*\n?([A-Z0-9]+)', m.message)
                                            if m_match: code_found = m_match.group(1)

                                if code_found:
                                    # Lưu code vào đúng danh mục (category_id)
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

    # ==================== MENU ADMIN ====================
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
        # Quay lại menu clone
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

    elif data == "admin_cats":
        if uid != ADMIN_ID: return
        cats = supabase.table("categories").select("*").execute().data
        txt = "📂 **DANH SÁCH DANH MỤC** \n\n"
        for c in cats:
            stock = len(supabase.table("codes").select("id").eq("category_id", c['id']).eq("status", "available").execute().data)
            txt += f"🔸 ID `{c['id']}`: {c['name']} | Giá: {c['price']}đ | Kho: {stock} code\n"
        
        btns = [
            [TButton.inline("➕ THÊM DANH MỤC", b"add_cat"), TButton.inline("📦 THÊM CODE TAY", b"add_manual_codes")],
            [TButton.inline("✏️ SỬA GIÁ", b"edit_cat_price"), TButton.inline("🗑 XÓA", b"del_cat")],
            [TButton.inline("🔙 QUAY LẠI", b"admin_menu")]
        ]
        await e.edit(txt, buttons=btns)

    elif data == "add_manual_codes":
        if uid != ADMIN_ID: return
        await e.delete()
        async with bot.conversation(uid) as conv:
            cats = supabase.table("categories").select("*").execute().data
            if not cats:
                await conv.send_message("❌ Chưa có danh mục nào! Hãy tạo danh mục trước.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"admin_cats")]])
                return
            
            cat_text = "📦 **THÊM CODE THỦ CÔNG** \n\nDanh sách ID Danh mục:\n"
            for c in cats:
                cat_text += f"🔸 ID: `{c['id']}` - {c['name']}\n"
            cat_text += "\n👉 **Nhập ID Danh mục bạn muốn thêm code vào:** "
            
            await conv.send_message(cat_text)
            
            try:
                cat_id_msg = await conv.get_response()
                cat_id = int(cat_id_msg.text.strip())
            except ValueError:
                await conv.send_message("❌ ID danh mục phải là số!", buttons=[[TButton.inline("🔙 QUAY LẠI", b"admin_cats")]])
                return

            cat_exists = next((c for c in cats if c['id'] == cat_id), None)
            if not cat_exists:
                await conv.send_message("❌ Không tìm thấy danh mục này!", buttons=[[TButton.inline("🔙 QUAY LẠI", b"admin_cats")]])
                return

            await conv.send_message(
                f"📝 Đang thêm code cho game: **{cat_exists['name']}** \n\n"
                f"👉 **Gửi danh sách code vào đây (Mỗi code 1 dòng):** \n"
                f"Ví dụ:\nCODE123\nCODE456\nCODE789"
            )
            
            codes_msg = await conv.get_response()
            raw_codes = codes_msg.text.strip().split('\n')
            
            valid_codes = [c.strip() for c in raw_codes if c.strip()]
            
            if not valid_codes:
                await conv.send_message("❌ Bạn chưa nhập code nào!", buttons=[[TButton.inline("🔙 QUAY LẠI", b"admin_cats")]])
                return
            
            insert_data = [
                {
                    "code": code,
                    "status": "available",
                    "source_phone": "Admin_Manual",
                    "category_id": cat_id
                } for code in valid_codes
            ]
            
            supabase.table("codes").insert(insert_data).execute()
            
            await conv.send_message(
                f"✅ **THÀNH CÔNG!** \nĐã nạp thêm **{len(valid_codes)}** code vào danh mục **{cat_exists['name']}** .", 
                buttons=[[TButton.inline("🔙 QUẢN LÝ DANH MỤC", b"admin_cats")]]
            )

    elif data == "add_cat":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("🎮 Tên Game:")
            name = (await conv.get_response()).text.strip()
            await conv.send_message("💰 Giá bán:")
            price = int((await conv.get_response()).text.strip())
            await conv.send_message("🤖 Username Bot Đập Hộp (không @):")
            bot_target = (await conv.get_response()).text.strip()
            await conv.send_message("📝 Mô tả ngắn:")
            desc = (await conv.get_response()).text.strip()
            
            supabase.table("categories").insert({"name": name, "price": price, "target_bot": bot_target, "description": desc}).execute()
            await conv.send_message("✅ Đã thêm danh mục!", buttons=[[TButton.inline("🔙 DANH MỤC", b"admin_cats")]])

    elif data == "admin_money":
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("👤 Nhập ID khách:")
            tid = int((await conv.get_response()).text.strip())
            await conv.send_message("💰 Số tiền cộng/trừ (VD: 5000 hoặc -5000):")
            amt = int((await conv.get_response()).text.strip())
            user = db_get_user(tid)
            supabase.table("users").update({"balance": user['balance'] + amt}).eq("user_id", tid).execute()
            await conv.send_message("✅ Thành công!", buttons=[[TButton.inline("🔙 ADMIN", b"admin_menu")]])

    # ==================== MENU KHÁCH HÀNG ====================
    elif data == "history":
        txt = (
            "🕒 **LỊCH SỬ MUA CODE** \n\n"
            "Toàn bộ code mà bạn đã mua đều được bot gửi trực tiếp vào trong khung chat này.\n\n"
            "👉 **Cách kiểm tra:** Bạn hãy lướt tin nhắn lên trên hoặc bấm vào nút Tìm Kiếm (Search) của Telegram, tìm từ khóa `MUA THÀNH CÔNG` để xem lại tất cả các code đã mua nhé!"
        )
        await e.edit(txt, buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])

    elif data == "list_categories":
        cats = supabase.table("categories").select("*").execute().data
        if not cats: return await e.answer("Chưa có danh mục nào!", alert=True)
        # Bổ sung tính số lượng kho ngay ngoài danh mục để khách thấy rõ
        btns = []
        for c in cats:
            stock = len(supabase.table("codes").select("id").eq("category_id", c['id']).eq("status", "available").execute().data)
            btns.append([TButton.inline(f"🎮 {c['name']} ({c['price']:,}đ) - Kho: {stock}", f"vcat_{c['id']}")])
        
        btns.append([TButton.inline("🔙 QUAY LẠI", b"back")])
        await e.edit("🛒 **CHỌN LOẠI GAME MUỐN MUA:** \n*(Click vào tên game để xem chi tiết và chọn số lượng)*", buttons=btns)

    elif data.startswith("vcat_"):
        cid = int(data.split("_")[1])
        cat = supabase.table("categories").select("*").eq("id", cid).execute().data[0]
        stock = len(supabase.table("codes").select("id").eq("category_id", cid).eq("status", "available").execute().data)
        txt = (f"🎮 **{cat['name']}** \n━━━━━━━━━━━━\n"
               f"📝 {cat['description']}\n\n"
               f"💵 Giá: **{cat['price']:,}đ / 1 Code** \n"
               f"📦 Tồn kho hiện tại: **{stock}** code\n━━━━━━━━━━━━")
        btns = [
            [TButton.inline("🛒 MUA 1 CODE", f"buy_{cid}_1")],
            [TButton.inline("🛒 MUA NHIỀU (TÙY CHỌN)", f"buycustom_{cid}")],
            [TButton.inline("🔙 DANH MỤC", b"list_categories")]
        ]
        await e.edit(txt, buttons=btns)

    elif data.startswith("buycustom_"):
        cid = int(data.split("_")[1])
        cat = supabase.table("categories").select("*").eq("id", cid).execute().data[0]
        stock = len(supabase.table("codes").select("id").eq("category_id", cid).eq("status", "available").execute().data)
        
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message(
                f"🛒 Bạn đang mua code game: **{cat['name']}** \n"
                f"📦 Tồn kho: **{stock}** code\n\n"
                f"👉 **Vui lòng nhắn số lượng code bạn muốn mua (Nhập 1 con số):** "
            )
            try:
                response = await conv.get_response()
                qty = int(response.text.strip())
                if qty <= 0:
                    await conv.send_message("❌ Số lượng không hợp lệ (Phải lớn hơn 0)!", buttons=[[TButton.inline("🔙 TRỞ VỀ DANH MỤC", b"list_categories")]])
                    return
            except ValueError:
                await conv.send_message("❌ Bạn phải nhập một con số!", buttons=[[TButton.inline("🔙 TRỞ VỀ DANH MỤC", b"list_categories")]])
                return
            
            user = db_get_user(uid)
            cost = cat['price'] * qty
            
            if user['balance'] < cost: 
                await conv.send_message(f"❌ Bạn không đủ tiền!\nCần: {cost:,}đ | Số dư: {user['balance']:,}đ", buttons=[[TButton.inline("🏦 NẠP THÊM TIỀN", b"dep_menu")]])
                return
            
            stock_data = supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute().data
            if len(stock_data) < qty: 
                await conv.send_message(f"❌ Kho không đủ code! Chỉ còn {len(stock_data)} code.", buttons=[[TButton.inline("🔙 TRỞ VỀ DANH MỤC", b"list_categories")]])
                return
            
            # Thanh toán
            supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute()
            res_text = f"✅ **MUA THÀNH CÔNG {qty} CODE!** \n🎮 Game: {cat['name']}\n💵 Tổng tiền: -{cost:,}đ\n\n🔑 Code của bạn:\n"
            for c in stock_data:
                supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute()
                res_text += f"`{c['code']}`\n"
            
            await conv.send_message(res_text, buttons=[[TButton.inline("🔙 TRANG CHỦ", b"back")]])

    elif data.startswith("buy_"):
        _, cid, qty = data.split("_")
        cid, qty = int(cid), int(qty)
        cat = supabase.table("categories").select("*").eq("id", cid).execute().data[0]
        user = db_get_user(uid)
        cost = cat['price'] * qty
        
        if user['balance'] < cost: return await e.answer("❌ Bạn không đủ tiền!", alert=True)
        
        stock = supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute().data
        if len(stock) < qty: return await e.answer("❌ Kho không đủ code!", alert=True)
        
        # Thanh toán
        supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute()
        res_text = f"✅ **MUA THÀNH CÔNG!** \n🎮 Game: {cat['name']}\n\n🔑 Code của bạn:\n"
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
        await e.edit(f"📥 Chuyển khoản **{int(amt):,}đ** \n📝 Nội dung: `{uid}`", buttons=[[TButton.url("MỞ APP QUÉT QR", qr)], [TButton.inline("🔙 QUAY LẠI", b"back")]])

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
        await conv.send_message("✅ Đã thêm clone và bắt đầu chạy worker!")
        asyncio.create_task(worker_grab_loop(client, phone))

# ==================== WEBHOOK & NOTIFY ====================
app = Flask(__name__)

@app.route('/sepay-webhook', methods=['POST'])
def webhook():
    d = request.json
    content = d.get("content", "").upper()
    m = re.search(r'(\d{8,12})', content)
    if m:
        uid = int(m.group(1))
        amt = int(d.get("transferAmount", 0))
        user = db_get_user(uid)
        new_bal = user['balance'] + amt
        supabase.table("users").update({"balance": new_bal}).eq("user_id", uid).execute()
        
        # Gửi tin cho khách
    asyncio.run_coroutine_threadsafe(bot.send_message(uid, f"✅ Đã nạp +{amt:,}đ. Số dư: {new_bal:,}đ"), loop)
        
        # Gửi thông báo vào kênh
        channel_id = db_get_setting("NOTIFY_CHANNEL_ID", "")
        if channel_id:
            try:
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(int(channel_id), f"💸 **THÔNG BÁO NẠP TIỀN** \n👤 ID: `{uid}`\n💰 Số tiền: **+{amt:,}đ** "), loop
                )
            except: pass
    return jsonify({"status": "ok"}), 200

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    print("--- BOT ADMIN STARTED ---")
    
    # Load lại toàn bộ clone từ database
    clones = supabase.table("my_clones").select("*").execute().data
    for c in clones:
        try:
            cl = TelegramClient(StringSession(c['session']), API_ID, API_HASH)
            asyncio.create_task(worker_grab_loop(cl, c['phone']))
            print(f"Loaded clone: {c['phone']}")
        except Exception as ex:
            print(f"Lỗi load clone {c.get('phone')}: {ex}")
            
    await bot.run_until_disconnected()

if __name__ == '__main__':
    Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000))), daemon=True).start()
    loop.run_until_complete(main())
