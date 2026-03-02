import os
import logging
import json
from datetime import datetime
from threading import Thread

import gspread
from google.oauth2.service_account import Credentials  # Gunakan google-auth, bukan oauth2client
from google.auth.transport.requests import Request
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
TELEGRAM_TOKEN = os.environ.get("8376770695:AAFqLbkaN-PfBjvGb0Y57QGYcdV1PrvRa8E")
SPREADSHEET_NAME = "catatan keuangan"  # Nama spreadsheet yang sudah ada
WORKSHEET_NAME = "transaksi"

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
# FLASK APP
# ============================================
app = Flask(__name__)

@app.route('/')
def home():
    return f"🤖 Bot Keuangan Aktif! | Spreadsheet: {SPREADSHEET_NAME}"

@app.route('/health')
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ============================================
# GOOGLE SHEETS SETUP (VERSI BARU)
# ============================================
def get_credentials():
    """Dapatkan credentials dari file atau environment variable"""
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    # Coba dari environment variable dulu
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if creds_json:
        try:
            creds_info = json.loads(creds_json)
            credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
            logger.info("✅ Credentials loaded from environment variable")
            return credentials
        except Exception as e:
            logger.error(f"❌ Error parsing GOOGLE_CREDENTIALS: {e}")
            raise
    
    # Fallback ke file
    try:
        credentials = Credentials.from_service_account_file(
            'credentials.json',
            scopes=scopes
        )
        logger.info("✅ Credentials loaded from credentials.json file")
        return credentials
    except FileNotFoundError:
        logger.error("❌ credentials.json not found and GOOGLE_CREDENTIALS not set")
        raise
    except Exception as e:
        logger.error(f"❌ Error loading credentials.json: {e}")
        raise

def setup_google_sheets():
    """Setup koneksi ke Google Sheets"""
    try:
        credentials = get_credentials()
        
        # Refresh token jika perlu
        if credentials.expired:
            credentials.refresh(Request())
        
        # Koneksi dengan gspread
        client = gspread.authorize(credentials)
        
        # Buka spreadsheet dengan nama
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            logger.info(f"✅ Spreadsheet opened: {spreadsheet.title} (ID: {spreadsheet.id})")
            return spreadsheet
        except gspread.SpreadsheetNotFound:
            logger.error(f"❌ Spreadsheet '{SPREADSHEET_NAME}' not found!")
            logger.error("Pastikan:")
            logger.error("1. Spreadsheet sudah dibuat dengan nama 'Catatan Keuangan'")
            logger.error("2. Service account sudah di-share ke spreadsheet dengan permission EDITOR")
            raise
        except Exception as e:
            logger.error(f"❌ Error opening spreadsheet: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"❌ Setup failed: {str(e)}")
        raise

def get_or_create_worksheet(spreadsheet, worksheet_name=WORKSHEET_NAME):
    """Ambil atau buat worksheet"""
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
        f"Data tersimpan di: `{SPREADSHEET_NAME}`\n\n"
        "Silakan pilih menu:",
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
                f"❌ Error: `{str(e)}`\n\n"
                "Pastikan spreadsheet sudah di-share ke service account.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Kembali", callback_data='back')
                ]])
            )
        return ConversationHandler.END

async def tipe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pemasukan/pengeluaran selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    tipe = query.data.replace('tipe_', '')
    temp_data[user_id] = {'tipe': tipe}
    
    emoji = "💰" if tipe == 'pemasukan' else "💸"
    
    await query.edit_message_text(
        f"{emoji} *{tipe.upper()}*\n\n"
        "Masukkan nominal (contoh: 50000):",
        parse_mode='Markdown'
    )
    return NOMINAL

async def get_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle nominal input"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Bersihkan format angka
    clean = text.replace('.', '').replace(',', '').replace(' ', '').replace('Rp', '')
    
    try:
        nominal = int(clean)
        if nominal <= 0:
            raise ValueError("Nominal harus positif")
        if nominal > 999999999999:
            raise ValueError("Nominal terlalu besar")
            
        temp_data[user_id]['nominal'] = nominal
        
        await update.message.reply_text(
            "✅ Nominal tersimpan!\n\nKirim keterangan:"
        )
        return KETERANGAN
        
    except ValueError as e:
        await update.message.reply_text(
            f"❌ *Error:* {str(e)}\n\nMasukkan angka valid (contoh: 50000):",
            parse_mode='Markdown'
        )
        return NOMINAL

async def get_keterangan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle keterangan input"""
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
    
    # Jika pemasukan, langsung simpan
    if tipe == 'pemasukan':
        return await save_transaction(update, context, user_id, "Pemasukan")
    
    # Jika pengeluaran, pilih kategori
    keyboard = [
        [InlineKeyboardButton("🍽 Makan", callback_data='cat_Makan')],
        [InlineKeyboardButton("🚬 Rokok", callback_data='cat_Rokok')],
        [InlineKeyboardButton("⛽ Bensin", callback_data='cat_Bensin')],
        [InlineKeyboardButton("☕ Nongkrong", callback_data='cat_Nongkrong')],
        [InlineKeyboardButton("📦 Lain-lain", callback_data='cat_Lain-lain')]
    ]
    
    await update.message.reply_text(
        "Pilih kategori:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return KATEGORI

async def get_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle kategori selection"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    kategori = query.data.replace('cat_', '')
    
    return await save_transaction(
        update, context, user_id, kategori,
        edit_message=query.edit_message_text
    )

async def save_transaction(update, context, user_id, kategori, edit_message=None):
    """Save to Google Sheets"""
    data = temp_data[user_id]
    
    try:
        # Simpan ke sheet
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
        logger.info(f"✅ Saved: {row}")
        
        # Format pesan
        icon = "💰" if data['tipe'] == 'pemasukan' else "💸"
        nominal_fmt = f"Rp {data['nominal']:,}".replace(',', '.')
        
        message = (
            f"✅ *Tersimpan!*\n\n"
            f"{icon} {data['tipe'].capitalize()}\n"
            f"💵 {nominal_fmt}\n"
            f"📁 {kategori}\n"
            f"📝 {data['keterangan']}\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        
    except Exception as e:
        logger.error(f"❌ Save error: {e}")
        message = f"❌ *Gagal menyimpan!*\n\nError: `{str(e)}`"
    
    # Cleanup
    if user_id in temp_data:
        del temp_data[user_id]
    
    # Tombol
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Lapor Lagi", callback_data='lapor'),
         InlineKeyboardButton("🔙 Menu", callback_data='back')]
    ])
    
    # Kirim
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
        "❌ Dibatalkan.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Menu", callback_data='back')
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
    
    # Validasi
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN tidak ditemukan!")
        return
    
    # Test Google Sheets
    try:
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)
        logger.info(f"✅ Google Sheets OK: {spreadsheet.title} > {worksheet.title}")
    except Exception as e:
        logger.error(f"❌ Google Sheets Error: {e}")
        logger.error("Pastikan:")
        logger.error("1. File credentials.json valid atau GOOGLE_CREDENTIALS sudah di-set")
        logger.error("2. Spreadsheet 'Catatan Keuangan' sudah dibuat")
        logger.error("3. Service account sudah di-share ke spreadsheet")
        return
    
    # Start Flask
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask server started")
    
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
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back$'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^cek$'))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot ready!")
    logger.info("=" * 60)
    
    # Run
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()