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

from mrbot_app.config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_EMAIL,
    get_notificacion_messagebox,
    reload_env_defaults,
)
from mrbot_app.constants import BG, FG
from mrbot_app.helpers import _format_dates_str


class BaseWindow(tk.Toplevel):
    def __init__(self, master=None, title: str = "", config_provider=None):
        super().__init__(master)
        self.config_provider = config_provider
        self.window_title = title or self.__class__.__name__
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
        self._execution_summary: Optional[Dict[str, Any]] = None

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

    def on_env_reloaded(self) -> None:
        """
        Hook opcional para ventanas que mantienen valores precargados
        desde variables de entorno.
        """
        return

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

    def log_warning(self, message: str) -> None:
        self.log_message(self._prefix_lines("WARNING: ", message))

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

    def clear_execution_summary(self) -> None:
        self._execution_summary = None

    def set_execution_summary(self, summary: Optional[Dict[str, Any]]) -> None:
        self._execution_summary = summary if summary else None

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_optional_bool(self, value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().lower()
        if not text:
            return None
        if text in {"1", "true", "t", "si", "sí", "s", "yes", "y"}:
            return True
        if text in {"0", "false", "f", "no", "n"}:
            return False
        return None

    def _has_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) > 0
        return True

    def _classify_download_result(self, row: Dict[str, Any]) -> str:
        if not isinstance(row, dict) or not row:
            return "error"

        descargas = self._safe_int(row.get("descargas"), default=0)
        success_value = self._coerce_optional_bool(row.get("success"))
        descarga_esperada = self._coerce_optional_bool(row.get("descarga_esperada"))
        status = str(row.get("status", "")).strip().lower()
        http_status = row.get("http_status")
        download_errors = self._has_value(row.get("errores_descarga"))
        post_errors = self._has_value(row.get("errores_postproceso"))
        explicit_error = (
            self._has_value(row.get("error"))
            or self._has_value(row.get("error_message"))
            or status == "sin_salida"
        )

        try:
            http_status_int = int(http_status) if http_status is not None else None
        except (TypeError, ValueError):
            http_status_int = None

        if descarga_esperada is False:
            if download_errors or post_errors:
                return "warning"
            if success_value is False or explicit_error:
                return "error"
            if http_status_int is not None and http_status_int >= 400:
                return "error"
            return "success"

        if download_errors or post_errors:
            if descargas > 0 or success_value is True or http_status_int == 200:
                return "warning"
            return "error"

        if success_value is False or explicit_error:
            if descargas > 0:
                return "warning"
            return "error"

        if http_status_int is not None and http_status_int >= 400:
            if descargas > 0:
                return "warning"
            return "error"

        if descargas > 0:
            return "success"

        if success_value is True or http_status_int == 200 or status in {"ok", "success", "completed", "completado"}:
            return "warning"

        return "error"

    def build_download_execution_summary(
        self,
        source: str,
        rows: list[Dict[str, Any]],
        total_expected: Optional[int] = None,
    ) -> Dict[str, Any]:
        total = int(total_expected if total_expected is not None else len(rows))
        success_count = 0
        warning_count = 0
        error_count = 0

        for row in rows:
            status = self._classify_download_result(row)
            if status == "success":
                success_count += 1
            elif status == "warning":
                warning_count += 1
            else:
                error_count += 1

        processed = success_count + warning_count + error_count
        if total > processed:
            error_count += total - processed

        return {
            "source": source,
            "total": max(total, 0),
            "success": max(success_count, 0),
            "warning": max(warning_count, 0),
            "error": max(error_count, 0),
        }

    def _build_execution_message(self, summary: Dict[str, Any]) -> tuple[str, str, Callable[[str, str], str]]:
        source = str(summary.get("source") or self.window_title)
        total = self._safe_int(summary.get("total"), default=0)
        success_count = self._safe_int(summary.get("success"), default=0)
        warning_count = self._safe_int(summary.get("warning"), default=0)
        error_count = self._safe_int(summary.get("error"), default=0)

        if total <= 0:
            return "", "", messagebox.showinfo

        if error_count >= total:
            title = "Proceso con error"
            headline = "Todas las descargas fallaron."
            message_fn = messagebox.showerror
        elif error_count > 0 or warning_count > 0:
            title = "Proceso con advertencias"
            headline = "Proceso finalizado con advertencias."
            message_fn = messagebox.showwarning
        else:
            title = "Proceso exitoso"
            headline = "Todas las descargas finalizaron correctamente."
            message_fn = messagebox.showinfo

        body_lines = [
            headline,
            "",
            f"Bot: {source}",
            f"Total procesados: {total}",
            f"Exitosos: {success_count}",
            f"Con advertencia: {warning_count}",
            f"Fallidos: {error_count}",
        ]
        return title, "\n".join(body_lines), message_fn

    def maybe_show_execution_summary(self) -> None:
        if not get_notificacion_messagebox():
            self.clear_execution_summary()
            return

        summary = self._execution_summary
        self.clear_execution_summary()
        if not summary:
            return

        title, message, message_fn = self._build_execution_message(summary)
        if not title or not message:
            return
        message_fn(title, message)

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

        self.clear_execution_summary()
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
            self.clear_execution_summary()
            self.log_info("Proceso abortado por el usuario.")
            messagebox.showinfo("Abortado", "El proceso fue detenido por el usuario.")
            return

        self.maybe_show_execution_summary()

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
