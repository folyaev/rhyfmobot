import asyncio
import random
import os
import logging
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from database import RhymesRepository
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, NetworkError, TimedOut
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    TypeHandler,
    filters,
)

logging.basicConfig(
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    level=os.getenv('LOG_LEVEL', 'INFO').upper(),
)
logger = logging.getLogger(__name__)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

warnings.simplefilter('ignore', PTBUserWarning)
warnings.filterwarnings(
    'ignore',
    message=r".*per_message=False.*CallbackQueryHandler.*",
    category=PTBUserWarning,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv('DATA_DIR', str(BASE_DIR)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv('DB_PATH', str(DATA_DIR / 'rhymes.db')))
WORDS_PATH = Path(os.getenv('WORDS_PATH', str(DATA_DIR / 'words.txt')))
SOURCE_WORDS_PATH = BASE_DIR / 'words.txt'
MAX_WORD_LENGTH = int(os.getenv('MAX_WORD_LENGTH', '64'))
CHALLENGE_TIMEZONE_NAME = os.getenv('CHALLENGE_TIMEZONE', 'Europe/Simferopol')
CHALLENGE_START_HOUR = int(os.getenv('CHALLENGE_START_HOUR', '10'))
CHALLENGE_END_HOUR = int(os.getenv('CHALLENGE_END_HOUR', '21'))
CHALLENGE_SAMPLE_SIZE = int(os.getenv('CHALLENGE_SAMPLE_SIZE', '100'))
CHALLENGE_POLL_SECONDS = int(os.getenv('CHALLENGE_POLL_SECONDS', '60'))
DEFAULT_WORDS = 'море\nгора\nлес\nзвезда\nлуна\n'
RHYMES_REPOSITORY = RhymesRepository(DB_PATH)

try:
    CHALLENGE_TIMEZONE = ZoneInfo(CHALLENGE_TIMEZONE_NAME)
except ZoneInfoNotFoundError:
    logger.warning("Часовой пояс %s не найден, используется UTC", CHALLENGE_TIMEZONE_NAME)
    CHALLENGE_TIMEZONE = timezone.utc

def get_api_token():
    token = os.getenv('API_TOKEN')
    if not token:
        raise RuntimeError('Environment variable API_TOKEN is not set')
    return token


def ensure_words_file():
    if WORDS_PATH.exists():
        return
    if SOURCE_WORDS_PATH.exists() and SOURCE_WORDS_PATH != WORDS_PATH:
        WORDS_PATH.write_bytes(SOURCE_WORDS_PATH.read_bytes())
        return
    WORDS_PATH.write_text(DEFAULT_WORDS, encoding='utf-8')


def normalize_words(raw_words):
    seen = set()
    normalized = []
    for raw in raw_words:
        word = raw.strip().lower()
        if not word or len(word) > MAX_WORD_LENGTH or word in seen:
            continue
        seen.add(word)
        normalized.append(word)
    return normalized


def is_valid_word(word):
    return bool(word) and len(word) <= MAX_WORD_LENGTH and ',' not in word

# Состояния для ConversationHandler
CHOOSING_RHYMES, INPUTTING_WORD = range(2)
EDITING_RHYMES = 0  # Состояние для редактирования рифм

# Чтение слов из файла words.txt
def load_words():
    ensure_words_file()
    with WORDS_PATH.open('r', encoding='utf-8') as file:
        return [line.strip().lower() for line in file if line.strip()]

words_list = load_words()

def save_words():
    with WORDS_PATH.open('w', encoding='utf-8') as file:
        for word in words_list:
            file.write(word + '\n')

def add_words_to_file(words):
    existing_words = set(words_list)
    new_words = [word for word in normalize_words(words) if word not in existing_words]
    if new_words:
        with WORDS_PATH.open('a', encoding='utf-8') as f:
            for word in new_words:
                f.write(word + '\n')
        words_list.extend(new_words)

def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🎲 Новое слово', callback_data='new_word')],
        [InlineKeyboardButton('📝 Ввести слово', callback_data='input_word')],
    ])

def get_word_actions():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('➡️ Следующее слово', callback_data='next_word'),
            InlineKeyboardButton('❌ Удалить слово', callback_data='delete_word'),
        ],
        [
            InlineKeyboardButton('📝 Ввести слово', callback_data='input_word'),
            InlineKeyboardButton('👀 Показать рифмы', callback_data='show_current_rhymes'),
        ],
    ])

def get_rhymes_prompt(word):
    return (
        f"Ваше слово: **{word}**\n\n"
        "Введите рифмы к этому слову, разделяя их запятыми."
    )

def get_next_challenge_at(now=None, start_from_tomorrow=False):
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(CHALLENGE_TIMEZONE)
    day_offset = 1 if start_from_tomorrow else 0
    while True:
        day = (local_now + timedelta(days=day_offset)).date()
        start = datetime.combine(
            day,
            datetime.min.time(),
            tzinfo=CHALLENGE_TIMEZONE,
        ).replace(hour=CHALLENGE_START_HOUR)
        end = start.replace(hour=CHALLENGE_END_HOUR)
        candidate = start + timedelta(
            seconds=random.randint(0, int((end - start).total_seconds()))
        )
        if candidate > local_now:
            return candidate.astimezone(timezone.utc)
        day_offset += 1

def get_challenge_word():
    if not words_list:
        return None
    sample_size = min(CHALLENGE_SAMPLE_SIZE, len(words_list))
    candidates = random.sample(words_list, sample_size)
    rhyme_counts = RHYMES_REPOSITORY.get_rhyme_counts(candidates)
    minimum_count = min(rhyme_counts.values())
    return random.choice([
        word for word, count in rhyme_counts.items() if count == minimum_count
    ])

def get_challenge_markup(word):
    callback_data = f'challenge_word:{word}'
    if len(callback_data.encode('utf-8')) > 64:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✍️ Срифмовать', callback_data=callback_data)],
    ])

async def send_challenge(bot, chat_id):
    word = get_challenge_word()
    if word is None:
        logger.warning("Не удалось отправить челлендж: список слов пуст")
        return
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🎯 Дневной рифмо-челлендж\n\n"
            f"Придумайте рифмы к слову: {word}"
        ),
        reply_markup=get_challenge_markup(word),
    )

async def challenge_worker(application):
    while True:
        now = datetime.now(timezone.utc)
        due_subscriptions = RHYMES_REPOSITORY.get_due_challenge_subscriptions(
            now.isoformat()
        )
        for subscription in due_subscriptions:
            chat_id = subscription['chat_id']
            next_send_at = get_next_challenge_at(now, start_from_tomorrow=True)
            try:
                await send_challenge(application.bot, chat_id)
            except Forbidden:
                logger.info("Отключаю челленджи для недоступного чата %s", chat_id)
                RHYMES_REPOSITORY.unsubscribe_from_challenges(chat_id)
                continue
            except Exception:
                logger.exception("Не удалось отправить челлендж в чат %s", chat_id)
            RHYMES_REPOSITORY.mark_challenge_sent(
                chat_id,
                now.isoformat(),
                next_send_at.isoformat(),
            )
        await asyncio.sleep(CHALLENGE_POLL_SECONDS)

async def post_init(application):
    application.create_task(challenge_worker(application))

async def ensure_default_challenge_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.effective_chat is None:
        return
    next_send_at = get_next_challenge_at()
    RHYMES_REPOSITORY.ensure_challenge_subscription(
        update.effective_chat.id,
        next_send_at.isoformat(),
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=get_main_menu()
    )

async def new_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        chat_id = query.message.chat_id
    else:
        chat_id = update.effective_chat.id

    # Удаляем сообщение с благодарностью, если оно есть
    thank_you_message_id = context.user_data.get('thank_you_message_id')
    if thank_you_message_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=thank_you_message_id)
        except Exception as e:
            logger.warning("Не удалось удалить сообщение с благодарностью: %s", e)
        context.user_data.pop('thank_you_message_id', None)

    if not words_list:
        await context.bot.send_message(chat_id=chat_id, text="Список слов пуст. Нет слов для отображения.")
        return ConversationHandler.END

    word = random.choice(words_list)
    context.user_data['chosen_word'] = word

    if query:
        # Редактируем сообщение, заменяя его на новое слово и кнопки
        sent_message = await query.edit_message_text(
            get_rhymes_prompt(word),
            parse_mode='Markdown',
            reply_markup=get_word_actions()
        )
    else:
        # Если функция вызвана не через CallbackQuery (например, при /start)
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=get_rhymes_prompt(word),
            parse_mode='Markdown',
            reply_markup=get_word_actions()
        )

    # Сохраняем идентификатор сообщения
    context.user_data['bot_message_id'] = sent_message.message_id
    return CHOOSING_RHYMES

async def accept_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    word = query.data.removeprefix('challenge_word:')
    context.user_data['chosen_word'] = word
    sent_message = await query.message.reply_text(
        get_rhymes_prompt(word),
        parse_mode='Markdown',
        reply_markup=get_word_actions(),
    )
    context.user_data['bot_message_id'] = sent_message.message_id
    return CHOOSING_RHYMES

async def next_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Удаляем сообщение с благодарностью, если оно есть
    thank_you_message_id = context.user_data.get('thank_you_message_id')
    if thank_you_message_id:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=thank_you_message_id)
        except Exception as e:
            logger.warning("Не удалось удалить сообщение с благодарностью: %s", e)
        context.user_data.pop('thank_you_message_id', None)

    # Очищаем предыдущее состояние и данные пользователя
    context.user_data.pop('chosen_word', None)

    if not words_list:
        await query.edit_message_text("Список слов пуст. Нет слов для отображения.")
        return ConversationHandler.END

    # Генерируем новое слово и редактируем сообщение
    word = random.choice(words_list)
    context.user_data['chosen_word'] = word

    sent_message = await query.edit_message_text(
        get_rhymes_prompt(word),
        parse_mode='Markdown',
        reply_markup=get_word_actions()
    )
    context.user_data['bot_message_id'] = sent_message.message_id
    return CHOOSING_RHYMES

async def delete_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    word = context.user_data.get('chosen_word')
    if word:
        # Удаляем слово из списка и файла
        words_list.remove(word)
        save_words()
        context.user_data.pop('chosen_word', None)

        # Удаляем сообщение с благодарностью, если оно есть
        thank_you_message_id = context.user_data.get('thank_you_message_id')
        if thank_you_message_id:
            try:
                await context.bot.delete_message(chat_id=query.message.chat_id, message_id=thank_you_message_id)
            except Exception as e:
                logger.warning("Не удалось удалить сообщение с благодарностью: %s", e)
            context.user_data.pop('thank_you_message_id', None)

        if not words_list:
            await query.edit_message_text("Слово удалено. Список слов пуст.")
            return ConversationHandler.END

        # Генерируем новое слово и редактируем сообщение
        new_word = random.choice(words_list)
        context.user_data['chosen_word'] = new_word

        sent_message = await query.edit_message_text(
            f"Слово **{word}** удалено.\n\nВаше новое слово: **{new_word}**\n\nВведите рифмы к этому слову, разделяя их запятыми.",
            parse_mode='Markdown',
            reply_markup=get_word_actions()
        )
        context.user_data['bot_message_id'] = sent_message.message_id
        return CHOOSING_RHYMES
    else:
        await query.edit_message_text("Слово не найдено или уже было удалено.")
        return ConversationHandler.END

async def input_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Удаляем предыдущее сообщение, если необходимо
    bot_message_id = context.user_data.get('bot_message_id')
    if bot_message_id:
        try:
            await context.bot.delete_message(chat_id=query.message.chat_id, message_id=bot_message_id)
        except Exception as e:
            logger.warning("Не удалось удалить сообщение: %s", e)
        context.user_data.pop('bot_message_id', None)

    # Отправляем новое сообщение с запросом ввести слово
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Введите слово, которое вы хотите использовать:"
    )
    return INPUTTING_WORD

async def receive_input_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_word = update.message.text.strip().lower()
    if new_word:
        if not is_valid_word(new_word):
            await update.message.reply_text(
                f"Слово должно быть без запятых и не длиннее {MAX_WORD_LENGTH} символов."
            )
            return INPUTTING_WORD
        if new_word not in words_list:
            words_list.append(new_word)
            save_words()
            await update.message.reply_text(f"Слово **{new_word}** добавлено.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"Слово **{new_word}** уже есть в списке.", parse_mode='Markdown')

        # Переходим к вводу рифм для нового слова
        context.user_data['chosen_word'] = new_word

        # Отправляем сообщение с предложением ввести рифмы
        sent_message = await update.message.reply_text(
            get_rhymes_prompt(new_word),
            parse_mode='Markdown',
            reply_markup=get_word_actions()
        )
        context.user_data['bot_message_id'] = sent_message.message_id

        return CHOOSING_RHYMES
    else:
        await update.message.reply_text("Пожалуйста, введите корректное слово.")
        return INPUTTING_WORD

async def receive_rhymes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = context.user_data.get('chosen_word')
    if word:
        rhymes = normalize_words(update.message.text.split(','))
        if not rhymes:
            await update.message.reply_text("Введите хотя бы одну рифму через запятую.")
            return CHOOSING_RHYMES
        RHYMES_REPOSITORY.add_rhyme_group(word.lower(), rhymes)

        # Удаляем предыдущее сообщение бота
        bot_message_id = context.user_data.get('bot_message_id')
        if bot_message_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_message_id)
            except Exception as e:
                logger.warning("Не удалось удалить сообщение: %s", e)
            context.user_data.pop('bot_message_id', None)

        # Отправляем сообщение с благодарностью и сохраняем его идентификатор
        thank_you_message = await update.message.reply_text(
            "✨ Спасибо! Ваши рифмы сохранены.\nВы можете выбрать дальнейшее действие."
        )
        context.user_data['thank_you_message_id'] = thank_you_message.message_id

        # Предлагаем дальнейшие действия
        await update.message.reply_text("Что дальше?", reply_markup=get_main_menu())

        add_words_to_file(rhymes)
        context.user_data.pop('chosen_word', None)

        return ConversationHandler.END
    else:
        await update.message.reply_text("Пожалуйста, нажмите кнопку ниже, чтобы получить слово для рифм.")
        return ConversationHandler.END

async def show_rhymes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Пожалуйста, укажите слово после команды.\nНапример: /r море")
        return
    word = ' '.join(args).strip().lower()
    context.user_data['edit_word'] = word  # Сохраняем слово для последующего редактирования
    rows = RHYMES_REPOSITORY.get_rhymes(word)
    if rows:
        rhymes = ', '.join(sorted(set(rows)))
        # Добавляем кнопку "Редактировать"
        keyboard = [
            [InlineKeyboardButton('✏️ Редактировать', callback_data='edit_rhymes')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✨ Рифмы к слову **{word}**:\n{rhymes}",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(f"Рифм к слову **{word}** пока нет.", parse_mode='Markdown')

async def show_current_rhymes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    word = context.user_data.get('chosen_word')
    if word:
        rows = RHYMES_REPOSITORY.get_rhymes(word)
        if rows:
            rhymes = ', '.join(sorted(set(rows)))
            await query.message.reply_text(
                f"✨ Рифмы к слову **{word}**:\n{rhymes}",
                parse_mode='Markdown'
            )
        else:
            await query.message.reply_text(f"Рифм к слову **{word}** пока нет.", parse_mode='Markdown')
    else:
        await query.message.reply_text("Слово не найдено.")

async def edit_rhymes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    word = context.user_data.get('edit_word')
    if word:
        await query.message.reply_text(
            f"Введите новые рифмы для слова **{word}**, разделяя их запятыми:",
            parse_mode='Markdown'
        )
        return EDITING_RHYMES
    else:
        await query.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def receive_new_rhymes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = context.user_data.get('edit_word')
    if word:
        new_rhymes = normalize_words(update.message.text.split(','))
        if new_rhymes:
            RHYMES_REPOSITORY.replace_rhymes_for_word(word, new_rhymes)
            await update.message.reply_text(f"Рифмы для слова **{word}** успешно обновлены.", parse_mode='Markdown')
            context.user_data.pop('edit_word', None)
            return ConversationHandler.END
        else:
            await update.message.reply_text("Пожалуйста, введите хотя бы одну рифму.")
            return EDITING_RHYMES
    else:
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, TimedOut):
        logger.warning("Таймаут Telegram API: %s", context.error)
        return
    if isinstance(context.error, NetworkError):
        logger.warning("Сетевая ошибка Telegram API: %s", context.error)
        return

    logger.exception("Необработанная ошибка в обработчике Telegram", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Внутренняя ошибка. Попробуйте еще раз через пару секунд.",
            )
        except Exception as send_error:
            logger.warning("Не удалось отправить сообщение об ошибке: %s", send_error)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = RHYMES_REPOSITORY.get_stats()
    await update.message.reply_text(
        "Статистика базы рифм:\n"
        f"Слов с сохранёнными связями: {stats['words_count']}\n"
        f"Связей между словами: {stats['links_count']}\n"
        f"Подписчиков на челленджи: {stats['subscribers_count']}"
    )


async def challenge_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    next_send_at = get_next_challenge_at()
    RHYMES_REPOSITORY.subscribe_to_challenges(
        update.effective_chat.id,
        next_send_at.isoformat(),
    )
    await update.message.reply_text(
        "Дневные рифмо-челленджи включены.\n"
        f"Следующий придёт {format_challenge_time(next_send_at)}."
    )


async def challenge_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    RHYMES_REPOSITORY.unsubscribe_from_challenges(update.effective_chat.id)
    await update.message.reply_text("Дневные рифмо-челленджи отключены.")


async def challenge_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscription = RHYMES_REPOSITORY.get_challenge_subscription(
        update.effective_chat.id
    )
    if subscription is None or not subscription['enabled']:
        await update.message.reply_text(
            "Дневные рифмо-челленджи отключены. Включить: /challenge_on"
        )
        return
    next_send_at = datetime.fromisoformat(subscription['next_send_at'])
    await update.message.reply_text(
        "Дневные рифмо-челленджи включены.\n"
        f"Следующий придёт {format_challenge_time(next_send_at)}."
    )


async def challenge_now_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_challenge(context.bot, update.effective_chat.id)


def format_challenge_time(value):
    return value.astimezone(CHALLENGE_TIMEZONE).strftime('%d.%m.%Y в %H:%M')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "Доступные команды:\n"
        "/start - начать работу с ботом\n"
        "/help - показать это сообщение\n"
        "/r <слово> - показать рифмы к указанному слову\n"
        "/stats - показать статистику базы рифм\n"
        "/challenge_on - включить дневные рифмо-челленджи\n"
        "/challenge_off - отключить дневные рифмо-челленджи\n"
        "/challenge_status - показать статус челленджей\n"
        "/challenge_now - получить челлендж прямо сейчас\n"
    )
    await update.message.reply_text(help_text, reply_markup=get_main_menu())

def main():
    RHYMES_REPOSITORY.init_db()

    application = (
        ApplicationBuilder()
        .token(get_api_token())
        .connect_timeout(20)
        .read_timeout(20)
        .write_timeout(20)
        .pool_timeout(20)
        .post_init(post_init)
        .build()
    )

    # Основной ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(new_word, pattern='^new_word$'),
            CallbackQueryHandler(input_word, pattern='^input_word$'),
            CallbackQueryHandler(accept_challenge, pattern='^challenge_word:'),
        ],
        states={
            CHOOSING_RHYMES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_rhymes),
                CallbackQueryHandler(next_word, pattern='^next_word$'),
                CallbackQueryHandler(delete_word, pattern='^delete_word$'),
                CallbackQueryHandler(input_word, pattern='^input_word$'),
                CallbackQueryHandler(show_current_rhymes, pattern='^show_current_rhymes$'),  # Добавлено
            ],
            INPUTTING_WORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_input_word),
            ],
        },
        fallbacks=[],
    )

    # ConversationHandler для редактирования рифм
    edit_rhymes_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(edit_rhymes, pattern='^edit_rhymes$'),
        ],
        states={
            EDITING_RHYMES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_rhymes),
            ],
        },
        fallbacks=[],
    )

    application.add_handler(
        TypeHandler(Update, ensure_default_challenge_subscription),
        group=-1,
    )
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('r', show_rhymes))  # Обновлено
    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('challenge_on', challenge_on_command))
    application.add_handler(CommandHandler('challenge_off', challenge_off_command))
    application.add_handler(CommandHandler('challenge_status', challenge_status_command))
    application.add_handler(CommandHandler('challenge_now', challenge_now_command))
    application.add_handler(conv_handler)
    application.add_handler(edit_rhymes_conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))
    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
