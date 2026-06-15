"""Telegram bot front-end for mdconvert.

Send the bot any supported file (as a *document*) and it replies with the
converted ``.md``. It is a thin layer over the conversion engine — all the
real work happens in :func:`mdconvert.core.convert_bytes`.

Setup
-----
1. Create a bot and get its token from Telegram's ``@BotFather``.
2. Export the token::

       export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."

3. Install the bot dependency (and any format extras you need)::

       pip install "python-telegram-bot>=20"
       pip install -r mdconvert/requirements.txt    # optional: xlsx/pdf/docx/pptx

4. Run it from the ``python/`` directory::

       python -m mdconvert.bot

The module imports cleanly even when ``python-telegram-bot`` is absent; the
library is only required to actually *run* the bot (``main``).
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path

from .core import (
    ConversionError,
    ConvertOptions,
    convert_bytes,
    supported_extensions,
)

LOG = logging.getLogger("mdconvert.bot")

# Telegram's Bot API lets a bot download files up to 20 MB via getFile.
MAX_FILE_BYTES = 20 * 1024 * 1024
# Telegram caption hard limit.
MAX_CAPTION = 1024


def _supported_summary() -> str:
    return ", ".join(sorted(supported_extensions()))


WELCOME = (
    "👋 *mdconvert* — send me a file and I'll convert it to Markdown.\n\n"
    "Send it as a *file/document* (not a compressed photo) and I'll reply with a `.md`.\n\n"
    f"Supported: {_supported_summary()}\n\n"
    "Use /help for details."
)

HELP = (
    "Send me a document and I'll return the Markdown version.\n\n"
    "• Text/CSV/TSV/JSON/HTML work out of the box.\n"
    "• PDF, Excel (.xlsx), Word (.docx) and PowerPoint (.pptx) require the matching "
    "library to be installed on the server running me.\n"
    "• Tables (CSV/Excel) use the first row as a header.\n"
    "• Unknown file types are read as plain text.\n\n"
    f"Supported extensions: {_supported_summary()}"
)


# --------------------------------------------------------------------------- #
# Handlers (the `update`/`context` objects are python-telegram-bot runtime
# types, so these functions need no telegram import at definition time).
# --------------------------------------------------------------------------- #

async def cmd_start(update, context) -> None:
    await update.message.reply_text(WELCOME, parse_mode="Markdown")


async def cmd_help(update, context) -> None:
    await update.message.reply_text(HELP)


async def on_text(update, context) -> None:
    await update.message.reply_text(
        "Send me a file (as a document) and I'll convert it to Markdown. /help for more."
    )


async def on_document(update, context) -> None:
    message = update.message
    document = message.document
    if document is None:
        return

    name = document.file_name or f"file_{document.file_unique_id}"

    if document.file_size and document.file_size > MAX_FILE_BYTES:
        await message.reply_text(
            f"❌ “{name}” is larger than the 20 MB limit Telegram allows bots to download."
        )
        return

    status = await message.reply_text(f"⏳ Converting “{name}” …")
    try:
        tg_file = await context.bot.get_file(document.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: convert_bytes(name, data, ConvertOptions())
        )
    except ConversionError as exc:
        await status.edit_text(f"❌ {exc}")
        return
    except Exception as exc:  # network / telegram / unexpected
        LOG.exception("Failed to convert %s", name)
        await status.edit_text(f"❌ Could not convert “{name}”: {exc}")
        return

    out_name = Path(name).stem + ".md"
    payload = io.BytesIO(result.markdown.encode("utf-8"))
    payload.name = out_name

    caption = "✅ Converted to Markdown"
    if result.warnings:
        caption += "\n" + "\n".join("• " + w for w in result.warnings)
    caption = caption[:MAX_CAPTION]

    await message.reply_document(document=payload, filename=out_name, caption=caption)
    try:
        await status.delete()
    except Exception:  # deleting the status line is best-effort
        pass


def build_application(token: str):
    """Construct the python-telegram-bot Application with handlers wired up."""
    try:
        from telegram.ext import (
            Application,
            CommandHandler,
            MessageHandler,
            filters,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without the lib
        raise SystemExit(
            "The Telegram bot needs 'python-telegram-bot' — install it with:\n"
            '    pip install "python-telegram-bot>=20"'
        ) from exc

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print(
            "Set TELEGRAM_BOT_TOKEN before starting the bot.\n"
            "Get a token from @BotFather, then:\n"
            '    export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."',
            flush=True,
        )
        return 2

    app = build_application(token)
    LOG.info("mdconvert Telegram bot starting (long polling). Press Ctrl+C to stop.")
    app.run_polling()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
