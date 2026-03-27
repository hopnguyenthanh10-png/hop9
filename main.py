import asyncio
import re
import os
import random
import logging
import urllib.request
import time
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

async def db_set_setting(key, value):
    try:
        res = await asyncio.to_thread(lambda: supabase.table("settings").select("value").eq("key", key).execute())
        if not res.data:
            await asyncio.to_thread(lambda: supabase.table("settings").insert({"key": key, "value": str(value)}).execute())
        else:
            await asyncio.to_thread(lambda: supabase.table("settings").update({"value": str(value)}).eq("key", key).execute())
    except Exception as e:
        logging.error(f"Lỗi db_set_setting: {e}")

# ==================== LOGIC ĐẬP HỘP ĐA DANH MỤC ====================
async def worker_grab_loop(client, phone):
    try:
        if not client.is_connected(): 
            await client.connect()
            
        if not await client.is_user_authorized():
            logging.error(f"Clone {phone} đã chết session (bị đăng xuất).")
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
            if not ev.reply_markup: 
                return
            
            chat = await ev.get_chat()
            chat_username = getattr(chat, 'username', '')
            if not chat_username: 
                return

            try:
                cats_data = await asyncio.to_thread(lambda: supabase.table("categories").select("*").execute())
                if not cats_data.data: 
                    return
                
                matched_cat = next((c for c in cats_data.data if c.get('target_bot') and c['target_bot'].lower() == chat_username.lower()), None)
                
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
        [TButton.inline("🏦 NẠP TIỀN", b"dep_menu"), TButton.inline("🕒 LỊCH SỬ MUA", b"history")],
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

    # XỬ LÝ MENU ADMIN
    elif data == "admin_menu":
        await e.answer() 
        if uid != ADMIN_ID: 
            return
        btns = [
            [TButton.inline("📂 QUẢN LÝ DANH MỤC", b"admin_cats"), TButton.inline("📱 QUẢN LÝ CLONE", b"admin_clones")],
            [TButton.inline("⚙️ CÀI ĐẶT CHUNG", b"admin_settings"), TButton.inline("💰 CỘNG/TRỪ TIỀN", b"admin_money")],
            [TButton.inline("🔙 TRANG CHỦ", b"back")]
        ]
        await e.edit("👨‍💻 **BẢNG ĐIỀU KHIỂN ADMIN** ", buttons=btns)

    # XỬ LÝ QUẢN LÝ CLONE
    elif data == "admin_clones":
        await e.answer()
        if uid != ADMIN_ID: 
            return
        try:
            res = await asyncio.to_thread(lambda: supabase.table("my_clones").select("*").execute())
            btns = [[TButton.inline("➕ THÊM CLONE MỚI", b"add_clone")]]
            if res.data:
                for c in res.data:
                    btns.append([TButton.inline(f"🗑 Xóa {c['phone']}", f"del_clone_{c['id']}")])
            btns.append([TButton.inline("🔙 QUAY LẠI", b"admin_menu")])
            await e.edit(f"📱 **QUẢN LÝ CLONE ({len(res.data)} acc)** ", buttons=btns)
        except Exception as ex:
            logging.error(f"Lỗi admin_clones: {ex}")
            await e.edit("❌ Lỗi lấy dữ liệu clone.", buttons=[[TButton.inline("🔙", b"admin_menu")]])

    elif data.startswith("del_clone_"):
        try:
            cid = data.split("_")[2]
            await asyncio.to_thread(lambda: supabase.table("my_clones").delete().eq("id", cid).execute())
            await e.answer("✅ Đã xóa clone!", alert=True)
            
            # Reload lại trang
            res = await asyncio.to_thread(lambda: supabase.table("my_clones").select("*").execute())
            btns = [[TButton.inline("➕ THÊM CLONE MỚI", b"add_clone")]]
            if res.data:
                for c in res.data:
                    btns.append([TButton.inline(f"🗑 Xóa {c['phone']}", f"del_clone_{c['id']}")])
            btns.append([TButton.inline("🔙 QUAY LẠI", b"admin_menu")])
            await e.edit(f"📱 **QUẢN LÝ CLONE ({len(res.data)} acc)** ", buttons=btns)
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
                    # Bọc Try/Except khi đếm số lượng để không bị sập nếu bảng Code bị lỗi
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
                
                # Phải xóa codes thuộc về category này trước để tránh lỗi khóa ngoại (Foreign key)
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

    # XỬ LÝ LỊCH SỬ VÀ DANH MỤC BÁN HÀNG
    elif data == "history":
        await e.answer()
        await e.edit("🕒 Để xem lại lịch sử mua code, vui lòng vuốt lên và tìm các tin nhắn có chữ `MUA THÀNH CÔNG` do bot gửi nhé.", buttons=[[TButton.inline("🔙 QUAY LẠI", b"back")]])

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
            
            if not cat_res.data:
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

    # ---------------- BỔ SUNG ĐOẠN "MUA 1 CODE" BỊ MẤT ----------------
    elif data.startswith("buy_"):
        await e.answer()
        try:
            parts = data.split("_")
            cid = int(parts[1])
            qty = int(parts[2]) # Mặc định là 1 từ nút MUA 1 CODE
            
            cat_res = await asyncio.to_thread(lambda: supabase.table("categories").select("*").eq("id", cid).execute())
            if not cat_res.data:
                await e.edit("❌ Lỗi: Không tìm thấy game này!", buttons=[[TButton.inline("🔙 LÀM LẠI", b"list_categories")]])
                return
            cat = cat_res.data[0]
            
            user = await db_get_user(uid)
            cost = cat['price'] * qty
            
            if user['balance'] < cost: 
                await bot.send_message(uid, "❌ Rất tiếc, số dư của bạn không đủ để thanh toán. Vui lòng nạp thêm tiền!")
                return
            
            stock_res = await asyncio.to_thread(lambda: supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute())
            stock_data = stock_res.data
            
            if len(stock_data) < qty: 
                await bot.send_message(uid, "❌ Rất tiếc, trong kho không còn đủ code bạn cần!")
                return
            
            # Trừ tiền trước cho chắc ăn
            await asyncio.to_thread(lambda: supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute())
            
            # Nhả code
            res_text = f"✅ **MUA THÀNH CÔNG!**\n\n"
            for c in stock_data:
                await asyncio.to_thread(lambda: supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute())
                res_text += f"🎮 Game {cat['name']}: `{c['code']}`\n"
                
            await e.delete() # Xóa tin nhắn menu
            await bot.send_message(uid, res_text, buttons=[[TButton.inline("🔙 QUAY LẠI TRANG CHỦ", b"back")]])
        except Exception as ex:
            logging.error(f"Lỗi mua 1 code: {ex}")
            await bot.send_message(uid, "❌ Đã xảy ra lỗi hệ thống khi mua hàng!")

    # ---------------- FIX LỖI THỤT LỀ Ở MUA NHIỀU ----------------
    elif data.startswith("buycustom_"):
        await e.answer()
        try:
            cid = int(data.split("_")[1])
            cat_res = await asyncio.to_thread(lambda: supabase.table("categories").select("*").eq("id", cid).execute())
            
            if not cat_res.data:
                await e.edit("❌ Danh mục không tồn tại.", buttons=[[TButton.inline("🔙", b"list_categories")]])
                return
                
            cat = cat_res.data[0]
            await e.delete()
            
            async with bot.conversation(uid) as conv:
                await conv.send_message(f"🛒 Đang mua Game: **{cat['name']}**.\n👉 Vui lòng nhập số lượng bạn muốn mua (Chỉ ghi số, VD: 5):")
                try:
                    response_msg = await conv.get_response()
                    qty = int(response_msg.text.strip())
                    
                    if qty <= 0:
                        await conv.send_message("❌ Số lượng phải lớn hơn 0!", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"list_categories")]])
                        return

                    user = await db_get_user(uid)
                    cost = cat['price'] * qty
                    
                    if user['balance'] < cost: 
                        await conv.send_message(f"❌ Số dư không đủ! Bạn cần {cost:,}đ để mua {qty} code.", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"list_categories")]])
                        return
                    
                    stock_res = await asyncio.to_thread(lambda: supabase.table("codes").select("*").eq("category_id", cid).eq("status", "available").limit(qty).execute())
                    stock_data = stock_res.data
                    
                    if len(stock_data) < qty: 
                        await conv.send_message(f"❌ Trong kho chỉ còn {len(stock_data)} code, không đủ số lượng bạn yêu cầu!", buttons=[[TButton.inline("🔙 QUAY LẠI DANH MỤC", b"list_categories")]])
                        return
                    
                    # Trừ tiền
                    await asyncio.to_thread(lambda: supabase.table("users").update({"balance": user['balance'] - cost}).eq("user_id", uid).execute())
            
                    # Gom code và gửi
                    res_text = f"✅ **MUA THÀNH CÔNG {qty} CODE!**\n\n"
                    for c in stock_data:
                        await asyncio.to_thread(lambda: supabase.table("codes").update({"status": "sold"}).eq("id", c['id']).execute())
                        res_text += f"`{c['code']}`\n"
                        
                    await conv.send_message(res_text, buttons=[[TButton.inline("🔙 QUAY LẠI TRANG CHỦ", b"back")]])
                
                except ValueError:
                    await conv.send_message("❌ Lỗi: Vui lòng chỉ nhập số lượng là các chữ số!", buttons=[[TButton.inline("🔙 LÀM LẠI", b"list_categories")]])
                except Exception as ex:
                    logging.error(f"Lỗi timeout hoặc xử lý mua nhiều: {ex}")
                    await conv.send_message("❌ Quá thời gian chờ hoặc có lỗi xảy ra. Hãy thử lại!", buttons=[[TButton.inline("🔙 QUAY LẠI", b"list_categories")]])
        except Exception as outer_ex:
            logging.error(f"Lỗi khởi tạo buycustom: {outer_ex}")

    # XỬ LÝ NẠP TIỀN
    elif data == "dep_menu":
        await e.answer()
        btns = [
            [TButton.inline("💸 Nạp 10,000đ", "p_10000")],
            [TButton.inline("💸 Nạp 50,000đ", "p_50000")],
            [TButton.inline("💸 Nạp 100,000đ", "p_100000")],
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


# ==================== LOGIC THÊM CLONE ====================
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
            
            client = TelegramClient(StringSession(), API_ID, API_HASH)
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
            await asyncio.to_thread(lambda: supabase.table("my_clones").insert({"phone": phone, "session": ss}).execute())
            await conv.send_message("✅ Quá trình thêm Clone hoàn tất và thành công!")
            
            # Khởi động Clone ngay lập tức
            asyncio.create_task(worker_grab_loop(client, phone))
            
        except Exception as ex:
            logging.error(f"Lỗi thêm clone: {ex}")
            await conv.send_message("❌ Có lỗi xảy ra trong quá trình đăng nhập (Sai sdt, sai OTP, hoặc Timeout).")

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
            
            user = sync_db_get_user(uid)
            new_balance = user['balance'] + amt
            supabase.table("users").update({"balance": new_balance}).eq("user_id", uid).execute()
            
            asyncio.run_coroutine_threadsafe(bot.send_message(uid, f"✅ Hệ thống đã ghi nhận. Bạn vừa được nạp +{amt:,}đ vào tài khoản thành công!"), loop)
        return jsonify({"status": "ok", "message": "Webhook processed"}), 200
    except Exception as e:
        logging.error(f"Lỗi Webhook: {e}")
        return jsonify({"status": "error"}), 500

def keep_alive_ping():
    while True:
        try:
            # Gửi request để Render không ngủ, cho phép timeout nhỏ để không block thread
            urllib.request.urlopen("http://127.0.0.1:10000/", timeout=10)
        except Exception as e:
            logging.warning(f"Lỗi ping keep_alive: {e}")
        time.sleep(120) 

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    print("--- BOT IS STARTED AND ONLINE ---")
    
    try:
        clones_res = await asyncio.to_thread(lambda: supabase.table("my_clones").select("*").execute())
        clones = clones_res.data
        if clones:
            for c in clones:
                try:
                    cl = TelegramClient(StringSession(c['session']), API_ID, API_HASH)
                    asyncio.create_task(worker_grab_loop(cl, c['phone']))
                    print(f"Khởi động lại Clone: {c['phone']}")
                except Exception as clone_err: 
                    logging.error(f"Lỗi khởi động clone {c['phone']}: {clone_err}")
    except Exception as db_err:
        logging.error(f"Lỗi tải danh sách clone từ DB: {db_err}")
        
    await bot.run_until_disconnected()

if __name__ == '__main__':
    Thread(target=keep_alive_ping, daemon=True).start()
    Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    loop.run_until_complete(main())
