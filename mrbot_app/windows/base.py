import json
import os
import threading
import queue
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional, Callable

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

import pandas as pd

from mrbot_app.config import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_EMAIL, reload_env_defaults
from mrbot_app.constants import BG, FG
from mrbot_app.helpers import _format_dates_str


class BaseWindow(tk.Toplevel):
    def __init__(self, master=None, title: str = "", config_provider=None):
        super().__init__(master)
        self.config_provider = config_provider
        self.configure(background=BG)
        self.title(title)
        self.resizable(False, False)
        style = ttk.Style(self)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, foreground=FG)
        
        # Threading infrastructure
        self._abort_event = threading.Event()
        self.throbber_frame = None
        self.throbber = None
        self.abort_btn = None
        self.log_windows = []  # Keep track of open log windows
        self._log_block_local = threading.local()

        # Traer ventana al frente
        self.lift()
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

    def bring_to_front(self) -> None:
        """Trae la ventana al frente después de operaciones como filedialog."""
        self.lift()
        self.focus_force()

    def _get_config(self) -> tuple[str, str, str]:
        if self.config_provider:
            return self.config_provider()
        return DEFAULT_BASE_URL, DEFAULT_API_KEY, DEFAULT_EMAIL

    def add_section_label(self, parent, text: str) -> None:
        lbl = ttk.Label(parent, text=text, foreground=FG, background=BG, font=("Arial", 11, "bold"))
        lbl.pack(anchor="w", pady=(8, 2))

    def add_info_label(self, parent, text: str) -> ttk.Label:
        lbl = ttk.Label(parent, text=text, foreground=FG, background=BG, wraplength=420, justify="left")
        lbl.pack(anchor="w", pady=2)
        return lbl

    def add_preview(self, parent, height: int = 10, show: bool = True) -> tk.Text:
        txt = tk.Text(parent, height=height, width=70, wrap="none", background="#1e1e1e", foreground=FG)
        if show:
            txt.pack(anchor="w", pady=4, padx=2, fill="both", expand=False)
        txt.configure(state="disabled")
        return txt

    def _append_log_widget(self, text: str) -> None:
        def _update():
            log_text = getattr(self, "log_text", None)
            if log_text is None or not text:
                return
            log_text.configure(state="normal")
            log_text.insert(tk.END, text)
            log_text.see(tk.END)
            log_text.configure(state="disabled")

            # Update separate log windows
            for win_text_widget in self.log_windows:
                try:
                    win_text_widget.configure(state="normal")
                    win_text_widget.insert(tk.END, text)
                    win_text_widget.see(tk.END)
                    win_text_widget.configure(state="disabled")
                except Exception:
                    # If window was closed, this might fail, just ignore or cleanup
                    pass

        self.after(0, _update)

    def _format_log_message(self, message: str) -> str:
        if not message:
            return ""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = str(message).splitlines() or [""]
        formatted = "\n".join(
            f"[{timestamp}] {line}" if line else f"[{timestamp}]"
            for line in lines
        )
        return formatted + "\n"

    def _format_precise_timestamp(self, value: Optional[datetime] = None) -> str:
        dt = value or datetime.now()
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _log_block_stack(self) -> list:
        stack = getattr(self._log_block_local, "stack", None)
        if stack is None:
            stack = []
            self._log_block_local.stack = stack
        return stack

    @contextmanager
    def log_block(self, label: str):
        stack = self._log_block_stack()
        block_label = str(label or "sin_identificador")
        block = {"label": block_label, "lines": []}
        stack.append(block)
        self.log_message(f"EJECUCION INICIO: {self._format_precise_timestamp()}")
        try:
            yield
        finally:
            self.log_message(f"EJECUCION FIN: {self._format_precise_timestamp()}")
            finished_block = stack.pop()
            sep = "-" * 60
            header = self._format_log_message(f"{sep}\nCONTRIBUYENTE: {block_label}\n{sep}")
            content = header + "".join(finished_block["lines"])
            content_with_gap = content + self._format_log_message("")
            if stack:
                stack[-1]["lines"].append(content_with_gap)
            else:
                self._append_log_widget(content_with_gap)

    def run_with_log_block(self, label: str, fn: Callable, *args, **kwargs):
        with self.log_block(label):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                self.log_error(f"Excepcion en bloque: {exc}")
                return None

    def _prefix_lines(self, prefix: str, message: str) -> str:
        lines = str(message).splitlines() or [""]
        return "\n".join(f"{prefix}{line}" if line else prefix.rstrip() for line in lines)

    def log_message(self, message: str) -> None:
        formatted = self._format_log_message(message)
        stack = getattr(self._log_block_local, "stack", None)
        if stack:
            stack[-1]["lines"].append(formatted)
            return
        self._append_log_widget(formatted)

    def log_info(self, message: str) -> None:
        self.log_message(self._prefix_lines("INFO: ", message))

    def log_error(self, message: str) -> None:
        self.log_message(self._prefix_lines("ERROR: ", message))

    def log_request(self, payload: Any, label: str = "REQUEST") -> None:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        self.log_message(self._prefix_lines(f"{label}: ", serialized))

    def log_response(self, http_status: Any, payload: Any) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        self.log_message(self._prefix_lines("RESPONSE: ", f"HTTP {http_status} - {serialized}"))

    def log_request_started(
        self,
        payload: Any,
        label: str = "REQUEST",
        started_at: Optional[datetime] = None,
        attempt: Optional[int] = None,
        total_attempts: Optional[int] = None,
    ) -> None:
        if attempt is not None and total_attempts is not None:
            self.log_info(f"Intento {attempt}/{total_attempts}")
        self.log_message(f"{label} INICIO: {self._format_precise_timestamp(started_at)}")
        self.log_request(payload, label=label)

    def log_response_finished(
        self,
        http_status: Any,
        payload: Any,
        finished_at: Optional[datetime] = None,
    ) -> None:
        self.log_message("")
        self.log_message(f"RESPONSE FIN: {self._format_precise_timestamp(finished_at)}")
        self.log_response(http_status, payload)
        self.log_message("")

    def log_start(self, title: str, details: Optional[Dict[str, Any]] = None) -> None:
        detail_text = ""
        if details:
            detail_text = " | " + json.dumps(details, ensure_ascii=False, default=str)
        self.log_message(f"INICIADOR: {title}{detail_text}")

    def log_separator(self, label: str) -> None:
        sep = "-" * 60
        self.log_message(f"{sep}\nCONTRIBUYENTE: {label}\n{sep}")

    def add_progress_bar(self, parent, label: str = "Progreso") -> ttk.LabelFrame:
        style = ttk.Style(self)
        style.configure("Progress.TLabel", background="#1b1b1b", foreground="#ffffff")
        frame = ttk.LabelFrame(parent, text=label)
        frame.pack(fill="x", pady=(6, 0))
        frame.columnconfigure(0, weight=1)
        self._progress_label_var = tk.StringVar(value="0/0")
        self._progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate")
        self._progress_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(frame, textvariable=self._progress_label_var, style="Progress.TLabel").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        # Throbber and Abort button area
        self.throbber_frame = ttk.Frame(frame)
        self.throbber_frame.grid(row=0, column=2, sticky="e", padx=(8, 4))
        self.throbber = ttk.Progressbar(self.throbber_frame, mode="indeterminate", length=100)
        self.throbber.pack(side="left", padx=(0, 4))
        self.abort_btn = ttk.Button(self.throbber_frame, text="Abortar", command=self.abort_process)
        self.abort_btn.pack(side="left")
        self.throbber_frame.grid_remove() # Hide initially

        return frame

    def add_collapsible_log(
        self,
        parent,
        title: str = "Logs de ejecución",
        height: int = 10,
        service: str = "servicio",
        start_hidden: bool = True,
    ) -> tk.Text:
        btns_frame = ttk.Frame(parent)
        btns_frame.pack(fill="x", pady=(6, 0))
        open_new_btn = ttk.Button(btns_frame, text="Abrir logs")
        open_new_btn.pack(side="left")

        # Widget interno donde se acumulan los logs.
        # Se mantiene oculto en la ventana principal y se replica en la emergente.
        log_frame = ttk.LabelFrame(parent, text=title)
        log_text = tk.Text(
            log_frame,
            height=height,
            wrap="word",
            background="#1b1b1b",
            foreground="#ffffff",
        )
        log_text.pack(fill="both", expand=True)
        log_text.configure(state="disabled")

        # Compatibilidad: mantener parámetro start_hidden aunque ahora siempre ocultamos en principal.
        _ = start_hidden

        def _export_logs(contents: str) -> None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            default_name = f"logs - {service} - {timestamp}.txt"
            path = filedialog.asksaveasfilename(
                title="Exportar logs",
                initialdir=os.getcwd(),
                initialfile=default_name,
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            )
            self.bring_to_front()
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(contents + "\n" if contents else "")
                messagebox.showinfo("Logs exportados", f"Logs guardados en:\n{path}")
            except Exception as exc:
                messagebox.showerror("Error", f"No se pudo guardar los logs: {exc}")

        def _open_new_window() -> None:
            top = tk.Toplevel(self)
            top.title(f"Logs - {service}")
            top.geometry("800x600")
            try:
                top.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
            except Exception:
                pass

            actions = ttk.Frame(top)
            actions.pack(fill="x", padx=8, pady=(8, 4))
            export_btn = ttk.Button(actions, text="Exportar TXT")
            export_btn.pack(side="left")

            txt = scrolledtext.ScrolledText(top, wrap="word", background="#1b1b1b", foreground="#ffffff")
            txt.pack(fill="both", expand=True, padx=8, pady=(0, 8))

            # Copy current logs
            current_content = log_text.get("1.0", tk.END)
            txt.insert("1.0", current_content)
            txt.configure(state="disabled")

            def _export_from_window() -> None:
                contents = txt.get("1.0", tk.END).rstrip()
                _export_logs(contents)

            export_btn.configure(command=_export_from_window)

            self.log_windows.append(txt)

            def _on_close():
                if txt in self.log_windows:
                    self.log_windows.remove(txt)
                top.destroy()

            top.protocol("WM_DELETE_WINDOW", _on_close)

        open_new_btn.configure(command=_open_new_window)
        return log_text

    def set_progress(self, current: int, total: int) -> None:
        def _update():
            progress_bar = getattr(self, "_progress_bar", None)
            progress_label_var = getattr(self, "_progress_label_var", None)
            if progress_bar is None or progress_label_var is None:
                return
            if total <= 0:
                progress_bar.configure(maximum=1, value=0)
                progress_label_var.set("0/0")
            else:
                value = max(0, min(int(current), int(total)))
                progress_bar.configure(maximum=int(total), value=value)
                progress_label_var.set(f"{value}/{int(total)}")

        self.after(0, _update)

    def set_preview(self, widget: Optional[tk.Text], content: str) -> None:
        def _update():
            if widget is None:
                return
            widget.configure(state="normal")
            widget.delete("1.0", tk.END)
            widget.insert(tk.END, content)
            widget.configure(state="disabled")

        self.after(0, _update)

    def open_df_preview(self, df: Optional[pd.DataFrame], title: str = "Previsualización de Excel", max_rows: int = 50) -> None:
        if df is None or df.empty:
            messagebox.showwarning("Sin datos", "No hay datos para previsualizar.")
            return
        top = tk.Toplevel(self)
        top.title(title)
        try:
            top.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        top.configure(background="#f5f5f5")
        df_display = _format_dates_str(df.head(max_rows).copy())
        tk.Label(
            top,
            text=f"Registros: {len(df)} | Columnas: {len(df.columns)}",
            background="#f5f5f5",
            foreground="#000000",
            font=("Arial", 11, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 4))
        txt = tk.Text(
            top,
            height=20,
            width=120,
            wrap="none",
            background="#ffffff",
            foreground="#000000",
            font=("Courier New", 10),
        )
        txt.pack(fill="both", expand=True, padx=8, pady=4)
        txt.insert(tk.END, df_display.to_string(index=False))
        txt.configure(state="disabled")
        ttk.Button(top, text="Cerrar", command=top.destroy).pack(pady=8)

    def run_in_thread(self, target: Callable, *args, **kwargs) -> None:
        """
        Ejecuta target(*args, **kwargs) en un hilo separado.
        Muestra el throbber y habilita el boton de abortar.
        """
        if self.throbber_frame:
            self.throbber_frame.grid()
            if self.throbber:
                self.throbber.start()
            if self.abort_btn:
                self.abort_btn.state(["!disabled"])

        self._abort_event.clear()

        def _wrapper():
            try:
                target(*args, **kwargs)
            except Exception as e:
                self.log_error(f"Error en hilo: {e}")
            finally:
                self.after(0, self._on_thread_finished)

        t = threading.Thread(target=_wrapper, daemon=True)
        t.start()

    def _on_thread_finished(self) -> None:
        """Called on main thread when worker thread finishes."""
        if self.throbber:
            self.throbber.stop()
        if self.throbber_frame:
            self.throbber_frame.grid_remove()

        if self._abort_event.is_set():
            self.log_info("Proceso abortado por el usuario.")
            messagebox.showinfo("Abortado", "El proceso fue detenido por el usuario.")

    def abort_process(self) -> None:
        """Signal the worker thread to stop."""
        if messagebox.askyesno("Confirmar", "¿Desea detener el proceso actual?"):
            self._abort_event.set()
            if self.abort_btn:
                self.abort_btn.state(["disabled"])
            self.log_info("Solicitud de aborto enviada...")


class ConfigPane(ttk.Frame):
    """
    Panel de configuracion compartido (base URL, API key, email).
    """

    def __init__(self, master):
        super().__init__(master, padding=8)
        self.base_url_var = tk.StringVar(value=DEFAULT_BASE_URL)
        self.api_key_var = tk.StringVar(value=DEFAULT_API_KEY)
        self.email_var = tk.StringVar(value=DEFAULT_EMAIL)

        ttk.Label(self, text="Base URL").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(self, textvariable=self.base_url_var, width=40).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(self, text="API Key").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(self, textvariable=self.api_key_var, width=40, show="*").grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Label(self, text="Mail").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        ttk.Entry(self, textvariable=self.email_var, width=40).grid(row=2, column=1, sticky="ew", padx=4, pady=2)

        self.columnconfigure(1, weight=1)

    def get_config(self) -> tuple[str, str, str]:
        return self.base_url_var.get().strip(), self.api_key_var.get().strip(), self.email_var.get().strip()

    def set_config(self, base_url: str, api_key: str, email: str) -> None:
        self.base_url_var.set(base_url)
        self.api_key_var.set(api_key)
        self.email_var.set(email)

    def load_from_env(self) -> tuple[str, str, str]:
        base_url, api_key, email = reload_env_defaults()
        self.set_config(base_url, api_key, email)
        return base_url, api_key, email
