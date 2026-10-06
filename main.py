from __future__ import annotations

import asyncio
import getpass
import json
import mimetypes
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

from telethon import TelegramClient, errors, functions, utils

try:
    import keyring
except Exception:
    keyring = None


APP_NAME = "TelegramVideoManager"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = DATA_DIR / "config.json"
SENT_PATH = DATA_DIR / "enviados.json"
SESSION_PATH = str(DATA_DIR / "telegram_session")
TEMP_DIR = BASE_DIR / "temp"

DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "api_id": "",
    "phone": "",
    "source_group": "",
    "destination_group": "",
    "create_topics": True,
    "keep_caption": True,
    "skip_already_sent": True,
    "destination_confirmed": False,
}


# ============================================================
# CONFIGURACION
# ============================================================

def load_config() -> dict:
    data = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update(saved)
        except Exception:
            pass
    return data


def save_config(data: dict) -> None:
    current = load_config()
    current.update(data)
    CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _api_hash_key(api_id: str | int) -> str:
    return f"api_hash:{str(api_id).strip()}"


def load_api_hash(api_id: str | int = "") -> str:
    """Carga el API Hash asociado al API ID actual.

    Se evita reutilizar un hash viejo de otro API ID, que provoca
    ApiIdInvalidError al iniciar sesion.
    """
    env_value = os.getenv("TELEGRAM_API_HASH", "").strip()
    if env_value:
        return env_value

    api_id = str(api_id or "").strip()
    if not api_id or keyring is None:
        return ""

    try:
        return (keyring.get_password(APP_NAME, _api_hash_key(api_id)) or "").strip()
    except Exception:
        return ""


def save_api_hash(api_id: str | int, value: str) -> None:
    api_id = str(api_id or "").strip()
    value = (value or "").strip()
    if not api_id or not value:
        return

    if keyring is not None:
        try:
            keyring.set_password(APP_NAME, _api_hash_key(api_id), value)
            # Borra la clave generica usada por versiones anteriores para no
            # mezclar un API ID con un API Hash de otra aplicacion.
            try:
                keyring.delete_password(APP_NAME, "api_hash")
            except Exception:
                pass
            return
        except Exception:
            pass

    print("[AVISO] No pude guardar el API Hash en Credenciales de Windows.")
    print("        Puedes usar la variable TELEGRAM_API_HASH.")


def clear_api_hash(api_id: str | int) -> None:
    api_id = str(api_id or "").strip()
    if keyring is None or not api_id:
        return
    try:
        keyring.delete_password(APP_NAME, _api_hash_key(api_id))
    except Exception:
        pass


def _validate_api_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise RuntimeError("Falta el API ID.")
    if not value.isdigit():
        raise RuntimeError("El API ID debe contener solamente numeros.")
    if int(value) <= 0:
        raise RuntimeError("El API ID no es valido.")
    return value


def _validate_api_hash(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise RuntimeError("Falta el API Hash.")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", value):
        raise RuntimeError(
            "El API Hash debe tener 32 caracteres hexadecimales. "
            "Copia exactamente el API Hash de my.telegram.org."
        )
    return value


def configure() -> dict:
    cfg = load_config()

    print("\n=== CONFIGURACION DE TELEGRAM ===")
    print("Usa el API ID y API Hash de LA MISMA aplicacion de my.telegram.org.")
    print("ENTER conserva el valor actual cuando ya hay uno correcto.\n")

    old_api_id = str(cfg.get("api_id", "") or "").strip()
    api_id_input = input(f"API ID [{old_api_id or 'vacio'}]: ").strip()
    api_id = _validate_api_id(api_id_input or old_api_id)

    # El hash se busca por API ID. Si cambias el ID, nunca se reutiliza el
    # hash guardado de otra aplicacion.
    current_hash = load_api_hash(api_id)
    api_hash_input = getpass.getpass(
        f"API Hash [{'guardado para este API ID' if current_hash else 'vacio'}]: "
    ).strip()
    api_hash = _validate_api_hash(api_hash_input or current_hash)

    old_phone = str(cfg.get("phone", "") or "")
    phone = input(f"Telefono [{old_phone or 'vacio'}]: ").strip() or old_phone

    old_source = str(cfg.get("source_group", "") or "")
    source = input(
        f"Grupo ORIGEN ID/@usuario/link [{old_source or 'vacio'}]: "
    ).strip() or old_source

    destination_confirmed = bool(cfg.get("destination_confirmed", False))
    old_destination = (
        str(cfg.get("destination_group", "") or "") if destination_confirmed else ""
    )
    destination = input(
        f"Grupo DESTINO ID/@usuario/link [{old_destination or 'vacio'}]: "
    ).strip() or old_destination

    if not phone:
        raise RuntimeError("Falta el telefono de Telegram.")

    save_config({
        "api_id": api_id,
        "phone": phone,
        "source_group": source,
        "destination_group": destination,
        "destination_confirmed": bool(destination),
    })
    save_api_hash(api_id, api_hash)

    print("\n[OK] Configuracion guardada.")
    return load_config()


def credentials() -> tuple[int, str, str]:
    cfg = load_config()
    api_id = str(cfg.get("api_id", "") or "").strip()
    phone = str(cfg.get("phone", "") or "").strip()
    api_hash = load_api_hash(api_id)

    if not api_id or not api_hash or not phone:
        cfg = configure()
        api_id = str(cfg.get("api_id", "") or "").strip()
        phone = str(cfg.get("phone", "") or "").strip()
        api_hash = load_api_hash(api_id)

    api_id = _validate_api_id(api_id)
    api_hash = _validate_api_hash(api_hash)
    return int(api_id), api_hash, phone


# ============================================================
# REGISTRO DE VIDEOS YA ENVIADOS
# ============================================================

def load_sent() -> set[str]:
    if not SENT_PATH.exists():
        return set()
    try:
        data = json.loads(SENT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data}
    except Exception:
        pass
    return set()


def save_sent(sent: set[str]) -> None:
    SENT_PATH.write_text(
        json.dumps(sorted(sent), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ============================================================
# TELEGRAM / ENLACES
# ============================================================

def parse_telegram_link(value: str):
    """Devuelve (chat_ref, message_id) para enlaces t.me cuando es posible."""
    text = (value or "").strip()
    if not text or not re.match(r"^https?://", text, flags=re.I):
        return None

    try:
        parsed = urlparse(text)
        if parsed.netloc.lower() not in {
            "t.me", "www.t.me", "telegram.me", "www.telegram.me"
        }:
            return None

        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            return None

        # Privado/supergrupo:
        # https://t.me/c/3929455385/12138
        # Con tema:
        # https://t.me/c/3929455385/123/12138
        if parts[0].lower() == "c" and len(parts) >= 3 and parts[1].isdigit():
            chat_ref = int("-100" + parts[1])
            numeric = [int(p) for p in parts[2:] if p.isdigit()]
            message_id = numeric[-1] if numeric else None
            return chat_ref, message_id

        # Publico: https://t.me/usuario/123
        username = parts[0]
        numeric = [int(p) for p in parts[1:] if p.isdigit()]
        message_id = numeric[-1] if numeric else None
        return username, message_id

    except Exception:
        return None


def normalize_chat_ref(value):
    if isinstance(value, int):
        return value

    text = str(value or "").strip()
    if not text:
        raise ValueError("Falta el grupo/canal.")

    parsed = parse_telegram_link(text)
    if parsed:
        return parsed[0]

    if re.fullmatch(r"-?\d+", text):
        return int(text)

    if text.startswith("@"):
        return text[1:]

    return text


async def resolve_chat(client: TelegramClient, value):
    ref = normalize_chat_ref(value)

    try:
        return await client.get_entity(ref)
    except Exception:
        pass

    if isinstance(ref, int):
        async for dialog in client.iter_dialogs():
            try:
                if utils.get_peer_id(dialog.entity) == ref:
                    return dialog.entity
            except Exception:
                continue

    raise RuntimeError(
        f"No pude abrir el chat '{value}'. Verifica que tu cuenta tenga acceso."
    )


def is_video(message) -> bool:
    if getattr(message, "video", None):
        return True

    document = getattr(message, "document", None)
    if document:
        mime = (getattr(document, "mime_type", "") or "").lower()
        return mime.startswith("video/")

    return False


def hashtags(text: str) -> list[str]:
    if not text:
        return []
    return re.findall(r"(?<!\w)#([\w]+)", text, flags=re.UNICODE)


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip().casefold()


def safe_topic_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").strip()
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        value = "SIN HASHTAG"
    return value[:128]


def chat_name(chat) -> str:
    return str(
        getattr(chat, "title", None)
        or getattr(chat, "username", None)
        or getattr(chat, "id", "chat")
    )


async def ensure_login(client: TelegramClient, phone: str) -> None:
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        who = getattr(me, "username", None) or getattr(me, "first_name", "Cuenta")
        print(f"[OK] Sesion iniciada como: {who}")
        return

    print("\nNo hay una sesion de Telegram iniciada.")
    try:
        sent = await client.send_code_request(phone)
    except errors.ApiIdInvalidError as exc:
        # No es un problema del numero ni del grupo: Telegram rechazo las
        # credenciales de la aplicacion.
        raise RuntimeError(
            "API ID / API Hash invalidos o no pertenecen a la misma aplicacion. "
            "Ejecuta 'py main.py', entra a Configuracion y vuelve a copiar "
            "ambos datos de la misma aplicacion creada en my.telegram.org. "
            "No uses el token de un bot como API Hash."
        ) from exc

    code = input("Codigo que llego a Telegram: ").strip()

    try:
        await client.sign_in(
            phone=phone,
            code=code,
            phone_code_hash=sent.phone_code_hash,
        )
    except errors.SessionPasswordNeededError:
        password = getpass.getpass("Contrasena 2FA: ")
        await client.sign_in(password=password)

    me = await client.get_me()
    who = getattr(me, "username", None) or getattr(me, "first_name", "Cuenta")
    print(f"[OK] Sesion guardada como: {who}")


# ============================================================
# TEMAS DEL GRUPO DESTINO
# ============================================================

class TopicManager:
    def __init__(self, client: TelegramClient, destination, create_topics: bool = True):
        self.client = client
        self.destination = destination
        self.create_topics = create_topics
        self.cache: dict[str, int] = {}

    def _get_request_class(self, name: str):
        """
        Telegram movio las funciones de foros desde channels.* a messages.*
        en capas recientes. Soportamos ambas ubicaciones para que funcione
        con versiones nuevas y antiguas de Telethon.
        """
        messages_ns = getattr(functions, "messages", None)
        channels_ns = getattr(functions, "channels", None)

        if messages_ns is not None and hasattr(messages_ns, name):
            return getattr(messages_ns, name), "messages"

        if channels_ns is not None and hasattr(channels_ns, name):
            return getattr(channels_ns, name), "channels"

        raise RuntimeError(
            f"Tu version de Telethon no incluye {name}. "
            "Ejecuta: py -m pip install -U \"Telethon>=1.44,<2\""
        )

    async def _get_topics(self, title: str):
        request_cls, namespace = self._get_request_class("GetForumTopicsRequest")

        common = dict(
            q=title,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
        )

        # API nueva: messages.getForumTopics(peer=...)
        if namespace == "messages":
            request = request_cls(peer=self.destination, **common)
        # API antigua: channels.getForumTopics(channel=...)
        else:
            request = request_cls(channel=self.destination, **common)

        return await self.client(request)

    async def _create_topic(self, title: str):
        request_cls, namespace = self._get_request_class("CreateForumTopicRequest")

        # API nueva: messages.createForumTopic(peer=...)
        if namespace == "messages":
            request = request_cls(
                peer=self.destination,
                title=title,
            )
        # API antigua: channels.createForumTopic(channel=...)
        else:
            request = request_cls(
                channel=self.destination,
                title=title,
            )

        return await self.client(request)

    async def _find_topic(self, title: str) -> int | None:
        key = normalize_text(title)
        if key in self.cache:
            return self.cache[key]

        try:
            result = await self._get_topics(title)
        except errors.FloodWaitError as exc:
            seconds = int(exc.seconds) + 1
            print(f"[TELEGRAM] Limite temporal. Esperando {seconds}s...")
            await asyncio.sleep(seconds)
            result = await self._get_topics(title)
        except Exception as exc:
            raise RuntimeError(
                "No pude leer los temas del grupo destino. "
                "Verifica que el grupo DESTINO tenga TEMAS activados y que tu cuenta tenga acceso. "
                f"Detalle: {type(exc).__name__}: {exc}"
            ) from exc

        for topic in getattr(result, "topics", []) or []:
            topic_title = str(getattr(topic, "title", "") or "")
            if normalize_text(topic_title) == key:
                # El ID real del tema es topic.id. En algunas versiones antiguas
                # top_message coincide con el mensaje raiz, pero topic.id es lo correcto.
                topic_id = getattr(topic, "id", None)
                if topic_id is None:
                    topic_id = getattr(topic, "top_message", None)
                if topic_id is None:
                    continue
                topic_id = int(topic_id)
                self.cache[key] = topic_id
                return topic_id

        return None

    async def get_or_create(self, raw_title: str) -> int:
        title = safe_topic_title(raw_title)

        existing = await self._find_topic(title)
        if existing is not None:
            return existing

        if not self.create_topics:
            raise RuntimeError(
                f"No existe el tema '{title}' y create_topics esta desactivado."
            )

        print(f"[TEMA] Creando: {title}")
        try:
            await self._create_topic(title)
        except errors.FloodWaitError as exc:
            seconds = int(exc.seconds) + 1
            print(f"[TELEGRAM] Esperando {seconds}s para crear el tema...")
            await asyncio.sleep(seconds)
            await self._create_topic(title)
        except Exception as exc:
            raise RuntimeError(
                f"No pude crear el tema '{title}'. "
                "La cuenta debe tener permiso para administrar/crear temas en el grupo destino. "
                f"Detalle: {type(exc).__name__}: {exc}"
            ) from exc

        # Telegram puede tardar un instante en mostrar el tema recien creado.
        for _ in range(10):
            await asyncio.sleep(0.5)
            found = await self._find_topic(title)
            if found is not None:
                return found

        raise RuntimeError(
            f"Se intento crear el tema '{title}', pero no pude localizarlo despues."
        )


# ============================================================
# DESCARGA TEMPORAL -> ENVIO AL TEMA -> BORRADO LOCAL
# ============================================================

def topics_for_message(message) -> list[str]:
    """Devuelve todos los #hashtags unicos del mensaje, conservando el orden."""
    result: list[str] = []
    seen: set[str] = set()
    for tag in hashtags(message.raw_text or ""):
        title = safe_topic_title(tag)
        key = normalize_text(title)
        if key and key not in seen:
            seen.add(key)
            result.append(title)
    return result


def caption_for_message(message, topic: str, keep_caption: bool) -> str:
    original = (message.raw_text or "").strip()
    if keep_caption and original:
        return original[:1024]
    return f"#{topic}"[:1024]


def _safe_extension(message) -> str:
    """Obtiene una extension razonable sin confiar en nombres de archivo externos."""
    file_obj = getattr(message, "file", None)
    ext = str(getattr(file_obj, "ext", "") or "").strip().lower()
    if ext and re.fullmatch(r"\.[a-z0-9]{1,8}", ext):
        return ext

    document = getattr(message, "document", None)
    mime = str(getattr(document, "mime_type", "") or "").lower()
    guessed = mimetypes.guess_extension(mime) if mime else None
    if guessed and re.fullmatch(r"\.[a-z0-9]{1,8}", guessed):
        return guessed
    return ".mp4"


def cleanup_temp_dir() -> None:
    """Borra cualquier archivo temporal que haya quedado de una ejecucion anterior."""
    if not TEMP_DIR.exists():
        return
    try:
        shutil.rmtree(TEMP_DIR)
    except Exception:
        # Si Windows mantiene algun archivo ocupado, se vuelve a intentar por archivo.
        for item in TEMP_DIR.glob("*"):
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink(missing_ok=True)
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass
        try:
            TEMP_DIR.rmdir()
        except Exception:
            pass


async def download_video_temporarily(
    client: TelegramClient,
    source_peer_id: int,
    message,
) -> Path:
    """Descarga un video a /temp para volver a subirlo al destino."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    ext = _safe_extension(message)
    temp_path = TEMP_DIR / f"{abs(int(source_peer_id))}_{int(message.id)}{ext}"

    # Si quedo un archivo de una ejecucion interrumpida, no lo reutilizamos.
    try:
        temp_path.unlink(missing_ok=True)
    except Exception:
        pass

    print(f"[DESCARGANDO TEMP] mensaje {message.id}...")

    last_percent = -1
    def progress(current: int, total: int) -> None:
        nonlocal last_percent
        if not total:
            return
        percent = int(current * 100 / total)
        # Evita llenar la consola: muestra 0,10,20...100.
        bucket = min(100, (percent // 10) * 10)
        if bucket != last_percent:
            last_percent = bucket
            print(f"  descarga: {bucket}%")

    downloaded = await client.download_media(
        message,
        file=str(temp_path),
        progress_callback=progress,
    )

    if not downloaded:
        raise RuntimeError(f"Telegram no pudo descargar el video del mensaje {message.id}.")

    real_path = Path(downloaded)
    if not real_path.exists() or real_path.stat().st_size <= 0:
        raise RuntimeError(f"El video temporal del mensaje {message.id} quedo vacio.")

    print(f"[OK DESCARGA] {real_path.name} ({real_path.stat().st_size / (1024*1024):.1f} MB)")
    return real_path


async def send_temp_video_to_topic(
    client: TelegramClient,
    destination,
    local_path: Path,
    message,
    topic: str,
    topic_manager: TopicManager,
    *,
    keep_caption: bool,
) -> None:
    """Crea/reutiliza el tema y sube el archivo temporal dentro de el."""
    topic_id = await topic_manager.get_or_create(topic)
    caption = caption_for_message(message, topic, keep_caption)

    print(f"[SUBIENDO] mensaje {message.id} -> tema: {topic}")

    async def do_send():
        return await client.send_file(
            destination,
            file=str(local_path),
            caption=caption,
            reply_to=topic_id,
            supports_streaming=True,
            force_document=False,
        )

    try:
        await do_send()
    except errors.FloodWaitError as exc:
        seconds = int(exc.seconds) + 1
        print(f"[TELEGRAM] Limite temporal. Esperando {seconds}s...")
        await asyncio.sleep(seconds)
        await do_send()

    print(f"[OK ENVIADO] mensaje {message.id} -> {topic}")


async def process_video_message(
    client: TelegramClient,
    source,
    destination,
    message,
    topic_manager: TopicManager,
    *,
    keep_caption: bool,
    wanted_tag: str = "",
    sent_state: set[str] | None = None,
    skip_already_sent: bool = True,
) -> tuple[int, int, int]:
    """Descarga una vez, envia a cada #hashtag y borra el temporal al terminar.

    Retorna: (enviados, repetidos, errores)
    """
    if not message or not is_video(message):
        return (0, 0, 0)

    all_topics = topics_for_message(message)
    if not all_topics:
        print(f"[SIN HASHTAG] mensaje {message.id} ignorado")
        return (0, 0, 0)

    wanted = normalize_text(wanted_tag.lstrip("#"))
    if wanted:
        all_topics = [t for t in all_topics if normalize_text(t) == wanted]
        if not all_topics:
            return (0, 0, 0)

    source_peer = utils.get_peer_id(source)
    destination_peer = utils.get_peer_id(destination)
    sent_state = sent_state if sent_state is not None else set()

    pending_topics: list[tuple[str, str]] = []
    repeated = 0
    for topic in all_topics:
        # Registro por TEMA: si un mensaje tiene 2 hashtags, cada envio se recuerda aparte.
        state_key = f"{source_peer}:{message.id}->{destination_peer}:#{normalize_text(topic)}"
        if skip_already_sent and state_key in sent_state:
            repeated += 1
            print(f"[YA ENVIADO] mensaje {message.id} -> {topic}")
            continue
        pending_topics.append((topic, state_key))

    if not pending_topics:
        return (0, repeated, 0)

    local_path: Path | None = None
    sent_count = 0
    errors_count = 0

    try:
        # IMPORTANTE: primero se descarga. Solo despues se crea/busca el tema.
        # Asi no quedan temas vacios si la descarga falla.
        local_path = await download_video_temporarily(client, source_peer, message)

        for topic, state_key in pending_topics:
            try:
                await send_temp_video_to_topic(
                    client,
                    destination,
                    local_path,
                    message,
                    topic,
                    topic_manager,
                    keep_caption=keep_caption,
                )
                sent_count += 1
                sent_state.add(state_key)
                save_sent(sent_state)
            except Exception as exc:
                errors_count += 1
                print(
                    f"[ERROR ENVIO] mensaje {message.id} -> {topic}: "
                    f"{type(exc).__name__}: {exc}"
                )

    finally:
        if local_path is not None:
            try:
                local_path.unlink(missing_ok=True)
                print(f"[TEMP BORRADO] {local_path.name}")
            except Exception as exc:
                print(f"[AVISO] No pude borrar temporal {local_path}: {exc}")
        # La carpeta temp queda eliminada si ya esta vacia.
        try:
            if TEMP_DIR.exists() and not any(TEMP_DIR.iterdir()):
                TEMP_DIR.rmdir()
        except Exception:
            pass

    return (sent_count, repeated, errors_count)


async def scan_and_send(
    client: TelegramClient,
    source,
    destination,
    *,
    hashtag_filter: str = "",
    min_id: int = 0,
    reverse: bool = True,
) -> None:
    cfg = load_config()
    keep_caption = bool(cfg.get("keep_caption", True))
    create_topics = bool(cfg.get("create_topics", True))
    skip_already_sent = bool(cfg.get("skip_already_sent", True))

    source_peer = utils.get_peer_id(source)
    destination_peer = utils.get_peer_id(destination)

    if source_peer == destination_peer:
        raise RuntimeError("El grupo origen y el grupo destino no pueden ser el mismo.")

    # Borra restos temporales de una ejecucion anterior.
    cleanup_temp_dir()

    sent_state = load_sent()
    topic_manager = TopicManager(client, destination, create_topics=create_topics)
    wanted = normalize_text(hashtag_filter.lstrip("#"))

    checked = 0
    videos = 0
    videos_with_hashtag = 0
    sent_count = 0
    repeated = 0
    skipped_no_hashtag = 0
    skipped_filter = 0
    errors_count = 0

    kwargs = {"reverse": reverse, "limit": None}
    if min_id > 0:
        kwargs["min_id"] = min_id

    print("\n===============================================")
    print(f"ORIGEN : {chat_name(source)}")
    print(f"DESTINO: {chat_name(destination)}")
    if wanted:
        print(f"FILTRO : #{hashtag_filter.lstrip('#')}")
    print("MODO   : descargar TEMP -> subir -> borrar TEMP")
    print("===============================================")
    print("Revisando mensajes...\n")

    try:
        async for message in client.iter_messages(source, **kwargs):
            checked += 1

            if checked % 100 == 0:
                print(
                    f"[PROGRESO] revisados={checked} videos={videos} "
                    f"envios={sent_count}"
                )

            if not is_video(message):
                continue

            videos += 1
            tags = topics_for_message(message)
            if not tags:
                skipped_no_hashtag += 1
                continue

            videos_with_hashtag += 1

            if wanted and wanted not in {normalize_text(x) for x in tags}:
                skipped_filter += 1
                continue

            try:
                sent_now, repeated_now, errors_now = await process_video_message(
                    client,
                    source,
                    destination,
                    message,
                    topic_manager,
                    keep_caption=keep_caption,
                    wanted_tag=hashtag_filter,
                    sent_state=sent_state,
                    skip_already_sent=skip_already_sent,
                )
                sent_count += sent_now
                repeated += repeated_now
                errors_count += errors_now
            except Exception as exc:
                errors_count += 1
                print(
                    f"[ERROR] mensaje {getattr(message, 'id', '?')}: "
                    f"{type(exc).__name__}: {exc}"
                )
    finally:
        # Garantia adicional: al finalizar/cancelar, no dejamos videos locales.
        cleanup_temp_dir()

    print("\n============== TERMINADO ==============")
    print(f"Mensajes revisados   : {checked}")
    print(f"Videos encontrados   : {videos}")
    print(f"Videos con hashtag   : {videos_with_hashtag}")
    print(f"Envios realizados    : {sent_count}")
    print(f"Ya enviados          : {repeated}")
    print(f"Sin hashtag          : {skipped_no_hashtag}")
    if wanted:
        print(f"Fuera del hashtag    : {skipped_filter}")
    print(f"Errores               : {errors_count}")
    print("Temporales locales   : BORRADOS")
    print("=========================================\n")


async def send_one_link(
    client: TelegramClient,
    link: str,
    destination_value: str,
) -> None:
    parsed = parse_telegram_link(link)
    if not parsed or not parsed[1]:
        raise RuntimeError("El enlace no contiene un ID de mensaje valido.")

    chat_ref, message_id = parsed
    source = await resolve_chat(client, chat_ref)
    destination = await resolve_chat(client, destination_value)
    message = await client.get_messages(source, ids=message_id)

    if not message:
        raise RuntimeError("No encontre ese mensaje.")
    if not is_video(message):
        raise RuntimeError("Ese mensaje no contiene un video.")
    if not topics_for_message(message):
        raise RuntimeError("Ese video no tiene ningun #hashtag; se ignora.")

    cfg = load_config()
    manager = TopicManager(
        client,
        destination,
        create_topics=bool(cfg.get("create_topics", True)),
    )
    sent_state = load_sent()

    cleanup_temp_dir()
    try:
        sent_now, repeated_now, errors_now = await process_video_message(
            client,
            source,
            destination,
            message,
            manager,
            keep_caption=bool(cfg.get("keep_caption", True)),
            sent_state=sent_state,
            skip_already_sent=bool(cfg.get("skip_already_sent", True)),
        )
        if errors_now:
            raise RuntimeError(f"Hubo {errors_now} error(es) al enviar el video.")
        if sent_now == 0 and repeated_now:
            print("[OK] Ese video ya habia sido enviado a sus temas.")
    finally:
        cleanup_temp_dir()


async def send_from_link_to_end(
    client: TelegramClient,
    link: str,
    destination_value: str,
) -> None:
    parsed = parse_telegram_link(link)
    if not parsed or not parsed[1]:
        raise RuntimeError("El enlace no contiene un ID de mensaje valido.")

    chat_ref, start_id = parsed
    source = await resolve_chat(client, chat_ref)
    destination = await resolve_chat(client, destination_value)

    await scan_and_send(
        client,
        source,
        destination,
        min_id=max(0, int(start_id) - 1),
        reverse=True,
    )


async def send_entire_group(
    client: TelegramClient,
    source_value: str,
    destination_value: str,
    tag: str = "",
) -> None:
    source = await resolve_chat(client, source_value)
    destination = await resolve_chat(client, destination_value)
    await scan_and_send(
        client,
        source,
        destination,
        hashtag_filter=tag,
        reverse=True,
    )


# ============================================================
# MENU CMD / POWERSHELL
# ============================================================

def print_header() -> None:
    print("\n" + "=" * 66)
    print(" TELEGRAM VIDEO COPIER - SOLO PYTHON / CMD / POWERSHELL")
    print(" Grupo origen -> temas por #hashtag -> grupo destino")
    print(" TEMPORAL: descarga -> envia -> borra")
    print("=" * 66)


def print_menu() -> None:
    print("1. Buscar videos con #hashtag y enviarlos por temas")
    print("2. Enviar videos de UN #hashtag")
    print("3. Enviar UN video pegando su enlace")
    print("4. Enviar DESDE un enlace hasta el ultimo mensaje")
    print("5. Cambiar grupo origen / destino / configuracion")
    print("6. Borrar registro de 'ya enviados'")
    print("0. Salir")


def ask_source(default: str) -> str:
    value = input(
        f"Grupo ORIGEN ID/@usuario/link [{default or 'sin configurar'}]: "
    ).strip() or default
    if not value:
        raise RuntimeError("Falta indicar el grupo origen.")
    return value


def ask_destination(default: str) -> str:
    value = input(
        f"Grupo DESTINO ID/@usuario/link [{default or 'sin configurar'}]: "
    ).strip() or default
    if not value:
        raise RuntimeError(
            "Falta el grupo destino. Cuando tengas el ID, pegalo aqui."
        )
    return value


async def interactive() -> None:
    api_id, api_hash, phone = credentials()
    client = TelegramClient(
        SESSION_PATH,
        api_id,
        api_hash,
        auto_reconnect=True,
        connection_retries=5,
        retry_delay=3,
    )

    await ensure_login(client, phone)

    try:
        while True:
            print_header()
            cfg = load_config()
            print(f"Origen : {cfg.get('source_group') or '(ninguno)'}")
            destination_saved = (
                str(cfg.get("destination_group", "") or "")
                if bool(cfg.get("destination_confirmed", False))
                else ""
            )
            print(f"Destino: {destination_saved or '(pendiente de poner ID)'}\n")
            print_menu()

            option = input("\nElige una opcion: ").strip()

            try:
                if option == "1":
                    source = ask_source(str(cfg.get("source_group", "") or ""))
                    destination = ask_destination(
                        str(cfg.get("destination_group", "") or "")
                        if bool(cfg.get("destination_confirmed", False)) else ""
                    )
                    save_config({
                        "source_group": source,
                        "destination_group": destination,
                        "destination_confirmed": True,
                    })
                    await send_entire_group(client, source, destination)

                elif option == "2":
                    source = ask_source(str(cfg.get("source_group", "") or ""))
                    destination = ask_destination(
                        str(cfg.get("destination_group", "") or "")
                        if bool(cfg.get("destination_confirmed", False)) else ""
                    )
                    tag = input("Hashtag (ejemplo #VeneciaLopez): ").strip()
                    if not tag:
                        raise RuntimeError("Falta el hashtag.")
                    save_config({
                        "source_group": source,
                        "destination_group": destination,
                        "destination_confirmed": True,
                    })
                    await send_entire_group(client, source, destination, tag)

                elif option == "3":
                    destination = ask_destination(
                        str(cfg.get("destination_group", "") or "")
                        if bool(cfg.get("destination_confirmed", False)) else ""
                    )
                    link = input("Pega el enlace del video: ").strip()
                    save_config({"destination_group": destination, "destination_confirmed": True})
                    await send_one_link(client, link, destination)

                elif option == "4":
                    destination = ask_destination(
                        str(cfg.get("destination_group", "") or "")
                        if bool(cfg.get("destination_confirmed", False)) else ""
                    )
                    link = input("Pega el enlace INICIAL: ").strip()
                    save_config({"destination_group": destination, "destination_confirmed": True})
                    await send_from_link_to_end(client, link, destination)

                elif option == "5":
                    await client.disconnect()
                    configure()
                    api_id, api_hash, phone = credentials()
                    client = TelegramClient(
                        SESSION_PATH,
                        api_id,
                        api_hash,
                        auto_reconnect=True,
                        connection_retries=5,
                        retry_delay=3,
                    )
                    await ensure_login(client, phone)

                elif option == "6":
                    answer = input(
                        "Escribe SI para permitir reenviar videos anteriores: "
                    ).strip().upper()
                    if answer == "SI":
                        if SENT_PATH.exists():
                            SENT_PATH.unlink()
                        print("[OK] Registro eliminado.")
                    else:
                        print("Cancelado.")

                elif option == "0":
                    print("Saliendo...")
                    break

                else:
                    print("Opcion invalida.")

            except KeyboardInterrupt:
                print("\nOperacion cancelada.")
            except Exception as exc:
                print(f"\n[ERROR] {type(exc).__name__}: {exc}\n")

            if option != "0":
                input("Presiona ENTER para volver al menu...")

    finally:
        cleanup_temp_dir()
        if client.is_connected():
            await client.disconnect()


async def command_mode(args: list[str]) -> bool:
    """Comandos rapidos opcionales para PowerShell."""
    if not args:
        return False

    cmd = args[0].lower()
    if cmd not in {"grupo", "hashtag", "link", "desde"}:
        return False

    cfg = load_config()
    destination = (
        str(cfg.get("destination_group", "") or "").strip()
        if bool(cfg.get("destination_confirmed", False)) else ""
    )

    # Permite: py main.py ... --destino -1001234567890
    if "--destino" in args:
        pos = args.index("--destino")
        if pos + 1 >= len(args):
            raise RuntimeError("Falta el ID despues de --destino")
        destination = args[pos + 1]
        args = args[:pos] + args[pos + 2:]
        save_config({"destination_group": destination, "destination_confirmed": True})

    if not destination:
        raise RuntimeError(
            "Falta el grupo destino. Ejecuta 'py main.py' o agrega "
            "--destino -100XXXXXXXXXX"
        )

    api_id, api_hash, phone = credentials()
    client = TelegramClient(SESSION_PATH, api_id, api_hash)
    await ensure_login(client, phone)

    try:
        if cmd == "grupo":
            if len(args) < 2:
                raise RuntimeError(
                    "Uso: py main.py grupo <ORIGEN> --destino <DESTINO>"
                )
            await send_entire_group(client, args[1], destination)

        elif cmd == "hashtag":
            if len(args) < 3:
                raise RuntimeError(
                    "Uso: py main.py hashtag <ORIGEN> <#hashtag> "
                    "--destino <DESTINO>"
                )
            await send_entire_group(client, args[1], destination, args[2])

        elif cmd == "link":
            if len(args) < 2:
                raise RuntimeError(
                    "Uso: py main.py link <ENLACE> --destino <DESTINO>"
                )
            await send_one_link(client, args[1], destination)

        elif cmd == "desde":
            if len(args) < 2:
                raise RuntimeError(
                    "Uso: py main.py desde <ENLACE> --destino <DESTINO>"
                )
            await send_from_link_to_end(client, args[1], destination)

        return True

    finally:
        cleanup_temp_dir()
        if client.is_connected():
            await client.disconnect()


async def main() -> None:
    cleanup_temp_dir()
    try:
        handled = await command_mode(sys.argv[1:])
        if not handled:
            await interactive()
    except KeyboardInterrupt:
        print("\nCancelado.")
    except Exception as exc:
        print(f"\n[ERROR] {type(exc).__name__}: {exc}")
        print("Ejecuta: py main.py")
    finally:
        cleanup_temp_dir()


if __name__ == "__main__":
    asyncio.run(main())
