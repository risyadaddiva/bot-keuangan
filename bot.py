import os
import logging
import gspread
from oauth2client.service_account import ServiceAccountCredentials
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
from threading import Thread
import json
from datetime import datetime

# ============================================
# KONFIGURASI
# ============================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = "Catatan Keuangan"  # Nama spreadsheet yang sudah ada
WORKSHEET_NAME = "Transaksi"  # Nama sheet/tab di dalam spreadsheet

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# States untuk ConversationHandler
NOMINAL, KETERANGAN, KATEGORI = range(3)
temp_data = {}

# ============================================
# FLASK APP (Untuk keep-alive dan health check)
# ============================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot Keuangan Aktif!"

@app.route('/health')
def health():
    return {
        "status": "ok", 
        "timestamp": datetime.now().isoformat(),
        "spreadsheet": SPREADSHEET_NAME
    }

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ============================================
# GOOGLE SHEETS SETUP
# ============================================
def setup_google_sheets():
    """
    Koneksi ke Google Sheets menggunakan service account.
    Spreadsheet harus sudah ada dengan nama "Catatan Keuangan"
    dan sudah di-share ke service account.
    """
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Load credentials dari environment variable (untuk production)
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    
    if creds_json:
        # Production: load dari env variable
        try:
            creds_dict = json.loads(creds_json)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            logger.info("Loaded credentials from environment variable")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in GOOGLE_CREDENTIALS: {e}")
            raise
    else:
        # Development: load dari file
        try:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
            logger.info("Loaded credentials from credentials.json file")
        except FileNotFoundError:
            logger.error("credentials.json not found and GOOGLE_CREDENTIALS not set")
            raise
    
    client = gspread.authorize(creds)
    
    # Buka spreadsheet dengan nama yang sudah ada
    try:
        spreadsheet = client.open(SPREADSHEET_NAME)
        logger.info(f"Successfully opened spreadsheet: {spreadsheet.title}")
        return spreadsheet
    except gspread.SpreadsheetNotFound:
        logger.error(f"Spreadsheet '{SPREADSHEET_NAME}' not found!")
        logger.error("Please ensure:")
        logger.error("1. Spreadsheet exists with exact name 'Catatan Keuangan'")
        logger.error("2. Service account email has been shared to the spreadsheet")
        raise
    except Exception as e:
        logger.error(f"Error opening spreadsheet: {e}")
        raise

def get_or_create_worksheet(spreadsheet, worksheet_name=WORKSHEET_NAME):
    """
    Ambil worksheet dengan nama tertentu, atau buat baru jika belum ada.
    Jika worksheet baru dibuat, tambahkan header.
    """
    try:
        # Coba ambil worksheet yang sudah ada
        worksheet = spreadsheet.worksheet(worksheet_name)
        logger.info(f"Using existing worksheet: {worksheet_name}")
    except gspread.WorksheetNotFound:
        # Buat worksheet baru jika belum ada
        logger.info(f"Creating new worksheet: {worksheet_name}")
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name, 
            rows=1000, 
            cols=5
        )
        # Tambahkan header
        headers = ["Tanggal", "Tipe", "Nominal", "Kategori", "Keterangan"]
        worksheet.append_row(headers)
        
        # Format header (bold dengan background abu)
        try:
            worksheet.format('A1:E1', {
                'textFormat': {'bold': True},
                'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9},
                'horizontalAlignment': 'CENTER'
            })
        except Exception as e:
            logger.warning(f"Could not format header: {e}")
        
        logger.info(f"Worksheet '{worksheet_name}' created with headers")
    
    return worksheet

# ============================================
# BOT HANDLERS
# ============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk command /start"""
    keyboard = [
        [InlineKeyboardButton("📝 Lapor Transaksi", callback_data='lapor')],
        [InlineKeyboardButton("📊 Cek Laporan", callback_data='cek')]
    ]
    
    await update.message.reply_text(
        "💰 *Bot Pencatatan Keuangan*\n\n"
        "Selamat datang! Bot ini akan membantu mencatat pemasukan dan pengeluaran Anda.\n\n"
        "Silakan pilih menu:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk tombol menu utama"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'lapor':
        # Menu lapor - pilih tipe transaksi
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
        # Menu cek laporan - kirim link spreadsheet
        try:
            spreadsheet = setup_google_sheets()
            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit"
            
            await query.edit_message_text(
                f"📊 *Laporan Keuangan*\n\n"
                f"Nama File: `{spreadsheet.title}`\n\n"
                f"[Klik di sini untuk membuka spreadsheet]({sheet_url})\n\n"
                f"Data tersimpan di worksheet: *{WORKSHEET_NAME}*",
                parse_mode='Markdown',
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Kembali ke Menu", callback_data='back')
                ]])
            )
        except Exception as e:
            logger.error(f"Error accessing spreadsheet: {e}")
            await query.edit_message_text(
                "❌ Terjadi kesalahan saat mengakses spreadsheet.\n"
                "Pastikan spreadsheet sudah dibagikan ke service account.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Kembali", callback_data='back')
                ]])
            )
        return ConversationHandler.END

async def tipe_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler setelah memilih tipe (pemasukan/pengeluaran)"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    tipe = query.data.replace('tipe_', '')
    temp_data[user_id] = {'tipe': tipe}
    
    emoji = "💰" if tipe == 'pemasukan' else "💸"
    
    await query.edit_message_text(
        f"{emoji} Anda memilih *{tipe.upper()}*\n\n"
        f"Silakan masukkan nominal angka (contoh: 50000 atau 100000):",
        parse_mode='Markdown'
    )
    return NOMINAL

async def get_nominal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler input nominal"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Bersihkan input (hapus titik, koma, spasi)
    clean_text = text.replace('.', '').replace(',', '').replace(' ', '')
    
    try:
        nominal = int(clean_text)
        if nominal <= 0:
            raise ValueError("Nominal harus positif")
        if nominal > 999999999:  # Batas maksimal 1 miliar
            raise ValueError("Nominal terlalu besar")
            
        temp_data[user_id]['nominal'] = nominal
        
        await update.message.reply_text(
            "✅ Nominal tersimpan!\n\n"
            "Sekarang kirim keterangan transaksi:\n"
            "_contoh: Gaji bulan Januari, Makan siang, dll_",
            parse_mode='Markdown'
        )
        return KETERANGAN
        
    except ValueError as e:
        error_msg = str(e) if str(e) else "Format tidak valid"
        await update.message.reply_text(
            f"❌ *Error:* {error_msg}\n\n"
            f"Nominal harus berupa angka positif.\n"
            f"Contoh: `50000`, `100.000`, `1.500.000`",
            parse_mode='Markdown'
        )
        return NOMINAL

async def get_keterangan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler input keterangan"""
    user_id = update.effective_user.id
    keterangan = update.message.text.strip()
    
    if len(keterangan) < 2:
        await update.message.reply_text(
            "❌ Keterangan terlalu pendek (minimal 2 karakter). Coba lagi:"
        )
        return KETERANGAN
    
    if len(keterangan) > 100:
        await update.message.reply_text(
            "❌ Keterangan terlalu panjang (maksimal 100 karakter). Coba lagi:"
        )
        return KETERANGAN
    
    temp_data[user_id]['keterangan'] = keterangan
    tipe = temp_data[user_id]['tipe']
    
    # Jika pemasukan, langsung simpan tanpa kategori
    if tipe == 'pemasukan':
        return await save_transaction(update, context, user_id, kategori="Pemasukan")
    
    # Jika pengeluaran, tampilkan pilihan kategori
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
    """Handler pilihan kategori"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    kategori = query.data.replace('cat_', '')
    
    return await save_transaction(
        update, context, user_id, kategori, 
        edit_message=query.edit_message_text
    )

async def save_transaction(update, context, user_id, kategori, edit_message=None):
    """
    Simpan transaksi ke Google Sheets.
    Fungsi ini dipanggil setelah semua data lengkap.
    """
    data = temp_data[user_id]
    
    try:
        # Koneksi ke Google Sheets
        spreadsheet = setup_google_sheets()
        worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)
        
        # Siapkan data untuk disimpan
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data['tipe'].capitalize(),
            data['nominal'],
            kategori,
            data['keterangan']
        ]
        
        # Simpan ke worksheet
        worksheet.append_row(row)
        logger.info(f"Transaction saved: {row}")
        
        # Format pesan konfirmasi
        tipe_icon = "💰" if data['tipe'] == 'pemasukan' else "💸"
        nominal_fmt = f"Rp {data['nominal']:,}".replace(',', '.')
        
        message = (
            f"✅ *Transaksi Berhasil Disimpan!*\n\n"
            f"{tipe_icon} *Tipe:* {data['tipe'].capitalize()}\n"
            f"💵 *Nominal:* {nominal_fmt}\n"
            f"📁 *Kategori:* {kategori}\n"
            f"📝 *Keterangan:* {data['keterangan']}\n"
            f"📅 *Waktu:* {datetime.now().strftime('%d-%m-%Y %H:%M')}\n\n"
            f"Data tersimpan di spreadsheet: *{SPREADSHEET_NAME}*"
        )
        
    except Exception as e:
        logger.error(f"Error saving transaction: {e}")
        message = (
            f"❌ *Gagal menyimpan transaksi!*\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Silakan coba lagi atau hubungi admin."
        )
    
    # Tombol navigasi
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Lapor Lagi", callback_data='lapor'),
            InlineKeyboardButton("🔙 Menu Utama", callback_data='back')
        ]
    ])
    
    # Kirim pesan (edit jika dari callback, reply jika dari message)
    if edit_message:
        await edit_message(message, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=keyboard)
    
    # Bersihkan data temporary
    if user_id in temp_data:
        del temp_data[user_id]
    
    return ConversationHandler.END

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler tombol kembali ke menu utama"""
    query = update.callback_query
    await query.answer()
    
    # Bersihkan data jika ada yang tertinggal
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    
    keyboard = [
        [InlineKeyboardButton("📝 Lapor Transaksi", callback_data='lapor')],
        [InlineKeyboardButton("📊 Cek Laporan", callback_data='cek')]
    ]
    
    await query.edit_message_text(
        "💰 *Bot Pencatatan Keuangan*\n\n"
        "Selamat datang kembali!\n\n"
        "Silakan pilih menu:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk membatalkan operasi"""
    user_id = update.effective_user.id
    if user_id in temp_data:
        del temp_data[user_id]
    
    await update.message.reply_text(
        "❌ Operasi dibatalkan. Data tidak disimpan.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Menu Utama", callback_data='back')
        ]])
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk error global"""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Terjadi kesalahan sistem. Silakan coba lagi atau ketik /start"
        )

# ============================================
# MAIN FUNCTION
# ============================================
def main():
    logger.info("=" * 50)
    logger.info("Starting Bot Keuangan")
    logger.info(f"Spreadsheet target: {SPREADSHEET_NAME}")
    logger.info("=" * 50)
    
    # Validasi environment variables
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set!")
        return
    
    # Test koneksi ke Google Sheets sebelum start bot
    try:
        spreadsheet = setup_google_sheets()
        logger.info(f"✅ Successfully connected to spreadsheet: {spreadsheet.title}")
        
        # Test akses worksheet
        worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)
        logger.info(f"✅ Worksheet ready: {worksheet.title}")
        
    except Exception as e:
        logger.error(f"❌ Failed to connect to Google Sheets: {e}")
        logger.error("Please check:")
        logger.error("1. GOOGLE_CREDENTIALS environment variable is set correctly")
        logger.error(f"2. Spreadsheet '{SPREADSHEET_NAME}' exists and is shared to service account")
        return
    
    # Start Flask server di thread terpisah (untuk keep-alive)
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask keep-alive server started")
    
    # Setup Telegram bot
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation handler untuk flow laporan
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_handler, pattern='^lapor$')
        ],
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
        fallbacks=[
            CommandHandler('cancel', cancel),
            CommandHandler('start', start)
        ],
    )
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back$'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^cek$'))
    application.add_error_handler(error_handler)
    
    logger.info("✅ Bot is running and ready to receive messages!")
    logger.info("=" * 50)
    
    # Jalankan bot
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == '__main__':
    main()
