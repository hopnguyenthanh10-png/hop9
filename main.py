import asyncio
import re
import os
import random
import logging
import urllib.request
import time
from datetime import datetime, timezone, timedelta
from threading import Thread
from flask import Flask, request, jsonify
from telethon import TelegramClient, events, Button as TButton
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from supabase import create_client, Client

app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
    
# ---> THÊM: CẤU HÌNH GIỜ VIỆT NAM (GMT+7)
VN_TZ = timezone(timedelta(hours=7))

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

# Thêm biến Cache Global để chống rate limit Supabase
cached_categories = []
last_cache_time = 0

# ==================== HELPER FUNCTIONS & DATABASE ====================
async def db_get_user(uid):
    try:
        res = await asyncio.to_thread(lambda: supabase.table("users").select("*").eq("user_id", uid).execute())
        if not res.data:
            await asyncio.to_thread(lambda: supabase.table("users").insert({"user_id": uid, "balance": 0}).execute())
            return {"user_id": uid, "balance": 0}
        return res.data[0]
    except Exception as e:
        logging.error(f"Lỗi db_get_user: {e}")
        return {"user_id": uid, "balance": 0}

def sync_db_get_user(uid):
    try:
        res = supabase.table("users").select("*").eq("user_id", uid).execute()
        if not res.data:
            supabase.table("users").insert({"user_id": uid, "balance": 0}).execute()
            return {"user_id": uid, "balance": 0}
        return res.data[0]
    except Exception as e:
        logging.error(f"Lỗi sync_db_get_user: {e}")
        return {"user_id": uid, "balance": 0}

async def db_get_setting(key, default_value):
    try:
        res = await asyncio.to_thread(lambda: supabase.table("settings").select("value").eq("key", key).execute())
        if not res.data:
            await asyncio.to_thread(lambda: supabase.table("settings").insert({"key": key, "value": str(default_value)}).execute())
            return str(default_value)
        return res.data[0]['value']
    except Exception as e:
        logging.error(f"Lỗi db_get_setting: {e}")
        return str(default_value)

def sync_db_get_setting(key, default_value):
    try:
        res = supabase.table("settings").select("value").eq("key", key).execute()
        if not res.data:
            supabase.table("settings").insert({"key": key, "value": str(default_value)}).execute()
            return str(default_value)
        return res.data[0]['value']
    except Exception as e:
        logging.error(f"Lỗi sync_db_get_setting: {e}")
        return str(default_value)

async def db_set_setting(key, value):
    try:
        res = await asyncio.to_thread(lambda: supabase.table("settings").select("value").eq("key", key).execute())
        if not res.data:
            await asyncio.to_thread(lambda: supabase.table("settings").insert({"key": key, "value": str(value)}).execute())
        else:
            await asyncio.to_thread(lambda: supabase.table("settings").update({"value": str(value)}).eq("key", key).execute())
    except Exception as e:
        logging.error(f"Lỗi db_set_setting: {e}")

# ==================== LOGIC THÔNG BÁO KÊNH & LỊCH SỬ ====================
async def send_channel_notify(text):
    channel_id_str = await db_get_setting("NOTIFY_CHANNEL_ID", "Chưa cài đặt")
    if channel_id_str and channel_id_str != "Chưa cài đặt":
        try:
            await bot.send_message(int(channel_id_str), text)
        except Exception as e:
            logging.error(f"Lỗi gửi thông báo kênh: {e}")

def sync_send_channel_notify(text):
    channel_id_str = sync_db_get_setting("NOTIFY_CHANNEL_ID", "Chưa cài đặt")
    if channel_id_str and channel_id_str != "Chưa cài đặt":
        try:
            asyncio.run_coroutine_threadsafe(bot.send_message(int(channel_id_str), text), loop)
        except Exception as e:
            logging.error(f"Lỗi gửi thông báo kênh sync: {e}")

async def db_add_history(uid, action, game_name, qty, amount, codes_list=""):
    try:
        now_str = datetime.now(timezone.utc).isoformat()
        await asyncio.to_thread(lambda: supabase.table("history").insert({
            "user_id": uid, "action": action, "game_name": game_name, 
            "qty": qty, "amount": amount, "codes_list": codes_list, "created_at": now_str
        }).execute())
    except Exception as e:
        logging.error(f"Lỗi lưu lịch sử: {e}")

def sync_db_add_history(uid, action, game_name, qty, amount, codes_list=""):
    try:
        now_str = datetime.now(timezone.utc).isoformat()
        supabase.table("history").insert({
            "user_id": uid, "action": action, "game_name": game_name, 
            "qty": qty, "amount": amount, "codes_list": codes_list, "created_at": now_str
        }).execute()
    except Exception as e:
        logging.error(f"Lỗi lưu lịch sử sync: {e}")

async def auto_clean_history():
    while True:
        try:
            # Xóa các lịch sử cũ hơn 24 giờ (Bao gồm cả code đã mua để bảo mật)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            await asyncio.to_thread(lambda: supabase.table("history").delete().lt("created_at", yesterday).execute())
        except Exception as e:
            logging.error(f"Lỗi tự động xóa lịch sử cũ: {e}")
        await asyncio.sleep(3600) # Cứ 1 tiếng quét dọn 1 lần

# ==================== LOGIC ĐẬP HỘP ĐA DANH MỤC (CLONE WORKER) ====================
async def worker_grab_loop(client, phone):
    global cached_categories, last_cache_time
    try:
        if not client.is_connected(): 
            await client.connect()
            
        if not await client.is_user_authorized():
            logging.error(f"Clone {phone} đã chết session (bị đăng xuất).")
            # Cập nhật trạng thái clone trong DB
            await asyncio.to_thread(lambda: supabase.table("my_clones").update({"status": "dead"}).eq("phone", phone).execute())
            await bot.send_message(ADMIN_ID, f"⚠️ **CẢNH BÁO CLONE CHẾT**\nClone `{phone}` đã bị văng session. Vui lòng nạp lại!")
            return

        try:
            cats_res = await asyncio.to_thread(lambda: supabase.table("categories").select("target_bot").execute())
            cats = cats_res.data
            if cats:
                for c in cats:
                    if c.get('target_bot'):
                        try:
                            await client.send_message(c['target_bot'], "/start")
                            await asyncio.sleep(1.5) 
                        except Exception as start_err:
                            logging.warning(f"Clone {phone} không thể gửi /start tới {c['target_bot']}: {start_err}")
        except Exception as e:
            logging.error(f"Lỗi khi auto-start bot mục tiêu cho {phone}: {e}")

        @client.on(events.NewMessage())
        @client.on(events.MessageEdited())
        async def handler(ev):
            global cached_categories, last_cache_time
            if not ev.reply_markup: 
                return
            
            chat = await ev.get_chat()
            chat_username = getattr(chat, 'username', '')
            if not chat_username: 
                return

            try:
                # Cập nhật cache mỗi 60 giây để chống rate limit Supabase
                current_time = time.time()
                if current_time - last_cache_time > 60 or not cached_categories:
                    cats_data = await asyncio.to_thread(lambda: supabase.table("categories").select("*").execute())
                    if cats_data and getattr(cats_data, 'data', None):
                        cached_categories = cats_data.data
                    last_cache_time = current_time

                if not cached_categories: 
                    return
                
                matched_cat = next((c for c in cached_categories if c.get('target_bot') and c['target_bot'].lower() == chat_username.lower()), None)
                
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
                                            if m_search: 
                                                code_found = m_search.group(1)
                                    
                                    if not code_found:
                                        await asyncio.sleep(1.0)
                                        msgs = await client.get_messages(chat.id, limit=2)
                                        for m in msgs:
                                            if m.message and "Mã code của bạn là:" in m.message:
                                                m_match = re.search(r'là:\s*\n?([A-Z0-9]+)', m.message)
                                                if m_match: 
                                                    code_found = m_match.group(1)

                                    if code_found:
                                        await asyncio.to_thread(lambda: supabase.table("codes").insert({
                                            "code": code_found, 
                                            "status": "available", 
                                            "source_phone": phone,
                                            "category_id": matched_cat['id']
                                        }).execute())
                                        
                                        await bot.send_message(
                                            ADMIN_ID, 
                                            f"🎊 **NHẬN CODE MỚI!** \n🎮 Danh mục: **{matched_cat['name']}** \n📱 Clone: `{phone}`\n🔑 Code: `{code_found}`"
                                        )
                                        return
                                except Exception as e:
                                    logging.error(f"Lỗi click đập hộp của {phone}: {e}")
            except Exception as outer_e:
                logging.error(f"Lỗi xử lý tin nhắn đập hộp: {outer_e}")
                
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Worker của clone {phone} đã dừng: {e}")

# ==================== GIAO DIỆN NGƯỜI DÙNG ====================
async def main_menu_text(user):
    bot_intro = await db_get_setting("BOT_INTRO", "Chào mừng bạn đến với hệ thống bán code tự động!")
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
        [TButton.inline("🏦 NẠP TIỀN", b"dep_menu"), TButton.inline("🕒 LỊCH SỬ GIAO DỊCH", b"history")],
        [TButton.inline("🏆 BẢNG XẾP HẠNG (TOP)", b"top_users")], # ---> THÊM NÚT TOP VÀO MAIN MENU
    ]
    if uid == ADMIN_ID:
        btns.append([TButton.inline("👑 QUẢN TRỊ ADMIN", b"admin_menu")])
    return btns

@bot.on(events.NewMessage(pattern="/start"))
async def start(e):
    user = await db_get_user(e.sender_id)
    text = await main_menu_text(user)
    await e.respond(text, buttons=main_btns(e.sender_id))

@bot.on(events.CallbackQuery)
async def cb_handler(e):
    uid = e.sender_id
    data = e.data.decode()

    # XỬ LÝ NÚT TRANG CHỦ
    if data == "back":
        await e.answer() 
        user = await db_get_user(uid)
        text = await main_menu_text(user)
        await e.edit(text, buttons=main_btns(uid))

    # ---> THÊM: LOGIC XEM TOP NGƯỜI CHƠI
    elif data == "top_users":
        await e.answer()
        try:
            # Lấy top 10 theo số dư (balance) để ko cần đổi DB. (Nếu ae dùng total_deposited thì sửa chữ "balance" thành "total_deposited")
            res = await asyncio.to_thread(lambda: supabase.table("users").select("*").order("balance", desc=True).limit(10).execute())
            if not getattr(res, 'data', None):
                await e.edit("🏆 Hệ thống chưa có dữ liệu TOP.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])
                return
            
            txt = "🏆 **BẢNG XẾP HẠNG ĐẠI GIA (TOP)** 🏆\n━━━━━━━━━━━━━━━━━━\n"
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]
            for i, u in enumerate(res.data):
                txt += f"{medals[i]} ID: `{u['user_id']}` - Điểm/Số dư: **{u['balance']:,}**\n"
            txt += "━━━━━━━━━━━━━━━━━━\n🕒 Cập nhật lúc: " + datetime.now(VN_TZ).strftime('%H:%M %d/%m/%Y')
            
            await e.edit(txt, buttons=[[TButton.inline("🔙 QUAY LẠI TRANG CHỦ", b"back")]])
        except Exception as ex:
            logging.error(f"Lỗi xem TOP: {ex}")
            await e.edit("❌ Lỗi tải bảng xếp hạng.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])

    # XỬ LÝ MENU ADMIN
    elif data == "admin_menu":
        await e.answer() 
        if uid != ADMIN_ID: 
            return
        btns = [
            [TButton.inline("📂 QUẢN LÝ DANH MỤC", b"admin_cats"), TButton.inline("📱 QUẢN LÝ CLONE", b"admin_clones")],
            [TButton.inline("⚙️ CÀI ĐẶT CHUNG", b"admin_settings"), TButton.inline("💰 CỘNG/TRỪ TIỀN", b"admin_money")],
            [TButton.inline("🕵️ CHECK LỊCH SỬ GD", b"admin_check_history")],
            [TButton.inline("🏆 BẮN THÔNG BÁO TOP KÊNH", b"admin_notify_top")], # ---> THÊM NÚT THÔNG BÁO TOP CHO ADMIN
            [TButton.inline("🔙 TRANG CHỦ", b"back")]
        ]
        await e.edit("👨‍💻 **BẢNG ĐIỀU KHIỂN ADMIN** ", buttons=btns)

    # ---> THÊM: LOGIC ADMIN BẮN THÔNG BÁO TOP LÊN KÊNH
    elif data == "admin_notify_top":
        await e.answer()
        if uid != ADMIN_ID: return
        try:
            res = await asyncio.to_thread(lambda: supabase.table("users").select("*").order("balance", desc=True).limit(5).execute())
            if not getattr(res, 'data', None):
                await e.edit("❌ Chưa có dữ liệu TOP để thông báo.", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])
                return
            
            txt = "🏆 **VINH DANH TOP ĐẠI GIA HÔM NAY** 🏆\n━━━━━━━━━━━━━━━━━━\n"
            medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
            for i, u in enumerate(res.data):
                txt += f"{medals[i]} Người chơi: `{u['user_id']}` - Điểm/Số dư: **{u['balance']:,}**\n"
            txt += "━━━━━━━━━━━━━━━━━━\n🎉 Cảm ơn các anh em đã luôn đồng hành và ủng hộ hệ thống!"
            
            await send_channel_notify(txt)
            await e.edit("✅ Đã bắn thông báo TOP lên kênh thành công!", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])
        except Exception as ex:
            logging.error(f"Lỗi bắn thông báo TOP: {ex}")
            await e.edit("❌ Lỗi khi gửi thông báo.", buttons=[[TButton.inline("🔙", b"admin_menu")]])

    # XỬ LÝ ADMIN CHECK LỊCH SỬ
    elif data == "admin_check_history":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("🕵️ Nhập ID khách hàng cần kiểm tra lịch sử:")
                check_uid = int((await conv.get_response()).text.strip())
                
                res = await asyncio.to_thread(lambda: supabase.table("history").select("*").eq("user_id", check_uid).order("created_at", desc=True).limit(20).execute())
                if not getattr(res, 'data', None):
                    await conv.send_message(f"❌ Khách hàng `{check_uid}` không có giao dịch nào trong 24h qua.", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])
                    return
                
                txt = f"🕵️ **LỊCH SỬ CỦA USER: `{check_uid}`**\n━━━━━━━━━━━━━━━━━━\n"
                for h in res.data:
                    dt = datetime.fromisoformat(h['created_at'].replace('Z', '+00:00'))
                    time_str = dt.astimezone(VN_TZ).strftime('%H:%M %d/%m') # ---> FIX GIỜ VN
                    if h['action'] == "Nạp tiền":
                        txt += f"🔹 `{time_str}` | Nạp tiền: **+{h['amount']:,}đ**\n"
                    else:
                        txt += f"🔸 `{time_str}` | Mua {h['qty']} code {h['game_name']} **(-{h['amount']:,}đ)**\n"
                        if h.get('codes_list'):
                            txt += f"   🔑 Code xuất ra: `{h['codes_list']}`\n"
                
                await conv.send_message(txt, buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])
            except ValueError:
                await conv.send_message("❌ ID phải là số!", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])
            except Exception as ex:
                logging.error(f"Lỗi admin check lịch sử: {ex}")
                await conv.send_message("❌ Lỗi truy xuất cơ sở dữ liệu!", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])

    # XỬ LÝ QUẢN LÝ CLONE
    elif data == "admin_clones":
        await e.answer()
        if uid != ADMIN_ID: 
            return
        try:
            # FIX TẠI ĐÂY: Thêm .range(0, 1000) để không bị kẹt ở 100 clone
            res = await asyncio.to_thread(lambda: supabase.table("my_clones").select("*").range(0, 1000).execute())
            btns = [[TButton.inline("➕ THÊM CLONE MỚI", b"add_clone")]]
            if getattr(res, 'data', None):
                for c in res.data:
                    status_icon = "🟢" if c['status'] == 'active' else "🔴"
                    btns.append([TButton.inline(f"{status_icon} Xóa {c['phone']}", f"del_clone_{c['id']}")])
            btns.append([TButton.inline("🔙 QUAY LẠI", b"admin_menu")])
            await e.edit(f"📱 **QUẢN LÝ CLONE ({len(res.data) if getattr(res, 'data', None) else 0} acc)** ", buttons=btns)
        except Exception as ex:
            logging.error(f"Lỗi admin_clones: {ex}")
            await e.edit("❌ Lỗi lấy dữ liệu clone.", buttons=[[TButton.inline("🔙", b"admin_menu")]])

    elif data.startswith("del_clone_"):
        try:
            cid = data.split("_")[2]
            await asyncio.to_thread(lambda: supabase.table("my_clones").delete().eq("id", cid).execute())
            await e.answer("✅ Đã xóa clone!", alert=True)
            
            # FIX TẠI ĐÂY: Reload lại trang cũng phải có .range(0, 1000)
            res = await asyncio.to_thread(lambda: supabase.table("my_clones").select("*").range(0, 1000).execute())
            btns = [[TButton.inline("➕ THÊM CLONE MỚI", b"add_clone")]]
            if getattr(res, 'data', None):
                for c in res.data:
                    status_icon = "🟢" if c['status'] == 'active' else "🔴"
                    btns.append([TButton.inline(f"{status_icon} Xóa {c['phone']}", f"del_clone_{c['id']}")])
            btns.append([TButton.inline("🔙 QUAY LẠI", b"admin_menu")])
            await e.edit(f"📱 **QUẢN LÝ CLONE ({len(res.data) if getattr(res, 'data', None) else 0} acc)** ", buttons=btns)
        except Exception as ex:
            logging.error(f"Lỗi xóa clone: {ex}")

    # XỬ LÝ CÀI ĐẶT
    elif data == "admin_settings":
        await e.answer()
        if uid != ADMIN_ID: 
            return
        intro = await db_get_setting("BOT_INTRO", "Chưa cài đặt")
        channel = await db_get_setting("NOTIFY_CHANNEL_ID", "Chưa cài đặt")
        txt = (f"⚙️ **CÀI ĐẶT HỆ THỐNG** \n\n"
               f"1️⃣ **Lời chào:** {intro}\n"
               f"2️⃣ **ID Kênh thông báo:** `{channel}`")
        btns = [
            [TButton.inline("SỬA LỜI CHÀO", b"set_intro"), TButton.inline("SỬA KÊNH THÔNG BÁO", b"set_channel")],
            [TButton.inline("🔙 QUAY LẠI", b"admin_menu")]
        ]
        await e.edit(txt, buttons=btns)

    elif data == "set_intro":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("📝 Nhập lời chào mới:")
                response = await conv.get_response()
                await db_set_setting("BOT_INTRO", response.text.strip())
                await conv.send_message("✅ Đã cập nhật thành công!", buttons=[[TButton.inline("🔙 CÀI ĐẶT", b"admin_settings")]])
            except Exception as ex:
                await conv.send_message("❌ Đã quá thời gian chờ hoặc có lỗi xảy ra.")

    elif data == "set_channel":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("📢 Nhập ID Kênh (Ví dụ: -100xxx):")
                response = await conv.get_response()
                await db_set_setting("NOTIFY_CHANNEL_ID", response.text.strip())
                await conv.send_message("✅ Đã cập nhật thành công!", buttons=[[TButton.inline("🔙 CÀI ĐẶT", b"admin_settings")]])
            except Exception as ex:
                await conv.send_message("❌ Đã quá thời gian chờ hoặc có lỗi xảy ra.")

    # XỬ LÝ QUẢN LÝ DANH MỤC
    elif data == "admin_cats":
        await e.answer()
        if uid != ADMIN_ID: 
            return
        try:
            cats_res = await asyncio.to_thread(lambda: supabase.table("categories").select("*").execute())
            cats = cats_res.data
            
            if not cats:
                txt = "📂 **DANH SÁCH GAME CỦA SHOP** \n\n❌ Hiện tại kho chưa có game nào. Hãy thêm mới!"
            else:
                txt = "📂 **DANH SÁCH GAME CỦA SHOP** \n━━━━━━━━━━━━━━━━━━\n"
                for c in cats:
                    try:
                        count_res = await asyncio.to_thread(lambda: supabase.table("codes").select("id", count='exact').eq("category_id", c['id']).eq("status", "available").limit(1).execute())
                        stock = count_res.count if count_res.count is not None else 0
                    except Exception as count_err:
                        logging.error(f"Lỗi đếm code danh mục {c['id']}: {count_err}")
                        stock = "Lỗi"

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
        except Exception as ex:
            logging.error(f"Lỗi tải danh mục admin: {ex}")
            await e.edit("❌ Lỗi truy xuất cơ sở dữ liệu.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"admin_menu")]])

    elif data == "add_cat":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("🎮 Nhập Tên Game Mới:")
                name = (await conv.get_response()).text.strip()
                
                await conv.send_message("💰 Nhập Giá bán (Chỉ điền số, VD: 15000):")
                price = int((await conv.get_response()).text.strip())
                
                await conv.send_message("🤖 Nhập Username Bot Đập Hộp (Bỏ chữ @ đi, VD: kiemtienbot):")
                bot_target = (await conv.get_response()).text.strip().replace("@", "")
                
                await conv.send_message("📝 Nhập Mô tả ngắn gọn cho Game:")
                desc = (await conv.get_response()).text.strip()
                
                await asyncio.to_thread(lambda: supabase.table("categories").insert({"name": name, "price": price, "target_bot": bot_target, "description": desc}).execute())
                await conv.send_message(f"✅ Đã tạo game thành công: **{name}**", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"admin_cats")]])
            except ValueError:
                await conv.send_message("❌ Lỗi: Giá bán phải là một con số!", buttons=[[TButton.inline("🔙 LÀM LẠI", b"admin_cats")]])
            except Exception as ex:
                logging.error(f"Lỗi tạo category: {ex}")
                await conv.send_message("❌ Có lỗi xảy ra trong quá trình tạo!", buttons=[[TButton.inline("🔙 LÀM LẠI", b"admin_cats")]])

    elif data == "edit_cat_price":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("✏️ Nhập ID của game cần sửa giá (Xem ID ở mục Quản lý danh mục):")
                cid = int((await conv.get_response()).text.strip())
                
                await conv.send_message("💰 Nhập GIÁ BÁN MỚI (Chỉ ghi số):")
                new_price = int((await conv.get_response()).text.strip())
                
                await asyncio.to_thread(lambda: supabase.table("categories").update({"price": new_price}).eq("id", cid).execute())
                await conv.send_message("✅ Đã cập nhật giá mới thành công!", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"admin_cats")]])
            except ValueError:
                await conv.send_message("❌ Lỗi: ID và Giá tiền phải là số!")
            except Exception as ex:
                logging.error(f"Lỗi sửa giá: {ex}")
                await conv.send_message("❌ Lỗi kết nối CSDL!")

    elif data == "del_cat":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("🗑 Nhập ID game cần XÓA BỎ HOÀN TOÀN:")
                cid = int((await conv.get_response()).text.strip())
                
                await asyncio.to_thread(lambda: supabase.table("codes").delete().eq("category_id", cid).execute())
                await asyncio.to_thread(lambda: supabase.table("categories").delete().eq("id", cid).execute())
                
                await conv.send_message("✅ Đã xóa game và toàn bộ code của game đó!", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"admin_cats")]])
            except ValueError:
                await conv.send_message("❌ Lỗi: ID phải là số!")
            except Exception as ex:
                logging.error(f"Lỗi xóa game: {ex}")
                await conv.send_message("❌ Lỗi không thể xóa!")

    elif data == "add_manual_codes":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("📦 Nhập ID Danh mục (Game) muốn thêm code vào:")
                cat_id = int((await conv.get_response()).text.strip())
                
                await conv.send_message("👉 Gửi danh sách code (Mỗi code nằm trên 1 dòng riêng biệt):")
                codes_msg = await conv.get_response()
                raw_codes = codes_msg.text.strip().split('\n')
                
                insert_data = []
                for c in raw_codes:
                    if c.strip():
                        insert_data.append({"code": c.strip(), "status": "available", "source_phone": "Admin", "category_id": cat_id})
                
                if insert_data:
                    await asyncio.to_thread(lambda: supabase.table("codes").insert(insert_data).execute())
                    await conv.send_message(f"✅ Đã nạp thành công {len(insert_data)} code tay!", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"admin_cats")]])
                else:
                    await conv.send_message("❌ Bạn chưa nhập code nào hợp lệ.", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"admin_cats")]])
            except ValueError:
                await conv.send_message("❌ Lỗi: ID Danh mục phải là số!")
            except Exception as ex:
                logging.error(f"Lỗi thêm code tay: {ex}")
                await conv.send_message("❌ Lỗi hệ thống khi thêm code!")

    elif data == "admin_money":
        await e.answer()
        await e.delete()
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("👤 Nhập ID khách hàng cần cộng/trừ tiền:")
                tid = int((await conv.get_response()).text.strip())
                
                await conv.send_message("💰 Nhập số tiền (Cộng thêm thì ghi 50000, Trừ đi thì ghi -50000):")
                amt = int((await conv.get_response()).text.strip())
                
                user = await db_get_user(tid)
                new_balance = user['balance'] + amt
                
                await asyncio.to_thread(lambda: supabase.table("users").update({"balance": new_balance}).eq("user_id", tid).execute())
                await conv.send_message(f"✅ Thành công! Số dư mới của khách {tid} là: {new_balance:,}đ", buttons=[[TButton.inline("🔙 QUAY LẠI ADMIN", b"admin_menu")]])
            except ValueError:
                await conv.send_message("❌ ID và Số tiền phải là chữ số!")
            except Exception as ex:
                logging.error(f"Lỗi cộng tiền admin: {ex}")
                await conv.send_message("❌ Lỗi cơ sở dữ liệu!")

    # XỬ LÝ LỊCH SỬ CHO THÀNH VIÊN (XEM LẠI CODE TRONG 24H)
    elif data == "history":
        await e.answer()
        try:
            res = await asyncio.to_thread(lambda: supabase.table("history").select("*").eq("user_id", uid).order("created_at", desc=True).limit(10).execute())
            hist_data = res.data
            
            if not hist_data:
                await e.edit("🕒 Bạn chưa có giao dịch nào trong 24h qua.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])
                return
            
            txt = "🕒 **LỊCH SỬ GIAO DỊCH (24H QUA)**\n━━━━━━━━━━━━━━━━━━\n"
            for h in hist_data:
                dt = datetime.fromisoformat(h['created_at'].replace('Z', '+00:00'))
                time_str = dt.astimezone(VN_TZ).strftime('%H:%M %d/%m') # ---> FIX GIỜ VN
                
                if h['action'] == "Nạp tiền":
                    txt += f"🔹 `{time_str}` | Nạp tiền: **+{h['amount']:,}đ**\n"
                else:
                    txt += f"🔸 `{time_str}` | Mua **{h['qty']}** {h['game_name']} (-{h['amount']:,}đ)\n"
                    if h.get('codes_list'):
                        txt += f"   🔑 Mã Code: `{h['codes_list']}`\n"
            
            txt += "━━━━━━━━━━━━━━━━━━\n*(Dữ liệu lịch sử và mã code sẽ tự động xóa sạch sau 24h để bảo mật)*"
            await e.edit(txt, buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])
        except Exception as ex:
            logging.error(f"Lỗi xem lịch sử: {ex}")
            await e.edit("❌ Lỗi tải lịch sử, vui lòng thử lại.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])

    elif data == "list_categories":
        await e.answer()
        try:
            cats_res = await asyncio.to_thread(lambda: supabase.table("categories").select("*").execute())
            cats = cats_res.data
            
            if not cats: 
                await e.edit("❌ Shop hiện tại chưa có danh mục game nào đang bán.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])
                return 
            
            btns = []
            for c in cats:
                try:
                    count_res = await asyncio.to_thread(lambda: supabase.table("codes").select("id", count='exact').eq("category_id", c['id']).eq("status", "available").limit(1).execute())
                    stock = count_res.count if count_res.count is not None else 0
                except:
                    stock = 0
                
                status = f"Kho: {stock}" if stock > 0 else "🔴 HẾT HÀNG"
                btns.append([TButton.inline(f"🎮 {c['name']} - {c['price']:,}đ ({status})", f"vcat_{c['id']}")])
            
            btns.append([TButton.inline("🔙 QUAY LẠI", b"back")])
            await e.edit("🛒 **DANH SÁCH GAME ĐANG BÁN:**", buttons=btns)
        except Exception as ex:
            logging.error(f"Lỗi list_categories: {ex}")
            await e.edit("❌ Lỗi tải danh mục.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])

    elif data.startswith("vcat_"):
        await e.answer()
        try:
            cid = int(data.split("_")[1])
            cat_res = await asyncio.to_thread(lambda: supabase.table("categories").select("*").eq("id", cid).execute())
            
            if not getattr(cat_res, 'data', None):
                await e.edit("❌ Danh mục này không tồn tại hoặc đã bị xóa.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"list_categories")]])
                return

            cat = cat_res.data[0]
            
            try:
                count_res = await asyncio.to_thread(lambda: supabase.table("codes").select("id", count='exact').eq("category_id", cid).eq("status", "available").limit(1).execute())
                stock = count_res.count if count_res.count is not None else 0
            except:
                stock = 0
                
            txt = (f"🎮 **{cat['name']}** \n━━━━━━━━━━━━\n"
                   f"📝 {cat['description']}\n\n"
                   f"💵 Giá bán: **{cat['price']:,}đ** \n"
                   f"📦 Tồn kho hiện tại: **{stock}** code")
            
            btns = [
                [TButton.inline("🛒 MUA 1 CODE", f"buy_{cid}_1")],
                [TButton.inline("🛒 MUA NHIỀU CODE", f"buycustom_{cid}")],
                [TButton.inline("🔙 QUAY LẠI DANH MỤC", b"list_categories")]
            ]
            await e.edit(txt, buttons=btns)
        except Exception as ex:
            logging.error(f"Lỗi vcat_: {ex}")
            await e.edit("❌ Lỗi truy xuất thông tin game.", buttons=[[TButton.inline("🔙", b"list_categories")]])

    # XỬ LÝ MUA SỐ LƯỢNG TÙY CHỌN (Đã fix lỗi bị thiếu trong bản cũ)
    elif data.startswith("buycustom_"):
        await e.answer()
        await e.delete()
        cid = int(data.split("_")[1])
        async with bot.conversation(uid) as conv:
            try:
                await conv.send_message("🔢 Bạn muốn mua bao nhiêu code? Vui lòng nhập số lượng (VD: 5):")
                response = await conv.get_response()
                qty = int(response.text.strip())
                if qty <= 0: raise ValueError
                
                # Sau khi nhập xong, chuyển hướng sang hàm mua thực tế
                await process_purchase(e, uid, cid, qty, conv)
            except ValueError:
                await conv.send_message("❌ Lỗi: Vui lòng chỉ nhập số lượng hợp lệ!", buttons=[[TButton.inline("🔙 QUAY LẠI", b"list_categories")]])
            except Exception as ex:
                logging.error(f"Lỗi buycustom: {ex}")
                await conv.send_message("❌ Quá thời gian chờ hoặc có lỗi xảy ra.", buttons=[[TButton.inline("🔙", b"list_categories")]])

    # XỬ LÝ MUA CODE CỐ ĐỊNH (Đã fix lỗi thụt lề và Thêm chức năng xuất List Code)
    elif data.startswith("buy_"):
        await e.answer()
        parts = data.split("_")
        cid = int(parts[1])
        qty = int(parts[2]) 
        await process_purchase(e, uid, cid, qty, None)

    # XỬ LÝ NẠP TIỀN
    elif data == "dep_menu":
        await e.answer()
        btns = [
            [TButton.inline("💸 Nạp 10,000đ", "p_10000"), TButton.inline("💸 Nạp 20,000đ", "p_20000")],
            [TButton.inline("💸 Nạp 30,000đ", "p_30000"), TButton.inline("💸 Nạp 50,000đ", "p_50000")],
            [TButton.inline("💸 Nạp 100,000đ", "p_100000"), TButton.inline("💸 Nạp 200,000đ", "p_200000")],
            [TButton.inline("🔙 QUAY LẠI TRANG CHỦ", b"back")]
        ]
        await e.edit("🏦 **VUI LÒNG CHỌN MỨC TIỀN MUỐN NẠP:** ", buttons=btns)

    elif data.startswith("p_"):
        await e.answer()
        amt = data.split("_")[1]
        qr = f"https://img.vietqr.io/image/MSB-{STK_MSB}-compact2.png?amount={amt}&addInfo=NAP%20{uid}"
        txt = (f"📥 **HƯỚNG DẪN NẠP TIỀN:**\n\n"
               f"🏦 Ngân hàng: **MSB**\n"
               f"💳 Số tài khoản: `{STK_MSB}`\n"
               f"💰 Số tiền: **{int(amt):,}đ**\n"
               f"📝 Nội dung chuyển khoản (BẮT BUỘC): `NAP {uid}`\n\n"
               f"*(Vui lòng bấm nút mở mã QR bên dưới hoặc chuyển khoản đúng nội dung để được cộng tiền tự động 24/7)*")
        await e.edit(txt, buttons=[[TButton.url("🖼 BẤM VÀO ĐÂY ĐỂ MỞ MÃ QR", qr)], [TButton.inline("🔙 QUAY LẠI", b"dep_menu")]])

# Hàm phụ trợ xử lý mua code dùng chung cho buy_ và buycustom_
async def process_purchase(e, uid, cid, qty, conv=None):
    try:
        cat_res = await asyncio.to_thread(lambda: supabase.table("categories").select("*").eq("id", cid).execute())
        if not getattr(cat_res, 'data', None):
            msg = "❌ Lỗi: Không tìm thấy game này!"
            if conv: await conv.send_message(msg, buttons=[[TButton.inline("🔙 LÀM LẠI", b"list_categories")]])
            else: await e.edit(msg, buttons=[[TButton.inline("🔙 LÀM LẠI", b"list_categories")]])
            return
            
        cat = cat_res.data[0]
        user = await db_get_user(uid)
        cost = cat['price'] * qty
        
        if user['balance'] < cost: 
            msg = "❌ Rất tiếc, số dư của bạn không đủ để thanh toán. Vui lòng nạp thêm tiền!"
            if conv: await conv.send_message(msg, buttons=[[TButton.inline("🔙", b"list_categories")]])
            else: await bot.send_message(uid, msg)
            return
        
        stock_res = await asyncio.to_thread(lambda: supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute())
        stock_data = getattr(stock_res, 'data', [])
        
        if len(stock_data) < qty: 
            msg = f"❌ Rất tiếc, trong kho chỉ còn {len(stock_data)} code, không đủ số lượng bạn cần!"
            if conv: await conv.send_message(msg, buttons=[[TButton.inline("🔙", b"list_categories")]])
            else: await bot.send_message(uid, msg)
            return
        
        # Trừ tiền 
        await asyncio.to_thread(lambda: supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute())

        # Gom code và gửi
        res_text = f"✅ **MUA THÀNH CÔNG {qty} CODE {cat['name']}!**\n\n"
        codes_str_db = ""
        for c in stock_data:
            await asyncio.to_thread(lambda: supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute())
            res_text += f"`{c['code']}`\n"
            codes_str_db += f"{c['code']} | "
            
        # Lưu lịch sử KÈM CODE & Gửi thông báo Kênh
        await db_add_history(uid, "Mua Code", cat['name'], qty, cost, codes_str_db.strip(" | "))
        await send_channel_notify(
            f"🛒 **GIAO DỊCH MUA CODE THÀNH CÔNG**\n"
            f"👤 Người mua: `{uid}`\n"
            f"🎮 Game: **{cat['name']}**\n"
            f"📦 Số lượng: **{qty} code**\n"
            f"💰 Tổng bill: **-{cost:,}đ**\n"
            f"✅ *(Hệ thống chỉ báo số lượng, không hiển thị code)*"
        )
            
        if conv: 
            await conv.send_message(res_text, buttons=[[TButton.inline("🔙 QUAY LẠI TRANG CHỦ", b"back")]])
        else:
            await e.edit(res_text, buttons=[[TButton.inline("🔙 QUAY LẠI TRANG CHỦ", b"back")]])
            
    except Exception as ex:
        logging.error(f"Lỗi xử lý thanh toán mua code: {ex}")
        if conv: await conv.send_message("❌ Lỗi hệ thống khi thanh toán.")

# ==================== LOGIC THÊM CLONE (ĐÃ FIX ĐỒNG BỘ) ====================
@bot.on(events.CallbackQuery(data=b"add_clone"))
async def add_clone_process(e):
    await e.answer()
    uid = e.sender_id
    if uid != ADMIN_ID: 
        return
        
    async with bot.conversation(uid) as conv:
        try:
            await conv.send_message("📞 Vui lòng nhập Số điện thoại (+84...):")
            phone = (await conv.get_response()).text.strip()
            
            # ĐÃ FIX: Thêm loop=loop vào khai báo TelegramClient
            client = TelegramClient(StringSession(), API_ID, API_HASH, loop=loop)
            await client.connect()
            await client.send_code_request(phone)
            
            await conv.send_message("📩 Telegram đã gửi mã OTP. Vui lòng nhập OTP vào đây:")
            otp = (await conv.get_response()).text.strip()
            
            try:
                await client.sign_in(phone, otp)
            except SessionPasswordNeededError:
                await conv.send_message("🔐 Tài khoản có cài Mật khẩu cấp 2 (2FA). Vui lòng nhập Mật khẩu 2FA:")
                password = (await conv.get_response()).text.strip()
                await client.sign_in(password=password)
                
            ss = client.session.save()
            await asyncio.to_thread(lambda: supabase.table("my_clones").insert({"phone": phone, "session": ss, "status": "active"}).execute())
            await conv.send_message("✅ Quá trình thêm Clone hoàn tất và thành công!", buttons=[[TButton.inline("🔙 QUẢN LÝ CLONE", b"admin_clones")]])
            
            # Khởi động Clone ngay lập tức
            asyncio.create_task(worker_grab_loop(client, phone))
            
        except Exception as ex:
            logging.error(f"Lỗi thêm clone: {ex}")
            await conv.send_message("❌ Có lỗi xảy ra trong quá trình đăng nhập (Sai sdt, sai OTP, hoặc Timeout).", buttons=[[TButton.inline("🔙", b"admin_clones")]])

# ==================== WEBHOOK & KEEP-ALIVE (TREO 24/7) ====================
app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return "Bot is running 24/7! Connection OK.", 200

@app.route('/sepay-webhook', methods=['POST'])
def webhook():
    try:
        d = request.json
        m = re.search(r'(\d{8,12})', d.get("content", "").upper())
        if m:
            uid = int(m.group(1))
            amt = int(d.get("transferAmount", 0))
            
            # === PHẦN BỊ THIẾU Ở CODE CỦA BẠN ĐÃ ĐƯỢC THÊM LẠI ĐẦY ĐỦ ===
            user = sync_db_get_user(uid)
            new_balance = user['balance'] + amt
            sync_db_add_history(uid, "Nạp tiền", "Bank", 1, amt)
            supabase.table("users").update({"balance": new_balance}).eq("user_id", uid).execute()
            sync_send_channel_notify(f"💰 **NẠP TIỀN TỰ ĐỘNG**\n👤 User: `{uid}`\n💵 Số tiền: **+{amt:,}đ**\n✅ Trạng thái: Thành công")
            try:
                asyncio.run_coroutine_threadsafe(bot.send_message(uid, f"✅ **NẠP TIỀN THÀNH CÔNG!**\nBạn vừa được cộng **{amt:,}đ** vào tài khoản."), loop)
            except Exception as e:
                logging.error(f"Lỗi gửi tin nhắn nạp tiền cho user: {e}")
            return jsonify({"status": "success"}), 200
        return jsonify({"status": "ignored"}), 200
    except Exception as e:
        logging.error(f"Lỗi webhook: {e}")
        return jsonify({"status": "error"}), 500

def run_web():
    app.run(host="0.0.0.0", port=10000)

Thread(target=run_web).start()

def keep_alive():
    while True:
        try:
            urllib.request.urlopen("http://127.0.0.1:10000/", timeout=10)
        except Exception as e:
            logging.warning(f"Lỗi ping keep_alive: {e}")
        time.sleep(120) 

Thread(target=keep_alive).start()

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    print("--- BOT IS STARTED AND ONLINE ---")
    
    # Kích hoạt background task tự động dọn rác DB
    asyncio.create_task(auto_clean_history())
    
    try:
        # FIX TẠI ĐÂY: Thêm .range(0, 1000) để bot load đủ 191 clone khi bật lên
        clones_res = await asyncio.to_thread(lambda: supabase.table("my_clones").select("*").eq("status", "active").range(0, 1000).execute())
        clones = clones_res.data if getattr(clones_res, 'data', None) else []
        if clones:
            print(f"--- ĐÃ TÌM THẤY {len(clones)} CLONE TRONG DB. BẮT ĐẦU KÍCH HOẠT ---")
            for c in clones:
                try:
                    cl = TelegramClient(StringSession(c['session']), API_ID, API_HASH, loop=loop)
                    asyncio.create_task(worker_grab_loop(cl, c['phone']))
                except Exception as clone_err: 
                    logging.error(f"Lỗi khởi động clone {c['phone']}: {clone_err}")
        else:
            print("--- KHÔNG CÓ CLONE NÀO ĐỂ CHẠY HOẶC BỊ CHẶN BỞI RLS ---")
    except Exception as db_err:
        logging.error(f"Lỗi tải danh sách clone từ DB: {db_err}")
        
    await bot.run_until_disconnected()
    

if __name__ == '__main__':
    loop.run_until_complete(main())
if __name__ == "__main__":
    keep_alive()  # Khởi tạo server giữ bot luôn thức
    print("Bot đang chạy...")
    client.run_until_disconnected() # Hoặc lệnh chạy bot của bạn
