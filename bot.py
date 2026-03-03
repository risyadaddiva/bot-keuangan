import os
import logging
import json
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

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

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
# GOOGLE SHEETS SETUP
# ============================================
def load_credentials_from_file():
    """Load credentials dari file (termasuk Render Secret Files)"""
    file_paths = [
        '/etc/secrets/service_account',  # Render Secret File (prioritas)
        '/etc/secrets/service_account.json',
        'service_account.json',  # Local development
        os.path.expanduser('~/service_account.json')
    ]
    
    for path in file_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    creds_info = json.load(f)
                logger.info(f"✅ Credentials loaded from: {path}")
                return validate_credentials(creds_info)
            except Exception as e:
                logger.warning(f"⚠️ Failed to load from {path}: {e}")
                continue
    
    return None

def get_credentials():
    """Get credentials dengan multiple fallback"""
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Coba dari file dulu (lebih reliable)
    creds_info = load_credentials_from_file()
    
    # Fallback ke environment variable
    if not creds_info:
        creds_info = load_credentials_from_env()
    
    if not creds_info:
        raise ValueError(
            "No valid credentials found! "
            "Please set GOOGLE_CREDENTIALS env var or upload service_account.json file."
        )
    
    # Create credentials
    try:
        credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
        logger.info(f"✅ Credentials created for: {creds_info.get('client_email')}")
        return credentials
    except Exception as e:
        logger.error(f"❌ Failed to create credentials: {e}")
        raise

def setup_google_sheets():
    """Connect to Google Sheets"""
    try:
        credentials = get_credentials()
        client = gspread.authorize(credentials)
        
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            logger.info(f"✅ Connected to spreadsheet: {spreadsheet.title}")
            return spreadsheet
        except gspread.SpreadsheetNotFound:
            logger.error(f"❌ Spreadsheet '{SPREADSHEET_NAME}' not found!")
            logger.error("Make sure the spreadsheet exists and is shared with the service account")
            raise
            
    except Exception as e:
        logger.error(f"❌ Failed to setup Google Sheets: {e}")
        raise

def get_or_create_worksheet(spreadsheet, worksheet_name=WORKSHEET_NAME):
    """Get or create worksheet"""
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        logger.info(f"✅ Using worksheet: {worksheet_name}")
    except gspread.WorksheetNotFound:
        logger.info(f"📝 Creating new worksheet: {worksheet_name}")
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=5)
        
        # Add headers
        headers = ["Tanggal", "Tipe", "Nominal", "Kategori", "Keterangan"]
        worksheet.append_row(headers)
        
        # Format headers
        try:
            worksheet.format('A1:E1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9},
                'horizontalAlignment': 'CENTER'
            })
        except Exception as e:
            logger.warning(f"Could not format headers: {e}")
    
    return worksheet

# ============================================
# BOT HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    keyboard = [
        [InlineKeyboardButton("📝 Lapor Transaksi", callback_data='lapor')],
        [InlineKeyboardButton("📊 Cek Laporan", callback_data='cek')]
    ]
    
    await update.message.reply_text(
        "💰 *Bot Pencatatan Keuangan*\n\n"
        "Selamat datang! Bot ini mencatat pemasukan dan pengeluaran Anda.\n\n"
        "Pilih menu:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu buttons"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'lapor':
        keyboard = [
            [InlineKeyboardButton("💰 Pemasukan", callback_data='tipe_pemasukan')],
            [InlineKeyboardButton("💸 Pengeluaran", callback_data='tipe_pengeluaran')]
        ]
        await query.edit_message_text(
            "Pilih jenis transaksi:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return NOMINAL
    
    elif query.data == 'cek':
        try:
            spreadsheet = setup_google_sheets()
            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit"
            
            await query.edit_message_text(
                f"📊 *Laporan Keuangan*\n\n"
                f"📁 File: `{spreadsheet.title}`\n"
                f"📄 Sheet: `{WORKSHEET_NAME}`\n\n"
                f"[👉 Buka Spreadsheet]({sheet_url})",
                parse_mode='Markdown',
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Kembali", callback_data='back')
                ]])
            )
        except Exception as e:
            logger.error(f"Error in cek: {e}")
            await query.edit_message_text(
                f"❌ Error accessing spreadsheet\n\n"
                f"Pastikan spreadsheet sudah di-share ke service account.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Kembali", callback_data='back')
                ]])
            )
        return ConversationHandler.END

async def tipe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle income/expense selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    tipe = query.data.replace('tipe_', '')
    temp_data[user_id] = {'tipe': tipe}
    
    emoji = "💰" if tipe == 'pemasukan' else "💸"
    
    await query.edit_message_text(
        f"{emoji} *{tipe.upper()}*\n\n"
        f"Masukkan nominal (contoh: 50000):",
        parse_mode='Markdown'
    )
    return NOMINAL

async def get_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle nominal input"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Clean input
    clean = text.replace('.', '').replace(',', '').replace(' ', '').replace('Rp', '')
    
    try:
        nominal = int(clean)
        if nominal <= 0:
            raise ValueError("Nominal must be positive")
        if nominal > 999999999999:
            raise ValueError("Nominal too large")
            
        temp_data[user_id]['nominal'] = nominal
        
        await update.message.reply_text(
            "✅ Nominal tersimpan!\n\n"
            "Kirim keterangan transaksi:"
        )
        return KETERANGAN
        
    except ValueError as e:
        await update.message.reply_text(
            f"❌ *Error:* {str(e)}\n\n"
            f"Masukkan angka valid (contoh: 50000):",
            parse_mode='Markdown'
        )
        return NOMINAL

async def get_keterangan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle description input"""
    user_id = update.effective_user.id
    keterangan = update.message.text.strip()
    
    if len(keterangan) < 2:
        await update.message.reply_text("❌ Terlalu pendek (min 2 karakter). Coba lagi:")
        return KETERANGAN
    
    if len(keterangan) > 200:
        await update.message.reply_text("❌ Terlalu panjang (max 200 karakter). Coba lagi:")
        return KETERANGAN
    
    temp_data[user_id]['keterangan'] = keterangan
    tipe = temp_data[user_id]['tipe']
    
    # If income, save directly without category
    if tipe == 'pemasukan':
        return await save_transaction(update, context, user_id, "Pemasukan")
    
    # If expense, show category options
    keyboard = [
        [InlineKeyboardButton("🍽 Makan", callback_data='cat_Makan')],
        [InlineKeyboardButton("🚬 Rokok", callback_data='cat_Rokok')],
        [InlineKeyboardButton("⛽ Bensin", callback_data='cat_Bensin')],
        [InlineKeyboardButton("☕ Nongkrong", callback_data='cat_Nongkrong')],
        [InlineKeyboardButton("📦 Lain-lain", callback_data='cat_Lain-lain')]
    ]
    
    await update.message.reply_text(
        "Pilih kategori pengeluaran:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return KATEGORI

async def get_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    kategori = query.data.replace('cat_', '')
    
    return await save_transaction(
        update, context, user_id, kategori,
        edit_message=query.edit_message_text
    )

async def save_transaction(update, context, user_id, kategori, edit_message=None):
    """Save transaction to Google Sheets"""
    data = temp_data[user_id]
    
    try:
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)
        
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data['tipe'].capitalize(),
            data['nominal'],
            kategori,
            data['keterangan']
        ]
        
        worksheet.append_row(row)
        logger.info(f"✅ Saved transaction: {row}")
        
        # Format message
        icon = "💰" if data['tipe'] == 'pemasukan' else "💸"
        nominal_fmt = f"Rp {data['nominal']:,}".replace(',', '.')
        
        message = (
            f"✅ *Transaksi Tersimpan!*\n\n"
            f"{icon} *Tipe:* {data['tipe'].capitalize()}\n"
            f"💵 *Nominal:* {nominal_fmt}\n"
            f"📁 *Kategori:* {kategori}\n"
            f"📝 *Keterangan:* {data['keterangan']}\n"
            f"📅 *Waktu:* {datetime.now().strftime('%d-%m-%Y %H:%M')}"
        )
        
    except Exception as e:
        logger.error(f"❌ Error saving: {e}")
        message = f"❌ *Gagal menyimpan!*\n\nError: `{str(e)[:100]}`"
    
    # Cleanup
    if user_id in temp_data:
        del temp_data[user_id]
    
    # Navigation buttons
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Lapor Lagi", callback_data='lapor'),
            InlineKeyboardButton("🔙 Menu Utama", callback_data='back')
        ]
    ])
    
    # Send message
    if edit_message:
        await edit_message(message, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
    
    return ConversationHandler.END

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to main menu"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    
    keyboard = [
        [InlineKeyboardButton("📝 Lapor Transaksi", callback_data='lapor')],
        [InlineKeyboardButton("📊 Cek Laporan", callback_data='cek')]
    ]
    
    await query.edit_message_text(
        "💰 *Bot Pencatatan Keuangan*\n\nPilih menu:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel operation"""
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    
    await update.message.reply_text(
        "❌ Operasi dibatalkan.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Menu Utama", callback_data='back')
        ]])
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler"""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Terjadi kesalahan. Ketik /start untuk memulai ulang."
        )

# ============================================
# MAIN
# ============================================
def main():
    logger.info("=" * 60)
    logger.info("🚀 BOT KEUANGAN STARTING")
    logger.info(f"📁 Target: {SPREADSHEET_NAME}")
    logger.info("=" * 60)
    
    # Validate
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN not set!")
        return
    
    # Test Google Sheets connection
    try:
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)
        logger.info(f"✅ Google Sheets OK: {spreadsheet.title} > {worksheet.title}")
    except Exception as e:
        logger.error(f"❌ Google Sheets Error: {e}")
        return
    
    # Start Flask keep-alive server
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"✅ Flask server started on port {PORT}")
    
    # Setup bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^lapor$')],
        states={
            NOMINAL: [
                CallbackQueryHandler(tipe_handler, pattern='^tipe_'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_nominal)
            ],
            KETERANGAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_keterangan)
            ],
            KATEGORI: [
                CallbackQueryHandler(get_kategori, pattern='^cat_')
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back$'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^cek$'))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot is running!")
    logger.info("=" * 60)
    
    # Run bot
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
