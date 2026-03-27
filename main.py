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
BOT_TOKEN = "8475867709:AAGPINZGRgMnZBRDpNZWPGgBof0fY8N-0D4"

STK_MSB = "96886693002613"

# 👑 ID ADMIN QUẢN TRỊ 
ADMIN_ID = 7816353760 

logging.basicConfig(level=logging.INFO)
bot = TelegramClient(StringSession(), API_ID, API_HASH)

# Event Loop toàn cục cho môi trường Render
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ==================== HELPER FUNCTIONS & DATABASE ====================
def db_get_user(uid):
    res = supabase.table("users").select("*").eq("user_id", uid).execute()
    if not res.data:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Mặc định bảng users giờ chỉ cần user_id và balance
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

# ==================== LOGIC ĐẬP HỘP & THÊM VÀO KHO ====================
async def worker_grab_loop(client, phone):
    try:
        if not client.is_connected(): await client.connect()
        if not await client.is_user_authorized():
            logging.error(f"Clone {phone} die session.")
            return

        # Lắng nghe mọi tin nhắn, ta sẽ check Target động bên trong handler
        @client.on(events.NewMessage())
        @client.on(events.MessageEdited())
        async def handler(ev):
            # Lấy target hiện tại từ Database để có thể thay đổi real-time
            current_target = db_get_setting("BOT_GAME_TARGET", "xocdia88_bot_uytin_bot").replace("@", "")
            
            chat = await ev.get_chat()
            chat_username = getattr(chat, 'username', '')
            
            # Chỉ xử lý nếu tin nhắn đến từ Bot Target
            if chat_username and chat_username.lower() == current_target.lower():
                if ev.reply_markup:
                    for row in ev.reply_markup.rows:
                        for btn in row.buttons:
                            if btn.text and "đập" in btn.text.lower():
                                await asyncio.sleep(random.uniform(0.1, 0.4))
                                try:
                                    click_res = await ev.click(text=btn.text)
                                    code_found = None
                                    
                                    # 1. Bắt code từ Popup
                                    if click_res and getattr(click_res, 'message', None):
                                        if "là:" in click_res.message:
                                            m_search = re.search(r'là:\s*([A-Z0-9]+)', click_res.message)
                                            if m_search: code_found = m_search.group(1)
                                    
                                    # 2. Bắt code từ tin nhắn bot trả về nếu popup không có
                                    if not code_found:
                                        await asyncio.sleep(1.0)
                                        msgs = await client.get_messages(chat.id, limit=2)
                                        for m in msgs:
                                            if m.message and "Mã code của bạn là:" in m.message:
                                                m_match = re.search(r'là:\s*\n?([A-Z0-9]+)', m.message)
                                                if m_match: code_found = m_match.group(1)

                                    # NẾU TÌM THẤY CODE -> ĐƯA VÀO KHO (DATABASE)
                                    if code_found:
                                        supabase.table("codes").insert({
                                            "code": code_found, 
                                            "status": "available", 
                                            "source_phone": phone
                                        }).execute()
                                        
                                        # Báo tin vui cho Admin
                                        await bot.send_message(
                                            ADMIN_ID, 
                                            f"🎊 **KHO VỪA NHẬN CODE MỚI!**\n📱 Clone: `{phone}`\n🔑 Code: `{code_found}`"
                                        )
                                        return
                                except Exception as e:
                                    logging.error(f"Lỗi click {phone}: {e}")
        
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Worker {phone} dừng: {e}")

# ==================== GIAO DIỆN NGƯỜI DÙNG & ADMIN ====================
def main_menu_text(user):
    code_price = int(db_get_setting("CODE_PRICE", "5000"))
    stock_res = supabase.table("codes").select("id").eq("status", "available").execute()
    stock_count = len(stock_res.data)

    return (
        f"🛒 **CỬA HÀNG BÁN CODE TỰ ĐỘNG** 🛒\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 ID Của Bạn: `{user['user_id']}`\n"
        f"💰 Số dư: **{user['balance']:,} VNĐ**\n"
        f"📦 Kho hiện còn: **{stock_count} code**\n"
        f"💵 Giá mỗi code: **{code_price:,} VNĐ**\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

def main_btns(uid):
    btns = [
        [TButton.inline("🛒 MUA CODE NGAY", b"buy_code_menu")],
        [TButton.inline("🏦 NẠP TIỀN", b"dep_menu"), TButton.inline("🕒 LỊCH SỬ MUA", b"history")],
    ]
    # Nút Admin chỉ hiển thị với Admin
    if uid == ADMIN_ID:
        btns.append([TButton.inline("👑 QUẢN TRỊ HỆ THỐNG", b"admin_menu")])
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
            [TButton.inline("📦 QUẢN LÝ KHO CODE", b"admin_stock"), TButton.inline("📱 QUẢN LÝ CLONE", b"admin_clones")],
            [TButton.inline("⚙️ CÀI ĐẶT THÔNG SỐ", b"admin_settings"), TButton.inline("💰 CỘNG/TRỪ TIỀN KHÁCH", b"admin_money")],
            [TButton.inline("🔙 TRANG CHỦ", b"back")]
        ]
        await e.edit("👨‍💻 **MENU QUẢN TRỊ HỆ THỐNG**", buttons=btns)
        
    elif data == "admin_stock":
        if uid != ADMIN_ID: return
        all_codes = supabase.table("codes").select("*").execute().data
        available = [c for c in all_codes if c['status'] == 'available']
        sold = [c for c in all_codes if c['status'] == 'sold']
        
        txt = (
            f"📦 **THỐNG KÊ KHO CODE**\n"
            f"🟢 Đang sẵn sàng: **{len(available)}** code\n"
            f"🔴 Đã bán: **{len(sold)}** code\n"
        )
        btns = [
            [TButton.inline("➕ THÊM CODE THỦ CÔNG", b"admin_add_code")],
            [TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]
        ]
        await e.edit(txt, buttons=btns)

    elif data == "admin_add_code":
        if uid != ADMIN_ID: return
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("📝 Vui lòng nhập Code muốn thêm vào kho:")
            new_code = (await conv.get_response()).text.strip()
            
            supabase.table("codes").insert({
                "code": new_code, 
                "status": "available", 
                "source_phone": "Manual_Admin"
            }).execute()
            await conv.send_message(f"✅ Đã thêm Code `{new_code}` vào kho thành công!")

    elif data == "admin_clones":
        if uid != ADMIN_ID: return
        res = supabase.table("my_clones").select("*").execute()
        btns = [[TButton.inline("➕ THÊM CLONE FARM MỚI", b"add_clone")]]
        
        if res.data:
            btns.extend([[TButton.inline(f"🗑 Xóa {c['phone']}", f"del_clone_{c['id']}")] for c in res.data])
            
        btns.append([TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")])
        await e.edit(f"📱 **DANH SÁCH CLONE ĐANG FARM ({len(res.data)} acc)**", buttons=btns)

    elif data.startswith("del_clone_"):
        if uid != ADMIN_ID: return
        clone_id = data.split("_")[2]
        supabase.table("my_clones").delete().eq("id", clone_id).execute()
        await e.answer("✅ Đã gỡ clone khỏi hệ thống!", alert=True)
        # Load lại trang
        await e.edit("Đã xoá. Vui lòng bấm /start để tải lại.", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])

    elif data == "admin_settings":
        if uid != ADMIN_ID: return
        current_price = db_get_setting("CODE_PRICE", "5000")
        current_target = db_get_setting("BOT_GAME_TARGET", "xocdia88_bot_uytin_bot")
        
        txt = (
            f"⚙️ **CÀI ĐẶT HỆ THỐNG**\n\n"
            f"💵 Giá bán 1 Code: **{int(current_price):,}đ**\n"
            f"🤖 Bot Target Đập Hộp: **@{current_target}**"
        )
        btns = [
            [TButton.inline("SỬA GIÁ BÁN CODE", b"set_price"), TButton.inline("SỬA BOT TARGET", b"set_target")],
            [TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]
        ]
        await e.edit(txt, buttons=btns)

    elif data == "set_price":
        if uid != ADMIN_ID: return
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("💵 Nhập giá bán Code mới (VD: 10000):")
            new_price = (await conv.get_response()).text.strip()
            db_set_setting("CODE_PRICE", new_price)
            await conv.send_message(f"✅ Đã cập nhật giá bán thành: {int(new_price):,}đ")

    elif data == "set_target":
        if uid != ADMIN_ID: return
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("🤖 Nhập Username của Bot Target đập hộp (không chứa @):")
            new_target = (await conv.get_response()).text.strip().replace("@", "")
            db_set_setting("BOT_GAME_TARGET", new_target)
            await conv.send_message(f"✅ Đã cập nhật Bot Target thành: @{new_target}")

    elif data == "admin_money":
        if uid != ADMIN_ID: return
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("👤 Vui lòng nhập ID của khách:")
            try:
                tid = int((await conv.get_response()).text)
                await conv.send_message("💰 Nhập số tiền (Ghi số âm ví dụ -10000 nếu muốn trừ):")
                amt = int((await conv.get_response()).text)
                
                user = db_get_user(tid)
                new_bal = user['balance'] + amt
                supabase.table("users").update({"balance": new_bal}).eq("user_id", tid).execute()
                await conv.send_message(f"✅ Đã cập nhật! Ví của ID `{tid}` hiện tại là: {new_bal:,}đ")
            except Exception as ex:
                await conv.send_message(f"❌ Lỗi: Nhập sai định dạng số. {ex}")

    # ==================== MENU KHÁCH HÀNG MUA CODE ====================
    elif data == "buy_code_menu":
        code_price = int(db_get_setting("CODE_PRICE", "5000"))
        btns = [
            [TButton.inline(f"🛒 Mua 1 Code ({code_price:,}đ)", b"buy_qty_1")],
            [TButton.inline(f"🛒 Mua 5 Code ({code_price*5:,}đ)", b"buy_qty_5")],
            [TButton.inline("🔙 QUAY LẠI", b"back")]
        ]
        await e.edit("🛍 **CHỌN SỐ LƯỢNG MUỐN MUA**", buttons=btns)

    elif data.startswith("buy_qty_"):
        qty = int(data.split("_")[2])
        code_price = int(db_get_setting("CODE_PRICE", "5000"))
        total_cost = code_price * qty
        
        user = db_get_user(uid)
        
        # Kiểm tra tiền
        if user['balance'] < total_cost:
            return await e.answer(f"❌ Ví không đủ tiền! Bạn cần {total_cost:,}đ để mua {qty} code.", alert=True)
            
        # Kiểm tra Kho
        stock_res = supabase.table("codes").select("*").eq("status", "available").limit(qty).execute()
        if len(stock_res.data) < qty:
            return await e.answer(f"❌ Rất tiếc, Kho hiện chỉ còn {len(stock_res.data)} code. Vui lòng quay lại sau!", alert=True)
            
        # Thực hiện thanh toán và giao code
        codes_to_deliver = stock_res.data
        
        # 1. Trừ tiền
        new_balance = user['balance'] - total_cost
        supabase.table("users").update({"balance": new_balance}).eq("user_id", uid).execute()
        
        # 2. Đổi status code thành sold và gửi cho khách
        delivered_text = f"✅ **GIAO DỊCH THÀNH CÔNG!**\nBạn đã mua {qty} code với giá {total_cost:,}đ\n\nDanh sách Code của bạn:\n"
        for idx, c in enumerate(codes_to_deliver, 1):
            supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute()
            delivered_text += f"{idx}. `{c['code']}`\n"
            
        delivered_text += f"\n💰 Số dư còn lại: {new_balance:,}đ"
        
        await e.delete()
        await bot.send_message(uid, delivered_text)
        
        # Thông báo cho Admin có người mua (Tuỳ chọn)
        await bot.send_message(ADMIN_ID, f"🛒 **CÓ KHÁCH MUA CODE!**\n👤 ID Khách: `{uid}`\n📦 SL: {qty} Code\n💵 Doanh thu: +{total_cost:,}đ")

    elif data == "dep_menu":
        btns = [
            [TButton.inline(f"💸 {a:,}đ", f"p_{a}") for a in [10000, 20000, 50000]], 
            [TButton.inline("🔙 QUAY LẠI", b"back")]
        ]
        await e.edit("🏦 **CHỌN MỨC NẠP TIỀN**", buttons=btns)

    elif data.startswith("p_"):
        amt = data.split("_")[1]
        qr = f"https://img.vietqr.io/image/MSB-{STK_MSB}-compact2.png?amount={amt}&addInfo=NAP%20{uid}"
        await e.edit(
            f"📥 **CHUYỂN KHOẢN TỰ ĐỘNG**\n"
            f"💰 Số tiền cần chuyển: **{int(amt):,}đ**\n"
            f"📝 Nội dung: `{uid}` (hoặc NAP {uid})\n\n"
            f"*(Hệ thống sẽ tự động cộng tiền vào ví từ 30s - 1 phút)*", 
            buttons=[[TButton.url("📲 MỞ APP BANK QUÉT MÃ", qr)], [TButton.inline("🔙 QUAY LẠI", b"back")]]
        )
        
    elif data == "history":
        await e.answer("Tính năng Lịch sử đang được cập nhật...", alert=True)

# ==================== LOGIC THÊM CLONE (DÀNH CHO ADMIN) ====================
@bot.on(events.CallbackQuery(data=b"add_clone"))
async def add_clone_process(e):
    uid = e.sender_id
    if uid != ADMIN_ID: return await e.answer("❌ Chức năng chỉ dành cho Admin!", alert=True)

    async with bot.conversation(uid) as conv:
        try:
            await conv.send_message("📞 Nhập số điện thoại Clone (Ví dụ: +84333...):")
            phone = (await conv.get_response()).text.strip().replace(" ", "")
            
            await conv.send_message("⏳ Đang kết nối với Telegram để xin mã OTP, vui lòng chờ...")
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            try:
                await client.send_code_request(phone)
                await conv.send_message("📩 Telegram đã gửi mã OTP! Vui lòng nhập mã:")
            except Exception as req_err:
                await conv.send_message(f"❌ **LỖI KHÔNG GỬI ĐƯỢC OTP!**\nLý do: `{str(req_err)}`")
                return

            otp = (await conv.get_response()).text.strip()
            try:
                await client.sign_in(phone, otp)
            except SessionPasswordNeededError:
                await conv.send_message("🔐 Acc có cài 2FA. Vui lòng nhập mật khẩu 2FA:")
                await client.sign_in(password=(await conv.get_response()).text.strip())

            # Lưu Clone vào Database cho Hệ Thống Farm
            supabase.table("my_clones").insert({
                "owner_id": uid, 
                "phone": phone, 
                "session": client.session.save()
            }).execute()
            
            await conv.send_message(f"✅ Đã thêm clone `{phone}` vào Đội Farm Code thành công!")
            asyncio.create_task(worker_grab_loop(client, phone))
            
        except asyncio.TimeoutError:
            await conv.send_message("❌ Hết thời gian chờ. Vui lòng thao tác lại.")
        except Exception as ex:
            await conv.send_message(f"❌ Lỗi đăng nhập: {str(ex)}")

# ==================== WEBHOOK SEPAY & STARTUP ====================
app = Flask(__name__)
@app.route('/')
def home(): return "Bot Bán Code is Alive", 200

@app.route('/sepay-webhook', methods=['POST'])
def webhook():
    d = request.json
    # Bắt cú pháp NAP 123456 hoặc chỉ ghi 123456 (User ID)
    content_upper = d.get("content", "").upper()
    m = re.search(r'(?:NAP\s+)?(\d{8,12})', content_upper) 
    
    if m:
        uid = int(m.group(1))
        amt = int(d.get("transferAmount", 0))
        
        user = db_get_user(uid)
        new_balance = user['balance'] + amt
        
        supabase.table("users").update({"balance": new_balance}).eq("user_id", uid).execute()
        asyncio.run_coroutine_threadsafe(
            bot.send_message(uid, f"✅ **NẠP TIỀN THÀNH CÔNG!**\n💰 Hệ thống vừa cộng +{amt:,} VNĐ vào ví của bạn.\nSố dư hiện tại: {new_balance:,} VNĐ"), 
            loop
        )
    return jsonify({"status": "ok"}), 200

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    
    # Khởi tạo thông số mặc định nếu chưa có
    db_get_setting("CODE_PRICE", "5000")
    db_get_setting("BOT_GAME_TARGET", "xocdia88_bot_uytin_bot")
    
    try:
        # Tải danh sách Clone từ DB và bắt đầu Farm
        clones = supabase.table("my_clones").select("*").execute()
        print(f">>> Tải thành công {len(clones.data)} Clone, đang khởi động Farm... <<<")
        for c in clones.data:
            cl = TelegramClient(StringSession(c['session']), API_ID, API_HASH)
            asyncio.create_task(worker_grab_loop(cl, c['phone']))
    except Exception as e: 
        print(f"Lỗi khởi chạy clone: {e}")
        
    print(">>> BOT BÁN CODE ĐÃ CHẠY - WEBHOOK SẴN SÀNG <<<")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt: pass
        
