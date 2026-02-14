import random
import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
)

def get_api_token():
    token = os.getenv('API_TOKEN')
    if not token:
        raise RuntimeError('Environment variable API_TOKEN is not set')
    return token

# Состояния для ConversationHandler
CHOOSING_RHYMES, INPUTTING_WORD = range(2)
EDITING_RHYMES = 0  # Состояние для редактирования рифм

# Функция для инициализации базы данных
def init_db():
    conn = sqlite3.connect('rhymes.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rhymes (
            word TEXT NOT NULL,
            rhyme TEXT NOT NULL,
            UNIQUE(word, rhyme)
        )
    ''')
    conn.commit()
    conn.close()

# Чтение слов из файла words.txt
def load_words():
    if not os.path.exists('words.txt'):
        with open('words.txt', 'w', encoding='utf-8') as f:
            f.write('море\nгора\nлес\nзвезда\nлуна\n')
    with open('words.txt', 'r', encoding='utf-8') as f:
        words_list = [line.strip().lower() for line in f if line.strip()]
    return words_list

words_list = load_words()

def save_words():
    with open('words.txt', 'w', encoding='utf-8') as f:
        for word in words_list:
            f.write(word + '\n')

def add_words_to_file(words):
    existing_words = set(words_list)
    new_words = set(word.lower() for word in words if word.lower() not in existing_words)
    if new_words:
        with open('words.txt', 'a', encoding='utf-8') as f:
            for word in new_words:
                f.write(word + '\n')
        words_list.extend(new_words)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton('🎲 Новое слово', callback_data='new_word')],
        [InlineKeyboardButton('📝 Ввести слово', callback_data='input_word')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать! Выберите действие:",
        reply_markup=reply_markup
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
            print(f"Не удалось удалить сообщение с благодарностью: {e}")
        context.user_data.pop('thank_you_message_id', None)

    if not words_list:
        await context.bot.send_message(chat_id=chat_id, text="Список слов пуст. Нет слов для отображения.")
        return ConversationHandler.END

    word = random.choice(words_list)
    context.user_data['chosen_word'] = word

    # Клавиатура с кнопками
    keyboard = [
        [
            InlineKeyboardButton('➡️ Следующее слово', callback_data='next_word'),
            InlineKeyboardButton('❌ Удалить слово', callback_data='delete_word')
        ],
        [
            InlineKeyboardButton('📝 Ввести слово', callback_data='input_word'),
            InlineKeyboardButton('👀 Показать рифмы', callback_data='show_current_rhymes')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        # Редактируем сообщение, заменяя его на новое слово и кнопки
        sent_message = await query.edit_message_text(
            f"Ваше слово: **{word}**\n\nВведите рифмы к этому слову, разделяя их запятыми.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        # Если функция вызвана не через CallbackQuery (например, при /start)
        sent_message = await context.bot.send_message(
            chat_id=chat_id,
            text=f"Ваше слово: **{word}**\n\nВведите рифмы к этому слову, разделяя их запятыми.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    # Сохраняем идентификатор сообщения
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
            print(f"Не удалось удалить сообщение с благодарностью: {e}")
        context.user_data.pop('thank_you_message_id', None)

    # Очищаем предыдущее состояние и данные пользователя
    context.user_data.pop('chosen_word', None)

    if not words_list:
        await query.edit_message_text("Список слов пуст. Нет слов для отображения.")
        return ConversationHandler.END

    # Генерируем новое слово и редактируем сообщение
    word = random.choice(words_list)
    context.user_data['chosen_word'] = word

    keyboard = [
        [
            InlineKeyboardButton('➡️ Следующее слово', callback_data='next_word'),
            InlineKeyboardButton('❌ Удалить слово', callback_data='delete_word')
        ],
        [
            InlineKeyboardButton('📝 Ввести слово', callback_data='input_word'),
            InlineKeyboardButton('👀 Показать рифмы', callback_data='show_current_rhymes')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    sent_message = await query.edit_message_text(
        f"Ваше слово: **{word}**\n\nВведите рифмы к этому слову, разделяя их запятыми.",
        parse_mode='Markdown',
        reply_markup=reply_markup
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
                print(f"Не удалось удалить сообщение с благодарностью: {e}")
            context.user_data.pop('thank_you_message_id', None)

        if not words_list:
            await query.edit_message_text("Слово удалено. Список слов пуст.")
            return ConversationHandler.END

        # Генерируем новое слово и редактируем сообщение
        new_word = random.choice(words_list)
        context.user_data['chosen_word'] = new_word

        keyboard = [
            [
                InlineKeyboardButton('➡️ Следующее слово', callback_data='next_word'),
                InlineKeyboardButton('❌ Удалить слово', callback_data='delete_word')
            ],
            [
                InlineKeyboardButton('📝 Ввести слово', callback_data='input_word'),
                InlineKeyboardButton('👀 Показать рифмы', callback_data='show_current_rhymes')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        sent_message = await query.edit_message_text(
            f"Слово **{word}** удалено.\n\nВаше новое слово: **{new_word}**\n\nВведите рифмы к этому слову, разделяя их запятыми.",
            parse_mode='Markdown',
            reply_markup=reply_markup
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
            print(f"Не удалось удалить сообщение: {e}")
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
        if new_word not in words_list:
            words_list.append(new_word)
            save_words()
            await update.message.reply_text(f"Слово **{new_word}** добавлено.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"Слово **{new_word}** уже есть в списке.", parse_mode='Markdown')

        # Переходим к вводу рифм для нового слова
        context.user_data['chosen_word'] = new_word

        # Клавиатура с кнопками
        keyboard = [
            [
                InlineKeyboardButton('➡️ Следующее слово', callback_data='next_word'),
                InlineKeyboardButton('❌ Удалить слово', callback_data='delete_word')
            ],
            [
                InlineKeyboardButton('📝 Ввести слово', callback_data='input_word'),
                InlineKeyboardButton('👀 Показать рифмы', callback_data='show_current_rhymes')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Отправляем сообщение с предложением ввести рифмы
        sent_message = await update.message.reply_text(
            f"Ваше слово: **{new_word}**\n\nВведите рифмы к этому слову, разделяя их запятыми.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        context.user_data['bot_message_id'] = sent_message.message_id

        return CHOOSING_RHYMES
    else:
        await update.message.reply_text("Пожалуйста, введите корректное слово.")
        return INPUTTING_WORD

async def receive_rhymes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    word = context.user_data.get('chosen_word')
    if word:
        rhymes = [r.strip().lower() for r in update.message.text.split(',')]
        conn = sqlite3.connect('rhymes.db')
        cursor = conn.cursor()
        # Сохраняем связь word ↔ rhyme
        for rhyme in rhymes:
            cursor.execute('INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)', (word.lower(), rhyme))
            cursor.execute('INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)', (rhyme, word.lower()))
        # Сохраняем связи между всеми рифмами
        for i in range(len(rhymes)):
            for j in range(len(rhymes)):
                if i != j:
                    cursor.execute('INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)', (rhymes[i], rhymes[j]))
        conn.commit()
        conn.close()

        # Удаляем предыдущее сообщение бота
        bot_message_id = context.user_data.get('bot_message_id')
        if bot_message_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=bot_message_id)
            except Exception as e:
                print(f"Не удалось удалить сообщение: {e}")
            context.user_data.pop('bot_message_id', None)

        # Отправляем сообщение с благодарностью и сохраняем его идентификатор
        thank_you_message = await update.message.reply_text(
            "✨ Спасибо! Ваши рифмы сохранены.\nВы можете выбрать дальнейшее действие."
        )
        context.user_data['thank_you_message_id'] = thank_you_message.message_id

        # Предлагаем дальнейшие действия
        keyboard = [
            [InlineKeyboardButton('🎲 Новое слово', callback_data='new_word')],
            [InlineKeyboardButton('📝 Ввести слово', callback_data='input_word')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Что дальше?", reply_markup=reply_markup)

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
    conn = sqlite3.connect('rhymes.db')
    cursor = conn.cursor()
    cursor.execute('SELECT rhyme FROM rhymes WHERE word = ?', (word,))
    rows = cursor.fetchall()
    conn.close()
    if rows:
        rhymes = ', '.join(sorted(set([row[0] for row in rows])))
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
        conn = sqlite3.connect('rhymes.db')
        cursor = conn.cursor()
        cursor.execute('SELECT rhyme FROM rhymes WHERE word = ?', (word,))
        rows = cursor.fetchall()
        conn.close()
        if rows:
            rhymes = ', '.join(sorted(set([row[0] for row in rows])))
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
        new_rhymes = [r.strip().lower() for r in update.message.text.split(',') if r.strip()]
        if new_rhymes:
            conn = sqlite3.connect('rhymes.db')
            cursor = conn.cursor()
            # Получаем старые рифмы для слова
            cursor.execute('SELECT rhyme FROM rhymes WHERE word = ?', (word,))
            old_rhymes = [row[0] for row in cursor.fetchall()]
            # Собираем все слова для обновления
            words_to_update = set([word] + old_rhymes)
            # Генерируем плейсхолдеры для запроса SQL
            placeholders = ','.join('?' for _ in words_to_update)
            params = list(words_to_update)
            # Удаляем все связи, где слова участвуют в колонках word или rhyme
            cursor.execute(f'DELETE FROM rhymes WHERE word IN ({placeholders}) OR rhyme IN ({placeholders})', params + params)
            # Добавляем новые рифмы
            for rhyme in new_rhymes:
                cursor.execute('INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)', (word, rhyme))
                cursor.execute('INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)', (rhyme, word))
            # Создаем связи между новыми рифмами
            for i in range(len(new_rhymes)):
                for j in range(len(new_rhymes)):
                    if i != j:
                        cursor.execute('INSERT OR IGNORE INTO rhymes (word, rhyme) VALUES (?, ?)', (new_rhymes[i], new_rhymes[j]))
            conn.commit()
            conn.close()
            await update.message.reply_text(f"Рифмы для слова **{word}** успешно обновлены.", parse_mode='Markdown')
            context.user_data.pop('edit_word', None)
            return ConversationHandler.END
        else:
            await update.message.reply_text("Пожалуйста, введите хотя бы одну рифму.")
            return EDITING_RHYMES
    else:
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton('🎲 Новое слово', callback_data='new_word')],
        [InlineKeyboardButton('📝 Ввести слово', callback_data='input_word')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    help_text = (
        "Доступные команды:\n"
        "/start - начать работу с ботом\n"
        "/help - показать это сообщение\n"
        "/r <слово> - показать рифмы к указанному слову\n"
    )
    await update.message.reply_text(help_text, reply_markup=reply_markup)

def main():
    init_db()

    application = ApplicationBuilder().token(get_api_token()).build()

    # Основной ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(new_word, pattern='^new_word$'),
            CallbackQueryHandler(input_word, pattern='^input_word$'),
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

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('r', show_rhymes))  # Обновлено
    application.add_handler(conv_handler)
    application.add_handler(edit_rhymes_conv_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))

    application.run_polling()

if __name__ == '__main__':
    main()
