#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import base64
import time
import asyncio
import aiohttp
import random
import warnings
import re
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import wraps
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)

warnings.filterwarnings('ignore')

# ================================================================
# CONFIGURATIONS & FILE PATHS
# ================================================================
# Render Environment Variable:
#   BOT_TOKEN = your NEW BotFather token
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [7212602902,6034021445,6160213563]

ACCOUNTS_FILE = "accounts.json"

MARKO_VERSION = "3.0.0-PHOENIX"
MARKO_SIGNATURE = "PH03N1X_C0R3"
MARKO_DEVICE_PREFIX = "PHOENIX-DEVICE-"
DEVELOPER = "MARKO"

API_KEY = 'AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ'
CF_BASE = 'https://europe-west1-cpm-2-7cea1.cloudfunctions.net'
KEY_ADD = '12345678'
IV_ADD = '01234567'
VERSION = '1.3.2.3'
CLIENT_HASH = 'F05A72840B40DC4FAADF539C5E38062527AE6422'
OG_BASE = 'https://cpm-2.ogames.kz/api'
OG_KEY = '320b93f3e7f4410aa52ce24da363ad04'
BUNDLE_ID = 'com.olzhas.carparking.multyplayer2'
USER_AGENT = 'UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)'
FB_LOGIN = f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}'

ITEMS_PER_PAGE = 10
MAX_ACCOUNTS = 50

WAITING_FARM_CREDS, WAITING_ADD_ACCOUNTS, WAITING_DELETE_ACCOUNTS = range(3)

# ================================================================
# RENDER HEALTH SERVER
# ================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 Health server listening on port {port}")
    server.serve_forever()

# ================================================================
# ADMIN SECURITY FILTER DECORATOR
# ================================================================
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer()
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ================================================================
# PERSISTENCE STORAGE HELPERS
# ================================================================
def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_accounts(data):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

ACCOUNTS_DB = load_accounts()

def get_user_accounts(user_id):
    uid_str = str(user_id)
    if uid_str not in ACCOUNTS_DB:
        ACCOUNTS_DB[uid_str] = []
        save_accounts(ACCOUNTS_DB)
    return ACCOUNTS_DB[uid_str]

# ================================================================
# CRYPTO ENGINE
# ================================================================
class PhoenixCrypto:
    def __init__(self, uid):
        self.uid = uid
        self.phoenix_key = (uid[:8] + KEY_ADD).encode()[:16]
        self.phoenix_iv = (uid[:8] + IV_ADD).encode()[:16]

    def phoenix_encrypt(self, plaintext):
        cipher = AES.new(self.phoenix_key, AES.MODE_CBC, self.phoenix_iv)
        encrypted = cipher.encrypt(pad(plaintext.encode(), 16))
        return base64.b64encode(encrypted).decode()

    def phoenix_decrypt(self, ciphertext):
        if not ciphertext:
            return None
        try:
            cipher = AES.new(self.phoenix_key, AES.MODE_CBC, self.phoenix_iv)
            decrypted = cipher.decrypt(base64.b64decode(ciphertext))
            return unpad(decrypted, 16).decode()
        except Exception:
            return None

    def phoenix_extract_value(self, data):
        if isinstance(data, (int, float)):
            return int(data)
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                return self.phoenix_extract_value(parsed)
            except Exception:
                pass
            if data.isdigit():
                return int(data)
            numbers = re.findall(r'\d+', data)
            if numbers:
                return int(numbers[0])
        if isinstance(data, list):
            for item in data:
                val = self.phoenix_extract_value(item)
                if val is not None:
                    return val
        if isinstance(data, dict):
            for key in ['coins', 'value', 'coin', 'amount', 'points', 'data']:
                if key in data:
                    val = self.phoenix_extract_value(data[key])
                    if val is not None:
                        return val
        return None

# ================================================================
# FARMING API ENGINE
# ================================================================
def phoenix_gen_device():
    return MARKO_DEVICE_PREFIX + ''.join(random.choice('0123456789abcdef') for _ in range(28))

def phoenix_headers(token):
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=utf-8",
        "X-Unity-Version": "2022.3.62f2",
        "Authorization": f"Bearer {token}",
        "X-Client-Hash": CLIENT_HASH,
        "X-Phoenix-Signature": MARKO_SIGNATURE,
        "X-Phoenix-Version": MARKO_VERSION,
        "X-Phoenix-Developer": DEVELOPER,
    }

def phoenix_ogames_headers(token, uid, device_id=None):
    return {
        "X-Firebase-Token": token,
        "X-Client-Platform": "ANDROID",
        "X-Client-Version": VERSION,
        "X-Client-DeviceId": device_id or phoenix_gen_device(),
        "X-Api-Key": OG_KEY,
        "X-Client-Env": "prod",
        "X-Bundle-Id": BUNDLE_ID,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Client-Hash": CLIENT_HASH,
        "X-Phoenix-Tag": MARKO_SIGNATURE,
        "X-Phoenix-Developer": DEVELOPER,
    }

async def phoenix_cf_request(fn, payload, token, session, timeout=30):
    url = f"{CF_BASE}/{fn}"
    body = json.dumps({"data": payload})
    hdrs = phoenix_headers(token)
    for attempt in range(3):
        try:
            async with session.post(
                url,
                headers=hdrs,
                data=body,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                if response.status in (429, 500, 502, 503):
                    await asyncio.sleep(1 + attempt * 2)
                    continue
                if response.status == 404:
                    return None
                text = await response.text()
                try:
                    parsed = json.loads(text)
                    return parsed.get("result")
                except json.JSONDecodeError:
                    if attempt < 2:
                        await asyncio.sleep(1 + attempt * 2)
                        continue
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt < 2:
                await asyncio.sleep(1 + attempt * 2)
                continue
            return None
    return None

async def phoenix_start_session(token, uid, session):
    device_id = phoenix_gen_device()
    oh = phoenix_ogames_headers(token, uid, device_id)
    try:
        await session.get(
            f"{OG_BASE}/check-service/v1/hash/check",
            headers=oh,
            timeout=aiohttp.ClientTimeout(total=15)
        )
        await session.post(
            f"{OG_BASE}/check-service/v1/session/start",
            headers=oh,
            json={},
            timeout=aiohttp.ClientTimeout(total=15)
        )
    except Exception:
        pass

    response = await phoenix_cf_request("MasterMainStartup23_1", "0", token, session)
    if response is None:
        response = await phoenix_cf_request("MasterMainStartup22_1", "0", token, session)
    return response

async def phoenix_login(email, password, session):
    try:
        async with session.post(
            FB_LOGIN,
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            data = await response.json()
            if "idToken" in data:
                return {
                    "token": data["idToken"],
                    "uid": data["localId"],
                    "email": data.get("email", email)
                }
            return None
    except Exception:
        return None

async def phoenix_get_coins(session, token, uid):
    headers = phoenix_headers(token)
    payload = {"data": None}
    url = f"{CF_BASE}/GetCoins23_1"
    try:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                if (
                    "result" in result
                    and isinstance(result["result"], dict)
                    and "data" in result["result"]
                ):
                    crypto = PhoenixCrypto(uid)
                    decrypted_str = crypto.phoenix_decrypt(result["result"]["data"])
                    return crypto.phoenix_extract_value(decrypted_str) or 0
    except Exception:
        pass
    return 0

async def phoenix_farm_engine(token, uid, session, progress_callback=None):
    crypto = PhoenixCrypto(uid)
    all_combos = [
        (a, b, c)
        for a in range(10)
        for b in range(1, 7)
        for c in range(10)
    ]
    all_combos_v2 = [
        (car, place, gear)
        for car in range(6)
        for place in range(1, 4)
        for gear in range(2)
    ]

    total_coins = 0
    successful_ops = 0
    total_ops = 0

    async def phoenix_execute_drag(sequence, sess):
        a, b, c = sequence
        payload = f"{a},{b},{c}"
        encrypted = crypto.phoenix_encrypt(payload)
        url = f"{CF_BASE}/SetDragRacing23_1"
        headers = phoenix_headers(token)
        body = json.dumps({"data": encrypted})
        try:
            async with sess.post(
                url,
                headers=headers,
                data=body,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    if (
                        "result" in result
                        and isinstance(result["result"], dict)
                        and "data" in result["result"]
                    ):
                        decrypted = crypto.phoenix_decrypt(result["result"]["data"])
                        coins = crypto.phoenix_extract_value(decrypted)
                        if coins is not None:
                            return coins
        except Exception:
            pass
        return 0

    async def phoenix_execute_combo(combo, sess):
        car, place, gear = combo
        payload = f"{car},{place},{gear}"
        encrypted = crypto.phoenix_encrypt(payload)
        response = await phoenix_cf_request(
            "SetDragRacing22_1",
            encrypted,
            token,
            sess
        )
        coins = 0
        if response is not None:
            arr = []
            if isinstance(response, str):
                try:
                    parsed = json.loads(response)
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        arr = parsed
                except Exception:
                    pass
            elif isinstance(response, list) and len(response) >= 2:
                arr = response
            if len(arr) >= 2:
                decrypted = (
                    crypto.phoenix_decrypt(arr[1])
                    if isinstance(arr[1], str)
                    else None
                )
                if decrypted:
                    try:
                        coins = int(decrypted)
                    except Exception:
                        pass
        return coins

        batch_size = 100
    for i in range(0, len(all_combos), batch_size):
        batch = all_combos[i:i + batch_size]
        results = await asyncio.gather(
            *[phoenix_execute_drag(seq, session) for seq in batch]
        )

        for coins in results:
            if coins > 0:
                total_coins += coins
                successful_ops += 1
            total_ops += 1

        if progress_callback and (
            i % 200 == 0 or i + batch_size >= len(all_combos)
        ):
            await progress_callback(
                f"⚡ **Phase 1/2: Drag Farming**\n"
                f"Progress: `{min(i + batch_size, len(all_combos))}/{len(all_combos)}`\n"
                f"Coins Harvested: `{total_coins:,}`"
            )
        await asyncio.sleep(0.2)


    completed_combos = set()
    for round_num in range(1, 6):
        pending = [
            combo
            for combo in all_combos_v2
            if combo not in completed_combos
        ]
        if not pending:
            break

        results = await asyncio.gather(
            *[phoenix_execute_combo(combo, session) for combo in pending]
        )

        for idx, coins in enumerate(results):
            if coins > 0:
                completed_combos.add(pending[idx])
                total_coins += coins
                successful_ops += 1
            total_ops += 1

        if progress_callback:
            await progress_callback(
                f"🏎 **Phase 2/2: Combo Farming**\n"
                f"Round: `{round_num}/5`\n"
                f"Coins Harvested: `{total_coins:,}`"
            )
        await asyncio.sleep(0.5)

    return successful_ops, total_ops, total_coins

# ================================================================
# TELEGRAM UI HELPERS
# ================================================================
def get_main_menu():
    return ReplyKeyboardMarkup(
        [["🚀 Start Farming", "📋 My Accounts"]],
        resize_keyboard=True
    )

def get_accounts_main_inline():
    keyboard = [
        [InlineKeyboardButton("👁 View All Accounts", callback_data="view_accounts")],
        [InlineKeyboardButton("✏️ Edit Accounts", callback_data="edit_accounts")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_edit_accounts_inline():
    keyboard = [
        [InlineKeyboardButton("➕ Add Accounts", callback_data="add_accounts")],
        [InlineKeyboardButton("🗑 Delete Accounts", callback_data="delete_accounts")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_acc_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_accounts_page(user_id, page=0):
    accounts = get_user_accounts(user_id)
    total_accs = len(accounts)
    total_pages = max(1, (total_accs + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    page = max(0, min(page, total_pages - 1))
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_accs = accounts[start_idx:end_idx]

    text = f"📋 **Saved Accounts** (`{total_accs}/{MAX_ACCOUNTS}`)\n"
    text += f"Page `{page + 1}/{total_pages}`\n\n"

    if not accounts:
        text += "_No accounts saved yet._"
    else:
        for idx, acc in enumerate(page_accs, start=start_idx + 1):
            text += f"`{idx}.` `{acc['email']}:{acc['password']}`\n"

    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton("◀️ Prev", callback_data=f"acc_page_{page - 1}")
        )

    nav_buttons.append(
        InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop")
    )

    if page < total_pages - 1:
        nav_buttons.append(
            InlineKeyboardButton("Next ▶️", callback_data=f"acc_page_{page + 1}")
        )

    keyboard = []
    if total_pages > 1 or total_accs > 0:
        keyboard.append(nav_buttons)
    keyboard.append(
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_acc_main")]
    )

    return text, InlineKeyboardMarkup(keyboard)

# ================================================================
# HANDLERS
# ================================================================
@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_user_accounts(user.id)
    await update.message.reply_text(
        "🤖 **welcome admin**\nSelect an option below:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

@admin_only
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "🚀 Start Farming":
        await update.message.reply_text(
            "🔑 **Start Farming**\n\n"
            "Please send your account details in format:\n"
            "`email:password`",
            parse_mode="Markdown"
        )
        return WAITING_FARM_CREDS

    elif text == "📋 My Accounts":
        await update.message.reply_text(
            "📋 **My Accounts Management**\n\nChoose an action below:",
            reply_markup=get_accounts_main_inline(),
            parse_mode="Markdown"
        )

    return ConversationHandler.END

@admin_only
async def process_farming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = update.message.text.strip()

    if ":" not in creds:
        await update.message.reply_text(
            "❌ Invalid format. Send credentials as `email:password`",
            parse_mode="Markdown"
        )
        return WAITING_FARM_CREDS

    email, password = creds.split(":", 1)
    status_msg = await update.message.reply_text(
        "🔑 Authenticating account...",
        parse_mode="Markdown"
    )

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False)
    ) as session:
        auth = await phoenix_login(email, password, session)
        if not auth:
            await status_msg.edit_text(
                "❌ **Authentication Failed!** Check credentials and try again."
            )
            return ConversationHandler.END

        token, uid = auth["token"], auth["uid"]
        await status_msg.edit_text("⚡ Starting Session...")

        initial_coins = await phoenix_get_coins(session, token, uid)
        await phoenix_start_session(token, uid, session)

        async def farm_progress(p_text):
            try:
                await status_msg.edit_text(
                    f"🚜 **Farming In Progress**\n"
                    f"Account: `{email}`\n\n{p_text}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        successful, total, coins = await phoenix_farm_engine(
            token,
            uid,
            session,
            progress_callback=farm_progress
        )

        final_coins = await phoenix_get_coins(
            session, token, uid
        ) or (initial_coins + coins)

        result_text = (
            "✅ **Farming Completed Successfully!**\n\n"
            f"• **Account**: `{email}`\n"
            f"• **Successful Operations**: `{successful:,}`\n"
            f"• **Initial Coins**: `{initial_coins:,}`\n"
            f"• **Harvested Coins**: `{coins:,}` 🪙\n"
            f"• **Final Coins**: `{final_coins:,}`"
        )
        await status_msg.edit_text(result_text, parse_mode="Markdown")

    return ConversationHandler.END

@admin_only
async def handle_inline_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    await query.answer()

    if data == "back_to_acc_main":
        await query.edit_message_text(
            "📋 **My Accounts Management**\n\nChoose an action below:",
            reply_markup=get_accounts_main_inline(),
            parse_mode="Markdown"
        )

    elif data == "view_accounts":
        msg_text, reply_markup = build_accounts_page(user_id, page=0)
        await query.edit_message_text(
            msg_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif data == "edit_accounts":
        await query.edit_message_text(
            "✏️ **Edit Accounts Menu**\n\n"
            "Choose whether to add or delete accounts:",
            reply_markup=get_edit_accounts_inline(),
            parse_mode="Markdown"
        )

    elif data.startswith("acc_page_"):
        page = int(data.split("_")[-1])
        msg_text, reply_markup = build_accounts_page(user_id, page=page)
        await query.edit_message_text(
            msg_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif data == "add_accounts":
        await query.message.reply_text(
            f"📥 **Add Accounts (Max {MAX_ACCOUNTS})**\n\n"
            "Send your accounts in `email:password` format (one per line):",
            parse_mode="Markdown"
        )
        return WAITING_ADD_ACCOUNTS

    elif data == "delete_accounts":
        await query.message.reply_text(
            "🗑 **Delete Accounts**\n\n"
            "Send the account(s) you want to remove in "
            "`email:password` or `email` format (one per line):",
            parse_mode="Markdown"
        )
        return WAITING_DELETE_ACCOUNTS

    elif data == "noop":
        pass

@admin_only
async def process_add_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split("\n")
    accounts = get_user_accounts(user_id)

    added = 0
    for line in lines:
        if ":" in line:
            email, password = line.strip().split(":", 1)
            email, password = email.strip(), password.strip()

            if not any(a["email"] == email for a in accounts):
                if len(accounts) < MAX_ACCOUNTS:
                    accounts.append({
                        "email": email,
                        "password": password
                    })
                    added += 1

    ACCOUNTS_DB[str(user_id)] = accounts
    save_accounts(ACCOUNTS_DB)

    await update.message.reply_text(
        f"✅ **Saved {added} account(s)!** "
        f"Total saved: `{len(accounts)}/{MAX_ACCOUNTS}`",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

@admin_only
async def process_delete_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lines = update.message.text.strip().split("\n")
    accounts = get_user_accounts(user_id)

    targets_to_remove = set()
    for line in lines:
        line_clean = line.strip()
        if ":" in line_clean:
            email, password = line_clean.split(":", 1)
            targets_to_remove.add(email.strip())
        elif line_clean:
            targets_to_remove.add(line_clean)

    initial_count = len(accounts)
    updated_accounts = [
        acc for acc in accounts
        if acc["email"] not in targets_to_remove
    ]
    deleted_count = initial_count - len(updated_accounts)

    ACCOUNTS_DB[str(user_id)] = updated_accounts
    save_accounts(ACCOUNTS_DB)

    await update.message.reply_text(
        f"🗑 **Deleted {deleted_count} account(s)!** "
        f"Total remaining: `{len(updated_accounts)}/{MAX_ACCOUNTS}`",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

@admin_only
async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Operation canceled.",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END

# ================================================================
# MAIN BOT RUNNER
# ================================================================
def main():
    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex("^🚀 Start Farming$"),
                handle_menu
            ),
            CallbackQueryHandler(
                handle_inline_buttons,
                pattern="^(add_accounts|delete_accounts)$"
            ),
        ],
        states={
            WAITING_FARM_CREDS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_farming
                )
            ],
            WAITING_ADD_ACCOUNTS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_add_accounts
                )
            ],
            WAITING_DELETE_ACCOUNTS: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_delete_accounts
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_handler),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                handle_menu
            )
        ]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_inline_buttons))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_menu
        )
    )

    print("🤖 Personal Farming Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
