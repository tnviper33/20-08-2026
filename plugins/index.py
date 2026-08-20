import logging
import re
import time
import asyncio
from math import ceil
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, ChannelInvalid, UsernameInvalid, UsernameNotModified
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.ia_filterdb import save_file
from utils import temp, get_readable_time

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

lock = asyncio.Lock()

# --- STEP 1: Ask before indexing ---
@Client.on_message(
    (filters.forwarded | filters.regex(r"(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[A-Za-z0-9_]+)/(\d+)"))
    & filters.private & filters.incoming
)
async def send_for_index(bot, message):
    regex = re.compile(r"(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[A-Za-z0-9_]+)/(\d+)")
    match = regex.match(message.text or "")
    if match:
        chat_id = match.group(3)
        last_msg_id = int(match.group(4))
        if chat_id.isnumeric():
            chat_id = int("-100" + chat_id)
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
        last_msg_id = message.forward_from_message_id
    else:
        return await message.reply("❌ Invalid link or unsupported forward.")

    # Build Accept/Reject buttons
    buttons = [
        [InlineKeyboardButton("✅ Start Indexing", callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}")],
        [InlineKeyboardButton("❌ Reject Request", callback_data=f"index#reject#{chat_id}#{message.id}#{message.from_user.id}")],
        [InlineKeyboardButton("🔍 Preview Channel", url=f"https://t.me/{chat_id}" if isinstance(chat_id, str) else None)]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    await message.reply(
        f"🚀 Ready to launch indexing mission?\n\n"
        f"📌 Channel: <code>{chat_id}</code>\n"
        f"📌 Last Message ID: <code>{last_msg_id}</code>",
        reply_markup=reply_markup
    )

# --- STEP 2: Handle Accept/Reject ---
@Client.on_callback_query(filters.regex(r"^index"))
async def index_files(bot, query):
    _, action, chat, lst_msg_id, from_user = query.data.split("#")
    if action == "reject":
        await query.message.delete()
        return await bot.send_message(int(from_user), f"❌ Your request to index {chat} was rejected.")
    if lock.locked():
        return await query.answer("⚠️ Another indexing process is running. Please wait.", show_alert=True)

    await query.answer("Processing…⏳", show_alert=True)
    await query.message.edit("📊 Starting Indexing...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="index_cancel")]]))

    try:
        chat = int(chat)
    except:
        pass
    await index_files_to_db(int(lst_msg_id), chat, query.message, bot)

# --- STEP 3: Indexing logic ---
def get_progress_bar(percent, length=10):
    filled = int(length * percent / 100)
    return "🟩" * filled + "⬜️" * (length - filled)

async def index_files_to_db(lst_msg_id, chat, msg, bot):
    total_files = duplicate = errors = deleted = no_media = unsupported = 0
    BATCH_SIZE = 50
    start_time = time.time()

    async with lock:
        try:
            current = temp.CURRENT
            temp.CANCEL = False
            total_messages = lst_msg_id
            total_fetch = lst_msg_id - current
            if total_messages <= 0:
                return await msg.edit("🚫 No Messages To Index.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close_data")]]))

            batches = ceil(total_messages / BATCH_SIZE)
            batch_times = []

            for batch in range(batches):
                if temp.CANCEL:
                    break
                start_id = current + 1
                end_id = min(current + BATCH_SIZE, lst_msg_id)
                message_ids = list(range(start_id, end_id + 1))

                try:
                    messages = await bot.get_messages(chat, message_ids)
                    if not isinstance(messages, list):
                        messages = [messages]
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    continue
                except Exception:
                    errors += len(message_ids)
                    current += len(message_ids)
                    continue

                save_tasks = []
                for message in messages:
                    current += 1
                    if message.empty:
                        deleted += 1
                        continue
                    if not message.media:
                        no_media += 1
                        continue
                    if message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT, enums.MessageMediaType.PHOTO]:
                        unsupported += 1
                        continue

                    media = getattr(message, message.media.value, None)
                    if not media:
                        unsupported += 1
                        continue

                    data = {"file_id": media.file_id, "file_type": message.media.value, "caption": message.caption}
                    save_tasks.append(save_file(data))

                results = await asyncio.gather(*save_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        errors += 1
                    else:
                        ok, code = result
                        if ok:
                            total_files += 1
                        elif code == 0:
                            duplicate += 1
                        elif code == 2:
                            errors += 1

                progress = current - temp.CURRENT
                percentage = (progress / total_fetch) * 100
                progress_bar = get_progress_bar(int(percentage))
                elapsed = time.time() - start_time

                await msg.edit(
                    f"📊 Indexing Progress: Batch {batch+1}/{batches}\n"
                    f"{progress_bar} <code>{percentage:.1f}%</code>\n\n"
                    f"📂 Files Saved: <code>{total_files}</code>\n"
                    f"🔁 Duplicates: <code>{duplicate}</code>\n"
                    f"🗑️ Deleted: <code>{deleted}</code>\n"
                    f"⚠️ Errors: <code>{errors}</code>\n"
                    f"⏱️ Elapsed: <code>{get_readable_time(elapsed)}</code>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="index_cancel")]])
                )

            await msg.edit(
                f"🎉 Indexing Mission Completed!\n\n"
                f"✅ Files Saved: <code>{total_files}</code>\n"
                f"🔁 Duplicates: <code>{duplicate}</code>\n"
                f"🗑️ Deleted: <code>{deleted}</code>\n"
                f"⚠️ Errors: <code>{errors}</code>\n"
                f"⏱️ Total Time: <code>{get_readable_time(time.time()-start_time)}</code>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Download Report", callback_data="download_report")],
                    [InlineKeyboardButton("🔄 Restart Indexing", callback_data="restart_index")],
                    [InlineKeyboardButton("❌ Close", callback_data="close_data")]
                ])
            )
        except Exception as e:
            await msg.edit(f"❌ Error: <code>{e}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close_data")]]))
