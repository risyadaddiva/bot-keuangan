import os
import logging
import json
import sys
from datetime import datetime
from threading import Thread

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from flask import Flask

# ============================================
# KONFIGURASI
# ============================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = "Catatan Keuangan"
WORKSHEET_NAME = "Transaksi"
PORT = int(os.environ.get("PORT", 10000))

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States
NOMINAL, KETERANGAN, KATEGORI = range(3)
temp_data = {}

# ============================================
# FLASK KEEP-ALIVE SERVER
# ============================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Keuangan Aktif!"

@app.route('/health')
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

def run_flask():
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

# ============================================
# GOOGLE SHEETS SETUP (KHUSUS UNTUK RENDER)
# ============================================
def get_credentials():
    """Get credentials dari Render Secret File"""
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Prioritas 1: Render Secret File
    secret_paths = [
        '/etc/secrets/google_credentials',  # Secret File di Render
        '/etc/secrets/service_account',
        '/etc/secrets/service_account.json',
    ]
    
    for path in secret_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    creds_info = json.load(f)
                
                # Validasi
                if 'private_key' not in creds_info:
                    logger.error(f"Missing private_key in {path}")
                    continue
                
                private_key = creds_info['private_key']
                
                # Cek panjang private key
                key_len = len(private_key)
                logger.info(f"Private key length: {key_len}")
                
                if key_len < 1000:
                    logger.error(f"Private key too short: {key_len} chars")
                    continue
                
                # Fix newlines jika perlu
                if '\\n' in private_key:
                    private_key = private_key.replace('\\n', '\n')
                    creds_info['private_key'] = private_key
                    logger.info("Fixed escaped newlines in private key")
                
                credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
                logger.info(f"✅ Credentials loaded from {path}")
                logger.info(f"   Service Account: {creds_info.get('client_email')}")
                return credentials
                
            except Exception as e:
                logger.error(f"❌ Failed to load from {path}: {e}")
                continue
    
    # Fallback: Environment variable (tidak direkomendasikan untuk production)
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        try:
            creds_info = json.loads(creds_json)
            credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
            logger.info("✅ Credentials loaded from environment variable")
            return credentials
        except Exception as e:
            logger.error(f"❌ Failed to load from env: {e}")
    
    raise ValueError("No valid credentials found in Secret Files or Environment!")

def setup_google_sheets():
    """Connect to Google Sheets"""
    try:
        credentials = get_credentials()
        client = gspread.authorize(credentials)
        
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            logger.info(f"✅ Connected to: {spreadsheet.title}")
            return spreadsheet
        except gspread.SpreadsheetNotFound:
            logger.error(f"❌ Spreadsheet '{SPREADSHEET_NAME}' not found!")
            raise
            
    except Exception as e:
        logger.error(f"❌ Google Sheets error: {e}")
        raise

def get_or_create_worksheet(spreadsheet, worksheet_name=WORKSHEET_NAME):
    """Get or create worksheet"""
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        logger.info(f"✅ Worksheet: {worksheet_name}")
    except gspread.WorksheetNotFound:
        logger.info(f"📝 Creating: {worksheet_name}")
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=5)
        
        headers = ["Tanggal", "Tipe", "Nominal", "Kategori", "Keterangan"]
        worksheet.append_row(headers)
        
        try:
            worksheet.format('A1:E1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
            })
        except:
            pass
    
    return worksheet

# ============================================
# BOT HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Lapor", callback_data='lapor')],
        [InlineKeyboardButton("📊 Cek", callback_data='cek')]
    ]
    await update.message.reply_text(
        "💰 *Bot Keuangan*\n\nPilih menu:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'lapor':
        keyboard = [
            [InlineKeyboardButton("💰 Pemasukan", callback_data='tipe_pemasukan')],
            [InlineKeyboardButton("💸 Pengeluaran", callback_data='tipe_pengeluaran')]
        ]
        await query.edit_message_text("Pilih:", reply_markup=InlineKeyboardMarkup(keyboard))
        return NOMINAL
    
    elif query.data == 'cek':
        try:
            spreadsheet = setup_google_sheets()
            url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit"
            await query.edit_message_text(
                f"📊 [Buka Spreadsheet]({url})",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data='back')]])
            )
        except Exception as e:
            error_str = str(e)
            if "invalid_grant" in error_str:
                error_msg = "❌ Credentials tidak valid. Silakan perbarui di Render Secrets."
            else:
                error_msg = f"❌ Error: {error_str[:100]}"
            
            await query.edit_message_text(
                error_msg,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data='back')]])
            )
        return ConversationHandler.END

async def tipe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tipe = query.data.replace('tipe_', '')
    temp_data[user_id] = {'tipe': tipe}
    emoji = "💰" if tipe == 'pemasukan' else "💸"
    await query.edit_message_text(f"{emoji} *{tipe.upper()}*\n\nNominal:", parse_mode='Markdown')
    return NOMINAL

async def get_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().replace('.', '').replace(',', '').replace(' ', '').replace('Rp', '')
    
    try:
        nominal = int(text)
        if nominal <= 0:
            raise ValueError()
        temp_data[user_id]['nominal'] = nominal
        await update.message.reply_text("✅ Kirim keterangan:")
        return KETERANGAN
    except:
        await update.message.reply_text("❌ Angka tidak valid. Coba lagi:")
        return NOMINAL

async def get_keterangan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keterangan = update.message.text.strip()
    
    if len(keterangan) < 2:
        await update.message.reply_text("❌ Terlalu pendek:")
        return KETERANGAN
    
    temp_data[user_id]['keterangan'] = keterangan
    
    if temp_data[user_id]['tipe'] == 'pemasukan':
        return await save_transaction(update, context, user_id, "Pemasukan")
    
    keyboard = [
        [InlineKeyboardButton("🍽 Makan", callback_data='cat_Makan')],
        [InlineKeyboardButton("🚬 Rokok", callback_data='cat_Rokok')],
        [InlineKeyboardButton("⛽ Bensin", callback_data='cat_Bensin')],
        [InlineKeyboardButton("☕ Nongkrong", callback_data='cat_Nongkrong')],
        [InlineKeyboardButton("📦 Lain-lain", callback_data='cat_Lain-lain')]
    ]
    await update.message.reply_text("Kategori:", reply_markup=InlineKeyboardMarkup(keyboard))
    return KATEGORI

async def get_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    kategori = query.data.replace('cat_', '')
    return await save_transaction(update, context, user_id, kategori, query.edit_message_text)

async def save_transaction(update, context, user_id, kategori, edit_msg=None):
    data = temp_data[user_id]
    
    try:
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet)
        
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data['tipe'].capitalize(),
            data['nominal'],
            kategori,
            data['keterangan']
        ]
        
        worksheet.append_row(row)
        logger.info(f"✅ Saved: {row}")
        
        icon = "💰" if data['tipe'] == 'pemasukan' else "💸"
        nominal_fmt = f"Rp {data['nominal']:,}".replace(',', '.')
        msg = f"✅ *Tersimpan!*\n\n{icon} {data['tipe'].capitalize()}\n💵 {nominal_fmt}\n📁 {kategori}\n📝 {data['keterangan']}"
        
    except Exception as e:
        logger.error(f"❌ Save error: {e}")
        error_str = str(e)
        if "invalid_grant" in error_str:
            msg = "❌ *Gagal!*\n\nCredentials Google tidak valid. Hubungi admin untuk perbarui."
        else:
            msg = f"❌ *Gagal!*\n\n{error_str[:100]}"
    
    if user_id in temp_data:
        del temp_data[user_id]
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Lagi", callback_data='lapor'),
         InlineKeyboardButton("🔙 Menu", callback_data='back')]
    ])
    
    if edit_msg:
        await edit_msg(msg, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=keyboard)
    
    return ConversationHandler.END

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    keyboard = [[InlineKeyboardButton("📝 Lapor", callback_data='lapor')], 
                [InlineKeyboardButton("📊 Cek", callback_data='cek')]]
    await query.edit_message_text("💰 *Bot Keuangan*\n\nPilih menu:", parse_mode='Markdown', 
                                  reply_markup=InlineKeyboardMarkup(keyboard))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    await update.message.reply_text("❌ Dibatalkan.", 
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data='back')]]))
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("⚠️ Error. Ketik /start untuk ulang.")

# ============================================
# MAIN
# ============================================
def main():
    logger.info("=" * 60)
    logger.info("🚀 BOT KEUANGAN STARTING")
    logger.info("=" * 60)
    
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN not set!")
        return
    
    # Test Google Sheets
    try:
        logger.info("🔍 Testing Google Sheets...")
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet)
        logger.info(f"✅ Google Sheets OK: {spreadsheet.title}")
    except Exception as e:
        logger.error(f"❌ Google Sheets Error: {e}")
        # Tetap lanjutkan agar bot bisa jalan
    
    # Start Flask
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"✅ Flask started on port {PORT}")
    
    # Setup bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^lapor$')],
        states={
            NOMINAL: [CallbackQueryHandler(tipe_handler, pattern='^tipe_'),
                     MessageHandler(filters.TEXT & ~filters.COMMAND, get_nominal)],
            KETERANGAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_keterangan)],
            KATEGORI: [CallbackQueryHandler(get_kategori, pattern='^cat_')]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back$'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^cek$'))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot running!")
    logger.info("=" * 60)
    
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
