"""Run the Telegram shelter bot via long polling.

Runs as a Django management command so the ORM is available inside handlers
(`python manage.py runbot`). Uses the telebot / pyTelegramBotAPI library.
"""

import telebot
from telebot import types
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from shelter_finder import (
    find_closest_shelter_by_coords,
    geocode_details,
    reverse_geocode,
)
from civil_defense import format_body_text, location_instructions

# Only shelters reachable within this walking time are offered to the user.
WALK_LIMIT_S = 15 * 60

# All feedback replies are forwarded to this Telegram user.
FEEDBACK_ADMIN_ID = 5458701780
FEEDBACK_CALLBACK = "feedback"
FEEDBACK_BUTTON_TEXT = "Обратная Связь"

WELCOME_TEXT = (
    "Привет! Этот бот поможет найти бомбоубежище рядом с вами. "
    "Чтобы получить информацию, пришлите геопозицию или адрес."
)

DISCLAIMER_TEXT = (
    "Адрес найден кем-то из ваших соседей, получен от госоргана или с помощью ИИ. "
    "Информация может быть неточной или устареть, проверьте укрытие сами заранее."
)

ADDRESS_NOT_RECOGNIZED_TEXT = (
    "Извините, не удалось распознать этот адрес. "
    "Попробуйте уточнить адрес или отправьте геолокацию."
)

FEEDBACK_PROMPT_TEXT = (
    "Пожалуйста, расскажите нам если:\n"
    "- Вы проверили одно из укрытий: укажите его адрес и расскажите, "
    "есть ли к нему доступ и какие там условия\n"
    "- Если вы связались с ГОЧС и узнали об укрытиях в вашем районе "
    "или получили дополнительные инструкции"
)

FEEDBACK_THANKS_TEXT = "Спасибо! Ваше сообщение передано."

CHANNEL_TEXT = "Больше информации в канале @bombshelterswatch_group"

# Content types accepted as a feedback reply (so photos, docs, etc. forward too).
FEEDBACK_REPLY_CONTENT_TYPES = [
    "text", "photo", "document", "video", "voice", "audio",
    "location", "contact", "sticker", "video_note",
]


def feedback_markup():
    """Inline keyboard with a single 'Обратная Связь' button."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(FEEDBACK_BUTTON_TEXT, callback_data=FEEDBACK_CALLBACK))
    return markup


def _is_feedback_reply(message):
    """True if the message is a reply to the feedback prompt."""
    replied = message.reply_to_message
    return bool(
        replied
        and replied.text
        and replied.text.startswith("Пожалуйста, расскажите нам если:")
    )


def send_shelter_found(bot, chat_id, result, instructions):
    """Send the nearest-shelter message (shelter within the walk limit)."""
    status = (
        "\u2705 Подтверждённое убежище"
        if result.get("confirmed")
        else "\u26a0\ufe0f Не подтверждено (данные не проверены)"
    )
    lines = [
        "Ближайшее к вам укрытие:",
        f"{result['okrug']} / {result['district']}",
        result["address"],
        f"~{result['distance_m'] / 1000:.1f} км, ~{result['duration_s'] / 60:.0f} мин пешком",
        status,
    ]
    comment = (result.get("comment") or "").strip()
    if comment:
        lines.append(comment)
    if instructions:
        lines.append("")
        lines.append(instructions)
    lines.append("")
    lines.append(DISCLAIMER_TEXT)
    lines.append("")
    lines.append(CHANNEL_TEXT)

    bot.send_message(chat_id, "\n".join(lines), reply_markup=feedback_markup())
    bot.send_location(chat_id, result["lat"], result["lon"])


def send_no_shelter(bot, chat_id, city, region, districts):
    """Send the fallback message when no shelter is within walking distance."""
    lines = [
        "В пешей доступности от вас не найдено ни одного укрытия.",
        "",
        "Что можно предпринять:",
    ]
    cd_text = format_body_text(city, region, districts)
    if cd_text:
        lines.append("- Обратитесь в районный отдел ГОЧС за более подробной информацией:")
        lines.append(cd_text)
    else:
        lines.append("- Позвоните по единому номеру экстренных служб 112.")
    lines.append("")
    lines.append(CHANNEL_TEXT)
    bot.send_message(chat_id, "\n".join(lines), reply_markup=feedback_markup())


def respond(bot, chat_id, lat, lon, city, region, districts):
    """Shared response flow for both location pins and typed addresses."""
    result = find_closest_shelter_by_coords(lat, lon)
    if result is not None and result["duration_s"] <= WALK_LIMIT_S:
        instructions = location_instructions(city, region, districts)
        send_shelter_found(bot, chat_id, result, instructions)
    else:
        send_no_shelter(bot, chat_id, city, region, districts)


def build_bot(token):
    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=["start"])
    def start(message):
        bot.send_message(message.chat.id, WELCOME_TEXT)

    @bot.callback_query_handler(func=lambda c: c.data == FEEDBACK_CALLBACK)
    def on_feedback(call):
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            FEEDBACK_PROMPT_TEXT,
            reply_markup=types.ForceReply(selective=False),
        )

    # Registered before the generic handlers so feedback replies take priority.
    @bot.message_handler(
        func=_is_feedback_reply, content_types=FEEDBACK_REPLY_CONTENT_TYPES
    )
    def handle_feedback_reply(message):
        bot.forward_message(FEEDBACK_ADMIN_ID, message.chat.id, message.message_id)
        bot.send_message(message.chat.id, FEEDBACK_THANKS_TEXT)

    @bot.message_handler(content_types=["location"])
    def handle_location(message):
        lat = message.location.latitude
        lon = message.location.longitude
        city, region, districts = reverse_geocode(lat, lon)
        respond(bot, message.chat.id, lat, lon, city, region, districts)

    @bot.message_handler(content_types=["text"])
    def handle_address(message):
        details = geocode_details(message.text.strip())
        if details is None:
            bot.send_message(message.chat.id, ADDRESS_NOT_RECOGNIZED_TEXT)
            return

        lat, lon, city, region, districts = details
        respond(bot, message.chat.id, lat, lon, city, region, districts)

    return bot


class Command(BaseCommand):
    help = "Run the Telegram shelter bot (long polling)."

    def handle(self, *args, **options):
        token = settings.BOT_TOKEN
        if not token:
            raise CommandError("BOT_TOKEN environment variable is not set")

        bot = build_bot(token)
        self.stdout.write(self.style.SUCCESS("Bot started. Polling..."))
        bot.polling(none_stop=True, timeout=60)
