import logging
import re
import time
import asyncio
from math import ceil
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, ChannelInvalid, ChatAdminRequired, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from info import ADMINS
from database.ia_filterdb import save_file
from utils import temp, get_readable_time

@Client.on_message(
    (filters.forwarded | filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$"))
    & filters.text & filters.private & filters.incoming
)
async def send_for_index(bot, message):
    regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
    match = regex.match(message.text or "")
    if match:
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int("-100" + chat_id)
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        last_msg_id = message.forward_from_message_id
    else:
        return await message.reply("Invalid link or unsupported forward.")

    # Build Accept/Reject buttons
    buttons = [
        [InlineKeyboardButton("Accept Index", callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}")],
        [InlineKeyboardButton("Reject Index", callback_data=f"index#reject#{chat_id}#{message.id}#{message.from_user.id}")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    # Always ask directly
    await message.reply(
        f"Do you want to index this channel/group?\n\n"
        f"Chat ID: <code>{chat_id}</code>\n"
        f"Last Message ID: <code>{last_msg_id}</code>",
        reply_markup=reply_markup
    )
