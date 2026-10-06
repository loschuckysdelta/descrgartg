from __future__ import annotations

import asyncio
import inspect
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from telethon import TelegramClient, errors, utils

from storage import (
    DATA_DIR,
    already_sent,
    mark_sent,
)

try:
    from telethon.tl.functions.channels import GetForumTopicsRequest
except Exception:
    from telethon.tl.functions.messages import GetForumTopicsRequest

try:
    from telethon.tl.functions.messages import CreateForumTopicRequest
except Exception:
    from telethon.tl.functions.channels import CreateForumTopicRequest


SESSION_PATH = str(
    DATA_DIR / "telegram_session"
)


def parse_group_id(value):
    text = str(
        value or ""
    ).strip()

    if not text:
        raise ValueError(
            "Falta el ID del grupo."
        )

    return int(text)


def make_client(
    api_id,
    api_hash
):
    return TelegramClient(
        SESSION_PATH,
        int(api_id),
        api_hash,
        auto_reconnect=True,
        connection_retries=5,
        retry_delay=3,
    )


def is_video(message):
    if getattr(
        message,
        "video",
        None
    ):
        return True

    document = getattr(
        message,
        "document",
        None
    )

    if document:
        mime = (
            getattr(
                document,
                "mime_type",
                ""
            )
            or ""
        )

        return mime.startswith(
            "video/"
        )

    return False


def first_hashtag(text):
    if not text:
        return None

    found = re.findall(
        r"(?<!\w)#([\w]+)",
        text,
        flags=re.UNICODE
    )

    return (
        found[0]
        if found
        else None
    )


def normalize(text):
    return unicodedata.normalize(
        "NFKC",
        text or ""
    ).strip().casefold()


def topic_title(hashtag):
    value = re.sub(
        r"\s+",
        " ",
        hashtag.replace(
            "_",
            " "
        ).strip()
    )

    return (
        value or "Sin nombre"
    )[:100]


def parse_message_link(link):
    text = (
        link or ""
    ).strip()

    if not text:
        return None

    try:
        parsed = urlparse(
            text
        )

        if parsed.netloc.lower() not in {
            "t.me",
            "telegram.me",
            "www.t.me",
            "www.telegram.me",
        }:
            return None

        parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        if (
            parts
            and parts[-1].isdigit()
        ):
            return int(
                parts[-1]
            )

    except Exception:
        pass

    return None


async def resolve_chat(
    client,
    chat_id
):
    try:
        return await client.get_entity(
            int(chat_id)
        )

    except Exception:
        pass

    async for dialog in client.iter_dialogs():
        try:
            if utils.get_peer_id(
                dialog.entity
            ) == int(chat_id):
                return dialog.entity

        except Exception:
            continue

    raise RuntimeError(
        f"No encontré el chat {chat_id}. "
        "Comprueba que esta cuenta tenga acceso al grupo."
    )


async def auth_status(
    api_id,
    api_hash
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        ok = await client.is_user_authorized()

        me = (
            await client.get_me()
            if ok
            else None
        )

        return ok, me

    finally:
        await client.disconnect()


async def send_login_code(
    api_id,
    api_hash,
    phone
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        if await client.is_user_authorized():
            return {
                "authorized": True,
                "phone_code_hash": None,
            }

        result = await client.send_code_request(
            phone
        )

        return {
            "authorized": False,
            "phone_code_hash": result.phone_code_hash,
        }

    finally:
        await client.disconnect()


async def confirm_login(
    api_id,
    api_hash,
    phone,
    code,
    phone_code_hash,
    password=""
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        if await client.is_user_authorized():
            return await client.get_me()

        try:
            await client.sign_in(
                phone=phone,
                code=code,
                phone_code_hash=phone_code_hash,
            )

        except errors.SessionPasswordNeededError:
            if not password:
                raise RuntimeError(
                    "Tu cuenta usa contraseña 2FA. "
                    "Escríbela y confirma otra vez."
                )

            await client.sign_in(
                password=password
            )

        return await client.get_me()

    finally:
        await client.disconnect()


def _get_topics_request(
    destination,
    offset_date=None,
    offset_id=0,
    offset_topic=0
):
    params = inspect.signature(
        GetForumTopicsRequest.__init__
    ).parameters

    kwargs = {}

    if "channel" in params:
        kwargs["channel"] = destination

    elif "peer" in params:
        kwargs["peer"] = destination

    else:
        raise RuntimeError(
            "No se pudo construir GetForumTopicsRequest."
        )

    if "offset_date" in params:
        kwargs["offset_date"] = offset_date

    if "offset_id" in params:
        kwargs["offset_id"] = offset_id

    if "offset_topic" in params:
        kwargs["offset_topic"] = offset_topic

    if "limit" in params:
        kwargs["limit"] = 100

    if "q" in params:
        kwargs["q"] = ""

    return GetForumTopicsRequest(
        **kwargs
    )


async def list_topics(
    client,
    destination
):
    topics = []
    seen = set()

    offset_date = None
    offset_id = 0
    offset_topic = 0

    for _ in range(50):
        result = await client(
            _get_topics_request(
                destination,
                offset_date,
                offset_id,
                offset_topic
            )
        )

        batch = list(
            getattr(
                result,
                "topics",
                []
            )
            or []
        )

        if not batch:
            break

        added = 0

        for item in batch:
            topic_id = int(
                getattr(
                    item,
                    "id"
                )
            )

            if topic_id not in seen:
                seen.add(
                    topic_id
                )

                topics.append(
                    item
                )

                added += 1

        total = int(
            getattr(
                result,
                "count",
                len(topics)
            )
            or len(topics)
        )

        if (
            len(topics) >= total
            or added == 0
        ):
            break

        last = batch[-1]

        offset_topic = int(
            getattr(
                last,
                "id",
                0
            )
            or 0
        )

        offset_id = int(
            getattr(
                last,
                "top_message",
                0
            )
            or 0
        )

        messages = (
            getattr(
                result,
                "messages",
                []
            )
            or []
        )

        dates = {
            int(
                getattr(
                    message,
                    "id",
                    0
                )
            ): getattr(
                message,
                "date",
                None
            )
            for message in messages
        }

        offset_date = dates.get(
            offset_id
        )

    return topics


def _create_topic_request(
    destination,
    title
):
    params = inspect.signature(
        CreateForumTopicRequest.__init__
    ).parameters

    kwargs = {
        "title": title
    }

    if "peer" in params:
        kwargs["peer"] = destination

    elif "channel" in params:
        kwargs["channel"] = destination

    else:
        raise RuntimeError(
            "No se pudo construir CreateForumTopicRequest."
        )

    return CreateForumTopicRequest(
        **kwargs
    )


async def get_or_create_topic(
    client,
    destination,
    title,
    create_topics
):
    wanted = normalize(
        title
    )

    for item in await list_topics(
        client,
        destination
    ):
        if normalize(
            getattr(
                item,
                "title",
                ""
            )
        ) == wanted:
            return int(
                getattr(
                    item,
                    "id"
                )
            )

    if not create_topics:
        raise RuntimeError(
            f"No existe el tema '{title}'. "
            "Créalo manualmente o activa creación automática."
        )

    await client(
        _create_topic_request(
            destination,
            title
        )
    )

    for _ in range(6):
        await asyncio.sleep(
            1
        )

        for item in await list_topics(
            client,
            destination
        ):
            if normalize(
                getattr(
                    item,
                    "title",
                    ""
                )
            ) == wanted:
                return int(
                    getattr(
                        item,
                        "id"
                    )
                )

    raise RuntimeError(
        f"El tema '{title}' se creó, "
        "pero no pude recuperar su ID."
    )


async def _flood_safe(
    factory,
    log=None
):
    while True:
        try:
            return await factory()

        except errors.FloodWaitError as exc:
            seconds = int(
                exc.seconds
            ) + 1

            if log:
                log(
                    f"Telegram pidió esperar "
                    f"{seconds} segundos."
                )

            await asyncio.sleep(
                seconds
            )


async def search_videos(
    api_id,
    api_hash,
    source_group,
    query,
    limit=5000,
    progress=None
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Primero inicia sesión en Telegram."
            )

        source = await resolve_chat(
            client,
            source_group
        )

        linked_id = parse_message_link(
            query
        )

        if linked_id:
            message = await client.get_messages(
                source,
                ids=linked_id
            )

            if (
                message
                and is_video(
                    message
                )
            ):
                return [
                    {
                        "message_id": int(
                            message.id
                        ),
                        "hashtag": (
                            first_hashtag(
                                message.raw_text or ""
                            )
                            or ""
                        ),
                        "date": (
                            message.date.isoformat(
                                sep=" ",
                                timespec="minutes"
                            )
                            if message.date
                            else ""
                        ),
                        "text": message.raw_text or "",
                    }
                ]

            return []

        needle = normalize(
            (query or "").lstrip("#")
        )

        by_hashtag = (
            query or ""
        ).strip().startswith("#")

        results = []
        checked = 0

        async for message in client.iter_messages(
            source,
            limit=int(limit)
        ):
            checked += 1

            if (
                progress
                and checked % 100 == 0
            ):
                progress(
                    checked
                )

            if not is_video(
                message
            ):
                continue

            text = (
                message.raw_text
                or ""
            )

            hashtag = first_hashtag(
                text
            )

            if not query.strip():
                match = True

            elif by_hashtag:
                match = bool(
                    hashtag
                    and normalize(
                        hashtag
                    ) == needle
                )

            else:
                match = (
                    needle
                    in normalize(
                        text
                    )
                )

            if match:
                results.append(
                    {
                        "message_id": int(
                            message.id
                        ),
                        "hashtag": hashtag or "",
                        "date": (
                            message.date.isoformat(
                                sep=" ",
                                timespec="minutes"
                            )
                            if message.date
                            else ""
                        ),
                        "text": text,
                    }
                )

        return results

    finally:
        await client.disconnect()


async def transfer_one(
    client,
    source,
    destination,
    source_group,
    destination_group,
    message,
    create_topics=True,
    keep_caption=True,
    log=None
):
    if not is_video(
        message
    ):
        return {
            "status": "skipped",
            "reason": "No es video",
        }

    hashtag = first_hashtag(
        message.raw_text or ""
    )

    if not hashtag:
        return {
            "status": "skipped",
            "reason": "No tiene hashtag",
        }

    if already_sent(
        source_group,
        int(message.id),
        destination_group
    ):
        return {
            "status": "duplicate",
            "reason": "Ya fue enviado",
        }

    title = topic_title(
        hashtag
    )

    topic_id = await get_or_create_topic(
        client,
        destination,
        title,
        create_topics
    )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="tvm_"
        )
    )

    local_file = None

    try:
        if log:
            log(
                f"Descargando mensaje "
                f"{message.id}..."
            )

        async def do_download():
            return await message.download_media(
                file=str(temp_dir)
            )

        local_file = await _flood_safe(
            do_download,
            log
        )

        if not local_file:
            raise RuntimeError(
                "No se pudo descargar el archivo."
            )

        caption = (
            message.raw_text or ""
            if keep_caption
            else ""
        )

        if log:
            log(
                f"Enviando al tema "
                f"'{title}'..."
            )

        async def do_send():
            return await client.send_file(
                destination,
                file=str(local_file),
                caption=caption,
                reply_to=topic_id,
                supports_streaming=True,
                force_document=False,
            )

        sent = await _flood_safe(
            do_send,
            log
        )

        sent_id = int(
            getattr(
                sent,
                "id",
                0
            )
            or 0
        )

        mark_sent(
            source_group,
            int(message.id),
            destination_group,
            sent_id or None,
            hashtag,
            title,
            topic_id,
        )

        return {
            "status": "sent",
            "message_id": int(
                message.id
            ),
            "hashtag": hashtag,
            "topic": title,
        }

    finally:
        try:
            if (
                local_file
                and Path(
                    local_file
                ).exists()
            ):
                Path(
                    local_file
                ).unlink()

        except Exception:
            pass

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )


async def send_selected(
    api_id,
    api_hash,
    source_group,
    destination_group,
    message_ids,
    create_topics=True,
    keep_caption=True,
    log=None,
    progress=None
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Primero inicia sesión en Telegram."
            )

        source = await resolve_chat(
            client,
            source_group
        )

        destination = await resolve_chat(
            client,
            destination_group
        )

        if not getattr(
            destination,
            "forum",
            False
        ):
            raise RuntimeError(
                "El grupo destino no tiene TEMAS activados."
            )

        output = []
        total = len(
            message_ids
        )

        for index, message_id in enumerate(
            message_ids,
            start=1
        ):
            message = await client.get_messages(
                source,
                ids=int(message_id)
            )

            if not message:
                output.append(
                    {
                        "status": "error",
                        "message_id": int(
                            message_id
                        ),
                        "reason": "Mensaje no encontrado",
                    }
                )

            else:
                try:
                    result = await transfer_one(
                        client,
                        source,
                        destination,
                        int(source_group),
                        int(destination_group),
                        message,
                        create_topics,
                        keep_caption,
                        log,
                    )

                    output.append(
                        result
                    )

                except Exception as exc:
                    output.append(
                        {
                            "status": "error",
                            "message_id": int(
                                message_id
                            ),
                            "reason": (
                                f"{type(exc).__name__}: "
                                f"{exc}"
                            ),
                        }
                    )

            if progress:
                progress(
                    index,
                    total
                )

        return output

    finally:
        await client.disconnect()


async def sync_all(
    api_id,
    api_hash,
    source_group,
    destination_group,
    create_topics=True,
    keep_caption=True,
    log=None,
    progress=None
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Primero inicia sesión en Telegram."
            )

        source = await resolve_chat(
            client,
            source_group
        )

        destination = await resolve_chat(
            client,
            destination_group
        )

        if not getattr(
            destination,
            "forum",
            False
        ):
            raise RuntimeError(
                "El grupo destino no tiene TEMAS activados."
            )

        checked = 0
        sent_count = 0
        skipped = 0
        errors_count = 0

        async for message in client.iter_messages(
            source,
            reverse=True
        ):
            checked += 1

            if (
                progress
                and checked % 25 == 0
            ):
                progress(
                    checked
                )

            if (
                not is_video(
                    message
                )
                or not first_hashtag(
                    message.raw_text or ""
                )
            ):
                continue

            try:
                result = await transfer_one(
                    client,
                    source,
                    destination,
                    int(source_group),
                    int(destination_group),
                    message,
                    create_topics,
                    keep_caption,
                    log,
                )

                if result["status"] == "sent":
                    sent_count += 1
                else:
                    skipped += 1

            except Exception as exc:
                errors_count += 1

                if log:
                    log(
                        f"Error mensaje "
                        f"{message.id}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

        return {
            "checked": checked,
            "sent": sent_count,
            "skipped": skipped,
            "errors": errors_count,
        }

    finally:
        await client.disconnect()


async def get_topics(
    api_id,
    api_hash,
    destination_group
):
    client = make_client(
        api_id,
        api_hash
    )

    await client.connect()

    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Primero inicia sesión."
            )

        destination = await resolve_chat(
            client,
            destination_group
        )

        if not getattr(
            destination,
            "forum",
            False
        ):
            raise RuntimeError(
                "El grupo destino no tiene TEMAS activados."
            )

        return [
            {
                "id": int(
                    getattr(
                        topic,
                        "id"
                    )
                ),
                "title": getattr(
                    topic,
                    "title",
                    ""
                ),
            }
            for topic in await list_topics(
                client,
                destination
            )
        ]

    finally:
        await client.disconnect()
