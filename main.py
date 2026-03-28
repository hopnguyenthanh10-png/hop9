import asyncio, re, os, random, logging
from datetime import datetime, timedelta, timezone
from threading import Thread
from flask import Flask, request, jsonify
from telethon import TelegramClient, events, Button as TButton
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from supabase import create_client, Client

# ==================== CẤU HÌNH HỆ THỐNG ====================
SUPABASE_URL = "https://npjjarsmvmqvhdnkvtxc.supabase.co" 
SUPABASE_KEY = "sb_publishable_gVXyT92FL0XpsiiEcerYFQ_RXE3n0ke"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

API_ID = 36437338
API_HASH = "18d34c7efc396d277f3db62baa078efc"
BOT_TOKEN = "8475867709:AAGPINZGRgMnZBRDpNZWPGgBof0fY8N-0D4"

STK_MSB = "96886693002613"
BOT_GAME_TARGET = "xocdia88_bot_uytin_bot"

PRICE_BOT_1D = 10000 
PRICE_BOT_7D = 60000
PRICE_ADD_ACC = 0 

# 👑 ID ADMIN CỦA BẠN (NGUYEN THANH HOP)
ADMIN_ID = 7816353760 

logging.basicConfig(level=logging.INFO)
bot = TelegramClient(StringSession(), API_ID, API_HASH)

# Tạo Event Loop toàn cục để tránh lỗi trên Render
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ==================== HELPER FUNCTIONS ====================
def db_get_user(uid):
    res = supabase.table("users").select("*").eq("user_id", uid).execute()
    if not res.data:
        now_iso = datetime.now(timezone.utc).isoformat()
        supabase.table("users").insert({"user_id": uid, "balance": 0, "bot_expiry": now_iso}).execute()
        return {"user_id": uid, "balance": 0, "bot_expiry": now_iso}
    return res.data[0]

# ==================== LOGIC ĐẬP HỘP (GIỮ NGUYÊN) ====================
async def worker_grab_loop(client, phone, owner_id):
    try:
        if not client.is_connected(): await client.connect()
        if not await client.is_user_authorized():
            logging.error(f"Clone {phone} die.")
            return

        @client.on(events.NewMessage(chats=BOT_GAME_TARGET))
        @client.on(events.MessageEdited(chats=BOT_GAME_TARGET))
        async def handler(ev):
            owner = db_get_user(owner_id)
            expiry = datetime.fromisoformat(owner['bot_expiry'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expiry: return

            if ev.reply_markup:
                for row in ev.reply_markup.rows:
                    for btn in row.buttons:
                        if btn.text and "đập" in btn.text.lower():
                            await asyncio.sleep(random.uniform(0.1, 0.4))
                            try:
                                click_res = await ev.click(text=btn.text)
                                
                                # 1. Bắt code từ Popup
                                if click_res and getattr(click_res, 'message', None):
                                    if "là:" in click_res.message:
                                        code = re.search(r'là:\s*([A-Z0-9]+)', click_res.message).group(1)
                                        await bot.send_message(owner_id, f"🎊 **ACC `{phone}` ĐẬP TRÚNG!**\n🔑 Code: `{code}`")
                                        return
                                
                                # 2. Bắt code từ tin nhắn
                                await asyncio.sleep(1.0)
                                msgs = await client.get_messages(BOT_GAME_TARGET, limit=2)
                                for m in msgs:
                                    if m.message and "Mã code của bạn là:" in m.message:
                                        m_match = re.search(r'là:\s*\n?([A-Z0-9]+)', m.message)
                                        if m_match:
                                            code = m_match.group(1)
                                            await bot.send_message(owner_id, f"🎊 **ACC `{phone}` ĐẬP TRÚNG!**\n🔑 Code: `{code}`")
                                            return
                            except Exception as e:
                                logging.error(f"Lỗi click {phone}: {e}")
        
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Worker {phone} dừng: {e}")

# ==================== GIAO DIỆN NGƯỜI DÙNG ====================
def main_menu_text(user):
    exp_dt = datetime.fromisoformat(user['bot_expiry'].replace('Z', '+00:00'))
    diff = exp_dt - datetime.now(timezone.utc)
    status = "🔴 Hết hạn" if diff.total_seconds() <= 0 else f"🟢 Còn {diff.days}n {diff.seconds//3600}h"
    return (
        f"👑 **HỆ THỐNG BOT ĐẬP HỘP VIP** 👑\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 ID: `{user['user_id']}`\n"
        f"💰 Số dư: **{user['balance']:,} VNĐ**\n"
        f"⏳ Hạn Bot: **{status}**\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

def main_btns(uid):
    btns = [
        [TButton.inline("💎 GIA HẠN BOT", b"renew_menu")],
        [TButton.inline("➕ THÊM ACC MỚI", b"add_clone"), TButton.inline("📱 DS CLONE", b"list_clones")],
        [TButton.inline("🏦 NẠP TIỀN", b"dep_menu"), TButton.inline("👤 VÍ CỦA TÔI", b"me")]
    ]
    # Nút Admin chỉ hiển thị với bạn
    if uid == ADMIN_ID:
        btns.append([TButton.inline("👑 MENU QUẢN TRỊ ADMIN", b"admin_menu")])
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

    # --- MENU ADMIN ---
    elif data == "admin_menu":
        if uid != ADMIN_ID: return
        btns = [
            [TButton.inline("📊 XEM THỐNG KÊ", b"admin_stats"), TButton.inline("💰 CỘNG/TRỪ TIỀN", b"admin_money")],
            [TButton.inline("🔙 QUAY LẠI", b"back")]
        ]
        await e.edit("👨‍💻 **MENU QUẢN TRỊ HỆ THỐNG**", buttons=btns)
        
    elif data == "admin_stats":
        if uid != ADMIN_ID: return
        u_res = supabase.table("users").select("*").execute()
        c_res = supabase.table("my_clones").select("*").execute()
        txt = f"📊 **BẢNG THỐNG KÊ**\n👥 Tổng thành viên: {len(u_res.data)}\n📱 Tổng clone đang treo: {len(c_res.data)}\n💰 Tổng tiền ví: {sum(u['balance'] for u in u_res.data):,}đ"
        await e.edit(txt, buttons=[[TButton.inline("🔙 TRỞ LẠI ADMIN", b"admin_menu")]])

    elif data == "admin_money":
        if uid != ADMIN_ID: return
        await e.delete()
        async with bot.conversation(uid) as conv:
            await conv.send_message("👤 Vui lòng nhập ID của khách cần nạp:")
            tid = int((await conv.get_response()).text)
            await conv.send_message("💰 Nhập số tiền (Ghi số âm ví dụ -10000 nếu muốn trừ):")
            amt = int((await conv.get_response()).text)
            
            user = db_get_user(tid)
            supabase.table("users").update({"balance": user['balance'] + amt}).eq("user_id", tid).execute()
            await conv.send_message(f"✅ Đã cập nhật! Ví của ID `{tid}` hiện tại là: {user['balance'] + amt:,}đ")

    # --- MENU KHÁCH HÀNG ---
    elif data == "renew_menu":
        btns = [[TButton.inline(f"Gói 1 Ngày ({PRICE_BOT_1D:,}đ)", b"buy_1")], [TButton.inline(f"Gói 7 Ngày ({PRICE_BOT_7D:,}đ)", b"buy_7")], [TButton.inline("🔙 QUAY LẠI", b"back")]]
        await e.edit("✨ **CHỌN GÓI GIA HẠN BOT**", buttons=btns)

    elif data.startswith("buy_"):
        days = int(data.split("_")[1])
        cost = PRICE_BOT_1D if days == 1 else PRICE_BOT_7D
        user = db_get_user(uid)
        if user['balance'] < cost: return await e.answer("❌ Ví không đủ tiền!", alert=True)
        
        curr_exp = datetime.fromisoformat(user['bot_expiry'].replace('Z', '+00:00'))
        new_exp = max(curr_exp, datetime.now(timezone.utc)) + timedelta(days=days)
        
        supabase.table("users").update({"balance": user['balance']-cost, "bot_expiry": new_exp.isoformat()}).eq("user_id", uid).execute()
        await e.answer(f"✅ Đã gia hạn thành công {days} ngày!", alert=True)
        await e.edit(main_menu_text(db_get_user(uid)), buttons=main_btns(uid))

    elif data == "dep_menu":
        btns = [[TButton.inline(f"💸 {a:,}đ", f"p_{a}") for a in [10000, 20000, 50000]], [TButton.inline("🔙 QUAY LẠI", b"back")]]
        await e.edit("🏦 **CHỌN MỨC NẠP TIỀN**", buttons=btns)

    elif data.startswith("p_"):
        amt = data.split("_")[1]
        qr = f"https://img.vietqr.io/image/MSB-{STK_MSB}-compact2.png?amount={amt}&addInfo=NAP%20{uid}"
        await e.edit(f"📥 **CHUYỂN KHOẢN**\n💰 Số tiền: {int(amt):,}đ\n📝 Nội dung: `NAP {uid}`", buttons=[[TButton.url("📲 MỞ APP BANK", qr)], [TButton.inline("🔙 QUAY LẠI", b"back")]])

    elif data == "list_clones":
        res = supabase.table("my_clones").select("*").eq("owner_id", uid).execute()
        if not res.data: return await e.answer("❌ Chưa có clone nào!", alert=True)
        btns = [[TButton.inline(f"🗑 Xóa {c['phone']}", f"del_{c['id']}")] for c in res.data]
        btns.append([TButton.inline("🔙 QUAY LẠI", b"back")])
        await e.edit("📱 **DANH SÁCH CLONE**", buttons=btns)

    elif data.startswith("del_"):
        supabase.table("my_clones").delete().eq("id", data.split("_")[1]).execute()
        await e.answer("✅ Đã gỡ clone!", alert=True)
        await cb_handler(e)

# ==================== LOGIC THÊM ACC MỚI ====================
@bot.on(events.CallbackQuery(data=b"add_clone"))
async def add_clone_process(e):
    uid = e.sender_id
    user = db_get_user(uid)
    if user['balance'] < PRICE_ADD_ACC: return await e.answer(f"❌ Cần {PRICE_ADD_ACC:,}đ", alert=True)

    async with bot.conversation(uid) as conv:
        try:
            await conv.send_message("📞 Nhập số điện thoại (Ví dụ: +84333...):")
            phone = (await conv.get_response()).text.strip().replace(" ", "")
            
            await conv.send_message("⏳ Đang kết nối với Telegram để xin mã OTP, vui lòng chờ...")
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            try:
                # Gửi yêu cầu OTP và bắt lỗi chi tiết
                await client.send_code_request(phone)
                await conv.send_message("📩 Telegram đã gửi mã OTP! Vui lòng nhập mã:")
            except Exception as req_err:
                await conv.send_message(f"❌ **LỖI KHÔNG GỬI ĐƯỢC OTP!**\nLý do: `{str(req_err)}`\n\n*(Lưu ý: Nếu lỗi là 'FloodWait' hoặc 'Phone Banned', có thể do IP của máy chủ Render bị Telegram chặn tạm thời).*")
                return

            otp = (await conv.get_response()).text.strip()
            try:
                await client.sign_in(phone, otp)
            except SessionPasswordNeededError:
                await conv.send_message("🔐 Acc có cài 2FA. Vui lòng nhập mật khẩu 2FA:")
                await client.sign_in(password=(await conv.get_response()).text.strip())

            # Lưu vào Database
            supabase.table("users").update({"balance": user['balance'] - PRICE_ADD_ACC}).eq("user_id", uid).execute()
            supabase.table("my_clones").insert({"owner_id": uid, "phone": phone, "session": client.session.save()}).execute()
            
            await conv.send_message(f"✅ Đã thêm clone `{phone}` thành công!")
            asyncio.create_task(worker_grab_loop(client, phone, uid))
            
        except asyncio.TimeoutError:
            await conv.send_message("❌ Hết thời gian chờ. Vui lòng thao tác lại.")
        except Exception as ex:
            await conv.send_message(f"❌ Lỗi đăng nhập: {str(ex)}")

# ==================== WEBHOOK & STARTUP ====================
app = Flask(__name__)
@app.route('/')
def home(): return "Bot is Alive", 200

@app.route('/sepay-webhook', methods=['POST'])
def webhook():
    d = request.json
    m = re.search(r'NAP\s+(\d+)', d.get("content", "").upper())
    if m:
        uid, amt = int(m.group(1)), int(d.get("transferAmount", 0))
        user = db_get_user(uid)
        supabase.table("users").update({"balance": user['balance'] + amt}).eq("user_id", uid).execute()
        asyncio.run_coroutine_threadsafe(bot.send_message(uid, f"✅ **NẠP TIỀN THÀNH CÔNG!**\n💰 +{amt:,} VNĐ"), loop)
    return jsonify({"status": "ok"}), 200

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    try:
        clones = supabase.table("my_clones").select("*").execute()
        for c in clones.data:
            cl = TelegramClient(StringSession(c['session']), API_ID, API_HASH)
            asyncio.create_task(worker_grab_loop(cl, c['phone'], c['owner_id']))
    except: pass
    print(">>> BOT ĐANG CHẠY - GIAO DIỆN ADMIN ĐÃ CẬP NHẬT <<<")
    await bot.run_until_disconnected()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    Thread(target=lambda: app.run(host='0.0.0.0', port=port, use_reloader=False), daemon=True).start()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt: pass
                            
