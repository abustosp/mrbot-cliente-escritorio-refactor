import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pandas as pd

from mrbot_app.config import DEFAULT_API_KEY, DEFAULT_BASE_URL, DEFAULT_EMAIL, reload_env_defaults
from mrbot_app.constants import BG, FG
from mrbot_app.helpers import _format_dates_str


class BaseWindow(tk.Toplevel):
    def __init__(self, master=None, title: str = ""):
        super().__init__(master)
        self.configure(background=BG)
        self.title(title)
        self.resizable(False, False)
        style = ttk.Style(self)
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, foreground=FG)
        
        # Traer ventana al frente
        self.lift()
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(100, lambda: self.attributes('-topmost', False))

    def bring_to_front(self) -> None:
        """Trae la ventana al frente después de operaciones como filedialog."""
        self.lift()
        self.focus_force()

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
        log_text = getattr(self, "log_text", None)
        if log_text is None or not text:
            return
        log_text.configure(state="normal")
        log_text.insert(tk.END, text)
        log_text.see(tk.END)
        log_text.configure(state="disabled")
        log_text.update_idletasks()

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

    def _prefix_lines(self, prefix: str, message: str) -> str:
        lines = str(message).splitlines() or [""]
        return "\n".join(f"{prefix}{line}" if line else prefix.rstrip() for line in lines)

    def log_message(self, message: str) -> None:
        self._append_log_widget(self._format_log_message(message))

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
        toggle_btn = ttk.Button(btns_frame, text="Mostrar logs")
        toggle_btn.pack(side="left")
        export_btn = ttk.Button(btns_frame, text="Exportar logs")
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

        visible = not start_hidden
        if visible:
            log_frame.pack(fill="both", expand=True, pady=(2, 0))
            export_btn.pack(side="left", padx=(6, 0))
            toggle_btn.configure(text="Ocultar logs")

        def _export_logs() -> None:
            contents = log_text.get("1.0", tk.END).rstrip()
            default_name = f"logs-{service}.txt"
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

        def _toggle() -> None:
            nonlocal visible
            if visible:
                log_frame.pack_forget()
                export_btn.pack_forget()
                toggle_btn.configure(text="Mostrar logs")
                visible = False
            else:
                log_frame.pack(fill="both", expand=True, pady=(2, 0))
                export_btn.pack(side="left", padx=(6, 0))
                toggle_btn.configure(text="Ocultar logs")
                visible = True

        toggle_btn.configure(command=_toggle)
        export_btn.configure(command=_export_logs)
        return log_text

    def set_progress(self, current: int, total: int) -> None:
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
        progress_bar.update_idletasks()

    def set_preview(self, widget: Optional[tk.Text], content: str) -> None:
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, content)
        widget.configure(state="disabled")

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
