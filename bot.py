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

# Load .env file jika ada (untuk local development & PythonAnywhere)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================
# KONFIGURASI
# ============================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = "Catatan Keuangan"
WORKSHEET_NAME = "Transaksi"

# Validasi
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN tidak ditemukan! Pastikan sudah di-set di environment variable.")

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
# GOOGLE SHEETS SETUP
# ============================================
def get_credentials():
    """Dapatkan credentials dari environment variable"""
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS tidak ditemukan!")
    
    try:
        creds_info = json.loads(creds_json)
        credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
        return credentials
    except Exception as e:
        logger.error(f"Error parsing credentials: {e}")
        raise

def setup_google_sheets():
    """Setup koneksi ke Google Sheets"""
    try:
        credentials = get_credentials()
        client = gspread.authorize(credentials)
        
        try:
            spreadsheet = client.open(SPREADSHEET_NAME)
            logger.info(f"✅ Spreadsheet opened: {spreadsheet.title}")
            return spreadsheet
        except gspread.SpreadsheetNotFound:
            logger.error(f"❌ Spreadsheet '{SPREADSHEET_NAME}' not found!")
            raise
            
    except Exception as e:
        logger.error(f"❌ Setup failed: {e}")
        raise

def get_or_create_worksheet(spreadsheet, worksheet_name=WORKSHEET_NAME):
    """Ambil atau buat worksheet"""
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        logger.info(f"✅ Using worksheet: {worksheet_name}")
    except gspread.WorksheetNotFound:
        logger.info(f"📝 Creating worksheet: {worksheet_name}")
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
# BOT HANDLERS (sama seperti sebelumnya)
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Lapor Transaksi", callback_data='lapor')],
        [InlineKeyboardButton("📊 Cek Laporan", callback_data='cek')]
    ]
    await update.message.reply_text(
        "💰 *Bot Pencatatan Keuangan*\n\nPilih menu:",
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
        await query.edit_message_text("Pilih jenis:", reply_markup=InlineKeyboardMarkup(keyboard))
        return NOMINAL
    
    elif query.data == 'cek':
        try:
            spreadsheet = setup_google_sheets()
            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit"
            await query.edit_message_text(
                f"📊 [Buka Spreadsheet]({sheet_url})",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data='back')]])
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kembali", callback_data='back')]]))
        return ConversationHandler.END

async def tipe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    tipe = query.data.replace('tipe_', '')
    temp_data[user_id] = {'tipe': tipe}
    emoji = "💰" if tipe == 'pemasukan' else "💸"
    await query.edit_message_text(f"{emoji} *{tipe.upper()}*\n\nMasukkan nominal:", parse_mode='Markdown')
    return NOMINAL

async def get_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().replace('.', '').replace(',', '').replace(' ', '').replace('Rp', '')
    try:
        nominal = int(text)
        if nominal <= 0:
            raise ValueError("Nominal harus positif")
        temp_data[user_id]['nominal'] = nominal
        await update.message.reply_text("✅ Nominal tersimpan!\n\nKirim keterangan:")
        return KETERANGAN
    except ValueError:
        await update.message.reply_text("❌ Masukkan angka valid (contoh: 50000):")
        return NOMINAL

async def get_keterangan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keterangan = update.message.text.strip()
    if len(keterangan) < 2:
        await update.message.reply_text("❌ Terlalu pendek. Coba lagi:")
        return KETERANGAN
    temp_data[user_id]['keterangan'] = keterangan
    tipe = temp_data[user_id]['tipe']
    if tipe == 'pemasukan':
        return await save_transaction(update, context, user_id, "Pemasukan")
    keyboard = [
        [InlineKeyboardButton("🍽 Makan", callback_data='cat_Makan')],
        [InlineKeyboardButton("🚬 Rokok", callback_data='cat_Rokok')],
        [InlineKeyboardButton("⛽ Bensin", callback_data='cat_Bensin')],
        [InlineKeyboardButton("☕ Nongkrong", callback_data='cat_Nongkrong')],
        [InlineKeyboardButton("📦 Lain-lain", callback_data='cat_Lain-lain')]
    ]
    await update.message.reply_text("Pilih kategori:", reply_markup=InlineKeyboardMarkup(keyboard))
    return KATEGORI

async def get_kategori(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    kategori = query.data.replace('cat_', '')
    return await save_transaction(update, context, user_id, kategori, edit_message=query.edit_message_text)

async def save_transaction(update, context, user_id, kategori, edit_message=None):
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
        icon = "💰" if data['tipe'] == 'pemasukan' else "💸"
        nominal_fmt = f"Rp {data['nominal']:,}".replace(',', '.')
        message = f"✅ *Tersimpan!*\n\n{icon} {data['tipe'].capitalize()}\n💵 {nominal_fmt}\n📁 {kategori}\n📝 {data['keterangan']}"
    except Exception as e:
        message = f"❌ Gagal: {str(e)}"
    if user_id in temp_data:
        del temp_data[user_id]
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📝 Lagi", callback_data='lapor'), InlineKeyboardButton("🔙 Menu", callback_data='back')]])
    if edit_message:
        await edit_message(message, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
    return ConversationHandler.END

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    keyboard = [[InlineKeyboardButton("📝 Lapor", callback_data='lapor')], [InlineKeyboardButton("📊 Cek", callback_data='cek')]]
    await query.edit_message_text("💰 *Bot Keuangan*\n\nPilih menu:", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    await update.message.reply_text("❌ Dibatalkan.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data='back')]]))
    return ConversationHandler.END

# ============================================
# MAIN
# ============================================
def main():
    logger.info("🚀 BOT KEUANGAN STARTING")
    
    # Test Google Sheets
    try:
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)
        logger.info(f"✅ Google Sheets OK: {spreadsheet.title}")
    except Exception as e:
        logger.error(f"❌ Google Sheets Error: {e}")
        return
    
    # Setup bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern='^lapor$')],
        states={
            NOMINAL: [CallbackQueryHandler(tipe_handler, pattern='^tipe_'), MessageHandler(filters.TEXT & ~filters.COMMAND, get_nominal)],
            KETERANGAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_keterangan)],
            KATEGORI: [CallbackQueryHandler(get_kategori, pattern='^cat_')]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back$'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^cek$'))
    
    logger.info("✅ Bot ready!")
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
