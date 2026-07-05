"""Run the Telegram shelter bot via long polling.

Runs as a Django management command so the ORM is available inside handlers
(`python manage.py runbot`). Uses the telebot / pyTelegramBotAPI library.
"""

import telebot
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from shelter_finder import (
    find_closest_shelter_by_coords,
    geocode_details,
    reverse_geocode,
)
from civil_defense import (
    lookup_civil_defense,
    format_body,
    find_district_body,
    format_district_body,
    is_district_city,
)


def send_result(bot, chat_id, result):
    status = (
        "\u2705 Подтверждённое убежище"
        if result.get("confirmed")
        else "\u26a0\ufe0f Не подтверждено (данные не проверены)"
    )
    text = (
        "Ближайшее убежище:\n"
        f"{result['okrug']} / {result['district']}\n"
        f"{result['address']}\n"
        f"~{result['distance_m'] / 1000:.1f} км, ~{result['duration_s'] / 60:.0f} мин пешком\n"
        f"{status}"
    )
    comment = (result.get("comment") or "").strip()
    if comment:
        text += f"\n\n{comment}"
    bot.send_message(chat_id, text)
    bot.send_location(chat_id, result["lat"], result["lon"])


def send_civil_defense(bot, chat_id, city, region, district_candidates=None):
    """Send the responsible civil-defense body.

    For Moscow/SPB only the district-level body is sent (no city/region info);
    for everywhere else the region/city body is sent.
    """
    if is_district_city(city):
        district_row = find_district_body(city, district_candidates)
        if district_row is not None:
            bot.send_message(chat_id, format_district_body(district_row))
        return

    result = lookup_civil_defense(city, region)
    if result is not None:
        bot.send_message(chat_id, format_body(result))


def build_bot(token):
    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=["start"])
    def start(message):
        bot.send_message(
            message.chat.id,
            "Здравствуйте! Отправьте мне свою геолокацию или напишите свой адрес "
            "текстом, и я найду ближайшее бомбоубежище и ответственный орган ГО и ЧС.",
        )

    @bot.message_handler(content_types=["location"])
    def handle_location(message):
        lat = message.location.latitude
        lon = message.location.longitude

        result = find_closest_shelter_by_coords(lat, lon)
        if result is None:
            bot.send_message(
                message.chat.id,
                "Извините, не удалось найти ни одного убежища с известными координатами.",
            )
        else:
            send_result(bot, message.chat.id, result)

        city, region, districts = reverse_geocode(lat, lon)
        send_civil_defense(bot, message.chat.id, city, region, districts)

    @bot.message_handler(content_types=["text"])
    def handle_address(message):
        details = geocode_details(message.text.strip())

        if details is None:
            bot.send_message(
                message.chat.id,
                "Извините, не удалось распознать этот адрес. Попробуйте уточнить "
                "адрес или отправьте геолокацию.",
            )
            return

        lat, lon, city, region, districts = details

        result = find_closest_shelter_by_coords(lat, lon)
        if result is None:
            bot.send_message(
                message.chat.id, "Извините, не удалось найти ближайшее убежище."
            )
        else:
            send_result(bot, message.chat.id, result)

        send_civil_defense(bot, message.chat.id, city, region, districts)

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
