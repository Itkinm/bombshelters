import os

import telebot
from telebot import types
from dotenv import load_dotenv

from shelter_finder import find_closest_shelter, find_closest_shelter_by_coords

load_dotenv()

token = os.environ.get('BOT_TOKEN')
if not token:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

bot = telebot.TeleBot(token)


def send_result(chat_id, result):
    text = (
        "Ближайшее убежище:\n"
        f"{result['okrug']} / {result['district']}\n"
        f"{result['address']}\n"
        f"~{result['distance_m'] / 1000:.1f} км, ~{result['duration_s'] / 60:.0f} мин пешком"
    )
    bot.send_message(chat_id, text)
    bot.send_location(chat_id, result['lat'], result['lon'])


@bot.message_handler(commands=['start'])
def start(message):   
    bot.send_message(message.chat.id, "Здравствуйте! Отправьте мне свою геолокацию или напишите свой адрес текстом, и я найду ближайшее бомбоубежище.")


@bot.message_handler(content_types=['location'])
def handle_location(message):
    lat = message.location.latitude
    lon = message.location.longitude

    result = find_closest_shelter_by_coords(lat, lon)

    if result is None:
        bot.send_message(message.chat.id, "Извините, не удалось найти ни одного убежища с известными координатами.")
        return

    send_result(message.chat.id, result)


@bot.message_handler(content_types=['text'])
def handle_address(message):
    address = message.text.strip()
    if not address.lower().startswith("москва"):
        address = "Москва, " + address

    result = find_closest_shelter(address)

    if result is None:
        bot.send_message(message.chat.id, "Извините, не удалось распознать этот адрес или найти ближайшее убежище. Попробуйте уточнить адрес или отправьте геолокацию.")
        return

    send_result(message.chat.id, result)



if __name__ == '__main__':
    bot.polling(none_stop=True, timeout=60)
