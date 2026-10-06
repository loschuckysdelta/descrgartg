from __future__ import annotations

import asyncio
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import storage
import telegram_core as tg


APP_TITLE = "Telegram Video Manager"


class App(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 650)

        self.config_data = storage.load_config()
        self.phone_code_hash = None
        self.worker_queue = queue.Queue()
        self.search_results = []

        self._build_style()
        self._build_ui()
        self._load_settings()
        self._refresh_history()

        self.after(150, self._poll_worker_queue)
        self.after(700, self.check_session)

    # =========================================================
    # ESTILO
    # =========================================================

    def _build_style(self):
        style = ttk.Style(self)

        try:
            style.theme_use("vista")
        except Exception:
            pass

        style.configure(
            "Title.TLabel",
            font=("Segoe UI", 17, "bold")
        )

        style.configure(
            "Status.TLabel",
            font=("Segoe UI", 10, "bold")
        )

        style.configure(
            "Treeview",
            rowheight=28
        )

    # =========================================================
    # INTERFAZ
    # =========================================================

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=12
        )

        self.notebook = notebook

        self.tab_home = ttk.Frame(notebook)
        self.tab_search = ttk.Frame(notebook)
        self.tab_topics = ttk.Frame(notebook)
        self.tab_history = ttk.Frame(notebook)
        self.tab_settings = ttk.Frame(notebook)

        notebook.add(
            self.tab_home,
            text="Inicio"
        )

        notebook.add(
            self.tab_search,
            text="Buscar y enviar"
        )

        notebook.add(
            self.tab_topics,
            text="Temas"
        )

        notebook.add(
            self.tab_history,
            text="Historial"
        )

        notebook.add(
            self.tab_settings,
            text="Configuración"
        )

        self._build_home()
        self._build_search()
        self._build_topics()
        self._build_history()
        self._build_settings()

    # =========================================================
    # INICIO
    # =========================================================

    def _build_home(self):
        f = self.tab_home

        ttk.Label(
            f,
            text="Telegram Video Manager",
            style="Title.TLabel"
        ).pack(
            anchor="w",
            padx=16,
            pady=(16, 4)
        )

        ttk.Label(
            f,
            text=(
                "Video + hashtag → tema del mismo nombre → "
                "envío → borrado del archivo temporal."
            ),
            wraplength=900
        ).pack(
            anchor="w",
            padx=16,
            pady=(0, 12)
        )

        info = ttk.LabelFrame(
            f,
            text="Estado"
        )

        info.pack(
            fill="x",
            padx=16,
            pady=8
        )

        self.session_label = ttk.Label(
            info,
            text="Sesión: comprobando...",
            style="Status.TLabel"
        )

        self.session_label.pack(
            anchor="w",
            padx=12,
            pady=6
        )

        self.source_label = ttk.Label(
            info,
            text="Origen: -"
        )

        self.source_label.pack(
            anchor="w",
            padx=12,
            pady=3
        )

        self.dest_label = ttk.Label(
            info,
            text="Destino: -"
        )

        self.dest_label.pack(
            anchor="w",
            padx=12,
            pady=(3, 10)
        )

        actions = ttk.Frame(f)

        actions.pack(
            fill="x",
            padx=16,
            pady=8
        )

        ttk.Button(
            actions,
            text="Sincronizar historial completo",
            command=self.sync_all
        ).pack(
            side="left",
            padx=(0, 8)
        )

        ttk.Button(
            actions,
            text="Ir al buscador",
            command=lambda: self.notebook.select(
                self.tab_search
            )
        ).pack(
            side="left",
            padx=8
        )

        ttk.Button(
            actions,
            text="Configuración",
            command=lambda: self.notebook.select(
                self.tab_settings
            )
        ).pack(
            side="left",
            padx=8
        )

        log_frame = ttk.LabelFrame(
            f,
            text="Actividad"
        )

        log_frame.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=12
        )

        self.log_text = tk.Text(
            log_frame,
            height=18,
            wrap="word"
        )

        self.log_text.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8
        )

    # =========================================================
    # BUSCADOR
    # =========================================================

    def _build_search(self):
        f = self.tab_search

        ttk.Label(
            f,
            text="Buscar videos",
            style="Title.TLabel"
        ).pack(
            anchor="w",
            padx=16,
            pady=(16, 8)
        )

        bar = ttk.Frame(f)

        bar.pack(
            fill="x",
            padx=16,
            pady=6
        )

        self.search_var = tk.StringVar()

        entry = ttk.Entry(
            bar,
            textvariable=self.search_var
        )

        entry.pack(
            side="left",
            fill="x",
            expand=True
        )

        entry.bind(
            "<Return>",
            lambda event: self.search()
        )

        ttk.Button(
            bar,
            text="Buscar",
            command=self.search
        ).pack(
            side="left",
            padx=(8, 0)
        )

        self.search_status = ttk.Label(
            f,
            text=(
                "Busca por #hashtag, texto "
                "o link de mensaje de Telegram."
            )
        )

        self.search_status.pack(
            anchor="w",
            padx=16,
            pady=(0, 8)
        )

        tree_frame = ttk.Frame(f)

        tree_frame.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=4
        )

        columns = (
            "id",
            "hashtag",
            "date",
            "text"
        )

        self.search_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="extended"
        )

        self.search_tree.heading(
            "id",
            text="ID mensaje"
        )

        self.search_tree.heading(
            "hashtag",
            text="Hashtag"
        )

        self.search_tree.heading(
            "date",
            text="Fecha"
        )

        self.search_tree.heading(
            "text",
            text="Texto"
        )

        self.search_tree.column(
            "id",
            width=110,
            anchor="center"
        )

        self.search_tree.column(
            "hashtag",
            width=180
        )

        self.search_tree.column(
            "date",
            width=160
        )

        self.search_tree.column(
            "text",
            width=600
        )

        yscroll = ttk.Scrollbar(
            tree_frame,
            orient="vertical",
            command=self.search_tree.yview
        )

        self.search_tree.configure(
            yscrollcommand=yscroll.set
        )

        self.search_tree.pack(
            side="left",
            fill="both",
            expand=True
        )

        yscroll.pack(
            side="right",
            fill="y"
        )

        btns = ttk.Frame(f)

        btns.pack(
            fill="x",
            padx=16,
            pady=10
        )

        ttk.Button(
            btns,
            text="Enviar seleccionados",
            command=self.send_selected
        ).pack(
            side="left",
            padx=(0, 8)
        )

        ttk.Button(
            btns,
            text="Enviar todos",
            command=self.send_all_results
        ).pack(
            side="left",
            padx=8
        )

        ttk.Button(
            btns,
            text="Limpiar resultados",
            command=self.clear_results
        ).pack(
            side="left",
            padx=8
        )

    # =========================================================
    # TEMAS
    # =========================================================

    def _build_topics(self):
        f = self.tab_topics

        ttk.Label(
            f,
            text="Temas del grupo destino",
            style="Title.TLabel"
        ).pack(
            anchor="w",
            padx=16,
            pady=(16, 8)
        )

        ttk.Button(
            f,
            text="Actualizar temas",
            command=self.refresh_topics
        ).pack(
            anchor="w",
            padx=16,
            pady=(0, 8)
        )

        self.topics_tree = ttk.Treeview(
            f,
            columns=("id", "title"),
            show="headings"
        )

        self.topics_tree.heading(
            "id",
            text="ID tema"
        )

        self.topics_tree.heading(
            "title",
            text="Nombre"
        )

        self.topics_tree.column(
            "id",
            width=180,
            anchor="center"
        )

        self.topics_tree.column(
            "title",
            width=650
        )

        self.topics_tree.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=8
        )

        ttk.Label(
            f,
            text=(
                "Ejemplo: #VeneciaLopez → tema VeneciaLopez. "
                "Si el tema no existe, puede crearse automáticamente."
            ),
            wraplength=900
        ).pack(
            anchor="w",
            padx=16,
            pady=(0, 16)
        )

    # =========================================================
    # HISTORIAL
    # =========================================================

    def _build_history(self):
        f = self.tab_history

        ttk.Label(
            f,
            text="Historial de envíos",
            style="Title.TLabel"
        ).pack(
            anchor="w",
            padx=16,
            pady=(16, 8)
        )

        btns = ttk.Frame(f)

        btns.pack(
            fill="x",
            padx=16,
            pady=(0, 8)
        )

        ttk.Button(
            btns,
            text="Actualizar",
            command=self._refresh_history
        ).pack(
            side="left"
        )

        ttk.Button(
            btns,
            text="Borrar historial",
            command=self.clear_history
        ).pack(
            side="left",
            padx=8
        )

        cols = (
            "source_id",
            "hashtag",
            "topic",
            "topic_id",
            "dest_id",
            "date"
        )

        self.history_tree = ttk.Treeview(
            f,
            columns=cols,
            show="headings"
        )

        headers = [
            ("source_id", "Mensaje origen", 120),
            ("hashtag", "Hashtag", 160),
            ("topic", "Tema", 190),
            ("topic_id", "ID tema", 100),
            ("dest_id", "Mensaje destino", 130),
            ("date", "Fecha", 170)
        ]

        for key, title, width in headers:
            self.history_tree.heading(
                key,
                text=title
            )

            self.history_tree.column(
                key,
                width=width
            )

        self.history_tree.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=(0, 16)
        )

    # =========================================================
    # CONFIGURACIÓN
    # =========================================================

    def _build_settings(self):
        f = self.tab_settings

        ttk.Label(
            f,
            text="Configuración",
            style="Title.TLabel"
        ).pack(
            anchor="w",
            padx=16,
            pady=(16, 8)
        )

        form = ttk.LabelFrame(
            f,
            text="Telegram y grupos"
        )

        form.pack(
            fill="x",
            padx=16,
            pady=8
        )

        self.api_id_var = tk.StringVar()
        self.api_hash_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.dest_var = tk.StringVar()

        self.create_topics_var = tk.BooleanVar(
            value=True
        )

        self.keep_caption_var = tk.BooleanVar(
            value=True
        )

        self.search_limit_var = tk.StringVar(
            value="5000"
        )

        fields = [
            ("API ID", self.api_id_var, False),
            ("API Hash", self.api_hash_var, True),
            ("Teléfono", self.phone_var, False),
            ("ID grupo origen", self.source_var, False),
            ("ID grupo destino", self.dest_var, False),
            ("Límite de búsqueda", self.search_limit_var, False)
        ]

        for row, (label, var, secret) in enumerate(fields):
            ttk.Label(
                form,
                text=label + ":"
            ).grid(
                row=row,
                column=0,
                sticky="w",
                padx=10,
                pady=6
            )

            entry = ttk.Entry(
                form,
                textvariable=var,
                show="*" if secret else ""
            )

            entry.grid(
                row=row,
                column=1,
                sticky="ew",
                padx=10,
                pady=6
            )

        form.columnconfigure(
            1,
            weight=1
        )

        ttk.Checkbutton(
            form,
            text="Crear temas automáticamente si no existen",
            variable=self.create_topics_var
        ).grid(
            row=6,
            column=1,
            sticky="w",
            padx=10,
            pady=5
        )

        ttk.Checkbutton(
            form,
            text="Conservar el texto/caption original",
            variable=self.keep_caption_var
        ).grid(
            row=7,
            column=1,
            sticky="w",
            padx=10,
            pady=(5, 10)
        )

        buttons = ttk.Frame(f)

        buttons.pack(
            fill="x",
            padx=16,
            pady=6
        )

        ttk.Button(
            buttons,
            text="Guardar configuración",
            command=self.save_settings
        ).pack(
            side="left"
        )

        ttk.Button(
            buttons,
            text="Borrar ID origen",
            command=self.clear_source_id
        ).pack(
            side="left",
            padx=6
        )

        ttk.Button(
            buttons,
            text="Borrar ID destino",
            command=self.clear_dest_id
        ).pack(
            side="left",
            padx=6
        )

        ttk.Button(
            buttons,
            text="Borrar API Hash guardado",
            command=self.delete_hash
        ).pack(
            side="left",
            padx=6
        )

        login = ttk.LabelFrame(
            f,
            text="Inicio de sesión de Telegram"
        )

        login.pack(
            fill="x",
            padx=16,
            pady=12
        )

        self.code_var = tk.StringVar()
        self.password_var = tk.StringVar()

        ttk.Label(
            login,
            text="Código:"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=10,
            pady=6
        )

        ttk.Entry(
            login,
            textvariable=self.code_var
        ).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=10,
            pady=6
        )

        ttk.Label(
            login,
            text="Contraseña 2FA:"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=10,
            pady=6
        )

        ttk.Entry(
            login,
            textvariable=self.password_var,
            show="*"
        ).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=10,
            pady=6
        )

        login.columnconfigure(
            1,
            weight=1
        )

        login_buttons = ttk.Frame(login)

        login_buttons.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="w",
            padx=10,
            pady=10
        )

        ttk.Button(
            login_buttons,
            text="1. Enviar código",
            command=self.send_code
        ).pack(
            side="left"
        )

        ttk.Button(
            login_buttons,
            text="2. Confirmar",
            command=self.confirm_login
        ).pack(
            side="left",
            padx=8
        )

        ttk.Button(
            login_buttons,
            text="Probar conexión",
            command=self.check_session
        ).pack(
            side="left",
            padx=8
        )

        ttk.Label(
            f,
            text=(
                "El API Hash se guarda mediante el administrador "
                "de credenciales del sistema. La sesión de Telegram "
                "se guarda localmente en la carpeta data. No la compartas."
            ),
            wraplength=950
        ).pack(
            anchor="w",
            padx=16,
            pady=8
        )

    # =========================================================
    # CONFIG
    # =========================================================

    def _load_settings(self):
        c = self.config_data

        self.api_id_var.set(
            str(c.get("api_id", ""))
        )

        self.api_hash_var.set(
            storage.load_api_hash()
        )

        self.phone_var.set(
            str(c.get("phone", ""))
        )

        self.source_var.set(
            str(c.get(
                "source_group",
                "-1003929455385"
            ))
        )

        self.dest_var.set(
            str(c.get(
                "destination_group",
                ""
            ))
        )

        self.create_topics_var.set(
            bool(c.get(
                "create_topics",
                True
            ))
        )

        self.keep_caption_var.set(
            bool(c.get(
                "keep_caption",
                True
            ))
        )

        self.search_limit_var.set(
            str(c.get(
                "search_limit",
                5000
            ))
        )

        self._update_home_labels()

    def _update_home_labels(self):
        source = (
            self.source_var.get().strip()
            or "No configurado"
        )

        dest = (
            self.dest_var.get().strip()
            or "No configurado"
        )

        self.source_label.config(
            text=f"Origen: {source}"
        )

        self.dest_label.config(
            text=f"Destino: {dest}"
        )

    def clear_source_id(self):
        self.source_var.set("")
        self._update_home_labels()

    def clear_dest_id(self):
        self.dest_var.set("")
        self._update_home_labels()

    def save_settings(self, quiet=False):
        try:
            api_id = self.api_id_var.get().strip()

            if api_id:
                int(api_id)

            source = self.source_var.get().strip()
            dest = self.dest_var.get().strip()

            if source:
                int(source)

            if dest:
                int(dest)

            limit = int(
                self.search_limit_var.get().strip()
                or "5000"
            )

            if limit < 100:
                raise ValueError(
                    "El límite de búsqueda debe ser 100 o más."
                )

            self.config_data = {
                "api_id": api_id,
                "phone": self.phone_var.get().strip(),
                "source_group": source,
                "destination_group": dest,
                "create_topics": self.create_topics_var.get(),
                "keep_caption": self.keep_caption_var.get(),
                "search_limit": limit
            }

            storage.save_config(
                self.config_data
            )

            api_hash = self.api_hash_var.get().strip()

            if api_hash:
                storage.save_api_hash(
                    api_hash
                )

            self._update_home_labels()

            if not quiet:
                messagebox.showinfo(
                    "Guardado",
                    "Configuración guardada."
                )

            return True

        except Exception as exc:
            if not quiet:
                messagebox.showerror(
                    "Error",
                    str(exc)
                )

            return False

    def _credentials(self):
        if not self.save_settings(
            quiet=True
        ):
            raise ValueError(
                "La configuración contiene datos inválidos."
            )

        api_id = self.api_id_var.get().strip()

        api_hash = (
            self.api_hash_var.get().strip()
            or storage.load_api_hash()
        )

        if not api_id:
            raise ValueError(
                "Falta API ID."
            )

        if not api_hash:
            raise ValueError(
                "Falta API Hash."
            )

        return int(api_id), api_hash

    def _groups(self, require_dest=True):
        source = tg.parse_group_id(
            self.source_var.get()
        )

        if require_dest:
            dest = tg.parse_group_id(
                self.dest_var.get()
            )

            return source, dest

        return source

    def delete_hash(self):
        if messagebox.askyesno(
            "Confirmar",
            "¿Borrar el API Hash guardado?"
        ):
            storage.delete_api_hash()
            self.api_hash_var.set("")

    # =========================================================
    # LOG / THREADS
    # =========================================================

    def _log(self, text):
        self.log_text.insert(
            "end",
            str(text) + "\n"
        )

        self.log_text.see(
            "end"
        )

    def _poll_worker_queue(self):
        try:
            while True:
                kind, payload, callback = (
                    self.worker_queue.get_nowait()
                )

                if kind == "log":
                    self._log(
                        payload
                    )

                elif kind == "progress":
                    if callback:
                        callback(
                            payload
                        )

                elif kind == "result":
                    if callback:
                        callback(
                            payload
                        )

                elif kind == "error":
                    self._log(
                        "ERROR: " + payload
                    )

                    messagebox.showerror(
                        "Error",
                        payload
                    )

        except queue.Empty:
            pass

        self.after(
            150,
            self._poll_worker_queue
        )

    def _run_async(
        self,
        coro_factory,
        on_done=None,
        on_progress=None
    ):
        def runner():
            try:
                def log(msg):
                    self.worker_queue.put(
                        (
                            "log",
                            str(msg),
                            None
                        )
                    )

                def progress(*args):
                    self.worker_queue.put(
                        (
                            "progress",
                            args,
                            on_progress
                        )
                    )

                result = asyncio.run(
                    coro_factory(
                        log,
                        progress
                    )
                )

                self.worker_queue.put(
                    (
                        "result",
                        result,
                        on_done
                    )
                )

            except Exception as exc:
                # IMPORTANTE:
                # Convertimos el error a texto aquí mismo.
                # Así NO usamos "e" o "exc" dentro de un lambda tardío.
                error_text = (
                    f"{type(exc).__name__}: {exc}"
                )

                self.worker_queue.put(
                    (
                        "error",
                        error_text,
                        None
                    )
                )

        threading.Thread(
            target=runner,
            daemon=True
        ).start()

    # =========================================================
    # SESIÓN TELEGRAM
    # =========================================================

    def check_session(self):
        try:
            api_id, api_hash = (
                self._credentials()
            )

        except Exception:
            self.session_label.config(
                text="Sesión: sin configurar"
            )

            return

        async def work(log, progress):
            return await tg.auth_status(
                api_id,
                api_hash
            )

        def done(result):
            ok, me = result

            if ok:
                name = (
                    getattr(
                        me,
                        "first_name",
                        ""
                    )
                    or ""
                )

                username = (
                    getattr(
                        me,
                        "username",
                        ""
                    )
                    or ""
                )

                suffix = (
                    f" @{username}"
                    if username
                    else ""
                )

                self.session_label.config(
                    text=(
                        "Sesión: conectada - "
                        f"{name}{suffix}"
                    )
                )

            else:
                self.session_label.config(
                    text=(
                        "Sesión: falta iniciar sesión"
                    )
                )

        self._run_async(
            work,
            done
        )

    def send_code(self):
        try:
            api_id, api_hash = (
                self._credentials()
            )

            phone = (
                self.phone_var.get().strip()
            )

            if not phone:
                raise ValueError(
                    "Escribe tu teléfono con código de país."
                )

        except Exception as exc:
            messagebox.showerror(
                "Error",
                str(exc)
            )

            return

        async def work(log, progress):
            return await tg.send_login_code(
                api_id,
                api_hash,
                phone
            )

        def done(data):
            if data["authorized"]:
                messagebox.showinfo(
                    "Telegram",
                    "La sesión ya estaba iniciada."
                )

                self.check_session()
                return

            self.phone_code_hash = (
                data["phone_code_hash"]
            )

            messagebox.showinfo(
                "Código enviado",
                (
                    "Telegram envió un código. "
                    "Escríbelo en el campo Código "
                    "y pulsa Confirmar."
                )
            )

        self._run_async(
            work,
            done
        )

    def confirm_login(self):
        try:
            api_id, api_hash = (
                self._credentials()
            )

            phone = (
                self.phone_var.get().strip()
            )

            code = (
                self.code_var.get().strip()
            )

            if not phone or not code:
                raise ValueError(
                    "Falta teléfono o código."
                )

            if not self.phone_code_hash:
                raise ValueError(
                    "Primero pulsa 'Enviar código'."
                )

        except Exception as exc:
            messagebox.showerror(
                "Error",
                str(exc)
            )

            return

        password = (
            self.password_var.get()
        )

        async def work(log, progress):
            return await tg.confirm_login(
                api_id,
                api_hash,
                phone,
                code,
                self.phone_code_hash,
                password
            )

        def done(me):
            self.code_var.set("")
            self.password_var.set("")
            self.phone_code_hash = None

            messagebox.showinfo(
                "Listo",
                "Sesión de Telegram iniciada."
            )

            self.check_session()

        self._run_async(
            work,
            done
        )

    # =========================================================
    # BUSCAR
    # =========================================================

    def search(self):
        try:
            api_id, api_hash = (
                self._credentials()
            )

            source = (
                self._groups(
                    require_dest=False
                )
            )

            query = (
                self.search_var.get().strip()
            )

            limit = int(
                self.search_limit_var.get()
            )

        except Exception as exc:
            messagebox.showerror(
                "Error",
                str(exc)
            )

            return

        self.search_status.config(
            text="Buscando..."
        )

        self.clear_results()

        async def work(log, progress):
            return await tg.search_videos(
                api_id,
                api_hash,
                source,
                query,
                limit,
                progress=lambda checked: progress(
                    checked
                )
            )

        def prog(args):
            checked = args[0]

            self.search_status.config(
                text=(
                    f"Revisados {checked} mensajes..."
                )
            )

        def done(rows):
            self.search_results = rows

            for row in rows:
                text = (
                    row["text"]
                    .replace("\n", " ")
                    [:500]
                )

                hashtag = (
                    "#" + row["hashtag"]
                    if row["hashtag"]
                    else ""
                )

                self.search_tree.insert(
                    "",
                    "end",
                    values=(
                        row["message_id"],
                        hashtag,
                        row["date"],
                        text
                    )
                )

            self.search_status.config(
                text=(
                    f"{len(rows)} video(s) encontrado(s)."
                )
            )

        self._run_async(
            work,
            done,
            prog
        )

    def clear_results(self):
        for item in (
            self.search_tree.get_children()
        ):
            self.search_tree.delete(
                item
            )

        self.search_results = []

    # =========================================================
    # ENVIAR
    # =========================================================

    def _selected_message_ids(self):
        selected = (
            self.search_tree.selection()
        )

        ids = []

        for item in selected:
            values = (
                self.search_tree.item(
                    item,
                    "values"
                )
            )

            if values:
                ids.append(
                    int(values[0])
                )

        return ids

    def send_selected(self):
        ids = (
            self._selected_message_ids()
        )

        if not ids:
            messagebox.showwarning(
                "Selecciona",
                "Selecciona uno o más videos."
            )

            return

        self._send_ids(
            ids
        )

    def send_all_results(self):
        ids = [
            int(x["message_id"])
            for x in self.search_results
        ]

        if not ids:
            messagebox.showwarning(
                "Sin resultados",
                "No hay videos para enviar."
            )

            return

        self._send_ids(
            ids
        )

    def _send_ids(self, ids):
        try:
            api_id, api_hash = (
                self._credentials()
            )

            source, dest = (
                self._groups()
            )

            create_topics = (
                self.create_topics_var.get()
            )

            keep_caption = (
                self.keep_caption_var.get()
            )

        except Exception as exc:
            messagebox.showerror(
                "Error",
                str(exc)
            )

            return

        self._log(
            f"Enviando {len(ids)} video(s)..."
        )

        async def work(log, progress):
            return await tg.send_selected(
                api_id,
                api_hash,
                source,
                dest,
                ids,
                create_topics,
                keep_caption,
                log=log,
                progress=lambda a, b: progress(
                    a,
                    b
                )
            )

        def prog(args):
            a, b = args

            self._log(
                f"Progreso: {a}/{b}"
            )

        def done(rows):
            sent = sum(
                1
                for x in rows
                if x.get("status") == "sent"
            )

            duplicates = sum(
                1
                for x in rows
                if x.get("status") == "duplicate"
            )

            errors_count = sum(
                1
                for x in rows
                if x.get("status") == "error"
            )

            self._refresh_history()

            messagebox.showinfo(
                "Terminado",
                (
                    f"Enviados: {sent}\n"
                    f"Ya enviados: {duplicates}\n"
                    f"Errores: {errors_count}"
                )
            )

        self._run_async(
            work,
            done,
            prog
        )

    # =========================================================
    # SINCRONIZAR TODO
    # =========================================================

    def sync_all(self):
        try:
            api_id, api_hash = (
                self._credentials()
            )

            source, dest = (
                self._groups()
            )

            create_topics = (
                self.create_topics_var.get()
            )

            keep_caption = (
                self.keep_caption_var.get()
            )

        except Exception as exc:
            messagebox.showerror(
                "Error",
                str(exc)
            )

            return

        if not messagebox.askyesno(
            "Sincronizar",
            (
                "Se revisará todo el historial del grupo origen "
                "y se enviarán los videos con hashtag que todavía "
                "no estén registrados.\n\n¿Continuar?"
            )
        ):
            return

        self._log(
            "Iniciando sincronización completa..."
        )

        async def work(log, progress):
            return await tg.sync_all(
                api_id,
                api_hash,
                source,
                dest,
                create_topics,
                keep_caption,
                log=log,
                progress=lambda checked: progress(
                    checked
                )
            )

        def prog(args):
            checked = args[0]

            self._log(
                f"Mensajes revisados: {checked}"
            )

        def done(result):
            self._refresh_history()

            messagebox.showinfo(
                "Sincronización terminada",
                (
                    f"Mensajes revisados: {result['checked']}\n"
                    f"Enviados: {result['sent']}\n"
                    f"Omitidos: {result['skipped']}\n"
                    f"Errores: {result['errors']}"
                )
            )

        self._run_async(
            work,
            done,
            prog
        )

    # =========================================================
    # TEMAS
    # =========================================================

    def refresh_topics(self):
        try:
            api_id, api_hash = (
                self._credentials()
            )

            _, dest = (
                self._groups()
            )

        except Exception as exc:
            messagebox.showerror(
                "Error",
                str(exc)
            )

            return

        async def work(log, progress):
            return await tg.get_topics(
                api_id,
                api_hash,
                dest
            )

        def done(rows):
            for item in (
                self.topics_tree.get_children()
            ):
                self.topics_tree.delete(
                    item
                )

            for row in rows:
                self.topics_tree.insert(
                    "",
                    "end",
                    values=(
                        row["id"],
                        row["title"]
                    )
                )

        self._run_async(
            work,
            done
        )

    # =========================================================
    # HISTORIAL
    # =========================================================

    def _refresh_history(self):
        for item in (
            self.history_tree.get_children()
        ):
            self.history_tree.delete(
                item
            )

        for row in storage.get_history():
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["source_message_id"],
                    "#" + row["hashtag"],
                    row["topic_title"],
                    row["topic_id"] or "",
                    row["destination_message_id"] or "",
                    row["sent_at"]
                )
            )

    def clear_history(self):
        if messagebox.askyesno(
            "Borrar historial",
            (
                "¿Seguro?\n\n"
                "Si lo borras, el programa podrá volver "
                "a enviar videos anteriores."
            )
        ):
            storage.clear_history()
            self._refresh_history()


if __name__ == "__main__":
    App().mainloop()
