import os
import tkinter as tk
from tkinter import ttk, messagebox

from mrbot_app.config import ENV_FILE
from mrbot_app.constants import ACCENT, BG, FG
from mrbot_app.examples import ensure_example_excels
from mrbot_app.files import open_with_default_app
from mrbot_app.windows import (
    ApocrifosWindow,
    AportesEnLineaWindow,
    BcraWindow,
    CcmaWindow,
    ConsultaCuitWindow,
    DeclaracionEnLineaWindow,
    GuiDescargaMC,
    HaciendaWindow,
    LiquidacionGranosWindow,
    PagoDevolucionesWindow,
    PortalIvaWindow,
    ProcesarPemWindow,
    MisFacilidadesWindow,
    RcelWindow,
    MisRetencionesWindow,
    SifereWindow,
    SctWindow,
    SrtAlicuotasWindow,
    WebservicesWindow,
    ControlMonotributistasWindow,
    UsuarioWindow,
    RetPerProvincialesWindow,
)
from mrbot_app.windows.base import ConfigPane


class MainMenu(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Herramientas API Mr Bot")
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass
        self.configure(background=BG)
        self.resizable(False, False)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TButton", foreground="#000000")
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.configure("TProgressbar", troughcolor="#1e1e1e", background=ACCENT)

        self.example_paths = ensure_example_excels()

        header = ttk.Frame(self, padding=10)
        header.pack(fill="x")
        logo_path = os.path.join("bin", "MrBot.png")
        self.logo_img = None
        if os.path.exists(logo_path):
            try:
                self.logo_img = tk.PhotoImage(file=logo_path)
                tk.Label(header, image=self.logo_img, background=BG).pack(side="top", pady=(0, 8))
            except Exception:
                self.logo_img = None
        title_lbl = ttk.Label(header, text="MR BOT - Cliente API", font=("Arial", 16, "bold"), foreground=FG, background=BG)
        title_lbl.pack(anchor="center")
        subtitle = ttk.Label(header, text="Consultas y descargas de la API api-bots.mrbot.com.ar", foreground=FG, background=BG)
        subtitle.pack(anchor="center")

        self.config_pane = ConfigPane(self)
        self.config_pane.pack(fill="x", padx=10, pady=6)

        btn_width = 22

        btns = ttk.Frame(self, padding=10)
        btns.pack(fill="both", expand=True)

        ttk.Button(btns, text="Editar .env", width=btn_width, command=self.open_env_file).grid(
            row=0, column=0, padx=4, pady=(4, 10), sticky="nsew"
        )
        ttk.Button(btns, text="Recargar .env", width=btn_width, command=self.reload_env_values).grid(
            row=0, column=1, padx=4, pady=(4, 10), sticky="nsew"
        )
        ttk.Button(btns, text="Usuarios", width=btn_width, command=self.open_usuario).grid(
            row=0, column=2, padx=4, pady=(4, 10), sticky="nsew"
        )

        ttk.Button(btns, text="Descarga Mis Comprobantes", width=btn_width, command=self.open_mis_comprobantes).grid(
            row=1, column=0, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="SCT", width=btn_width, command=self.open_sct).grid(
            row=1, column=1, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="CCMA", width=btn_width, command=self.open_ccma).grid(
            row=1, column=2, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Portal IVA", width=btn_width, command=self.open_portal_iva).grid(
            row=1, column=3, padx=4, pady=4, sticky="nsew"
        )

        ttk.Button(btns, text="RCEL", width=btn_width, command=self.open_rcel).grid(
            row=2, column=0, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Hacienda y Carne", width=btn_width, command=self.open_hacienda).grid(
            row=2, column=1, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Liquidacion de Granos", width=btn_width, command=self.open_liquidacion_granos).grid(
            row=2, column=2, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Mis Retenciones", width=btn_width, command=self.open_mis_retenciones).grid(
            row=2, column=3, padx=4, pady=4, sticky="nsew"
        )

        ttk.Button(btns, text="SIFERE", width=btn_width, command=self.open_sifere).grid(
            row=3, column=0, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Mis Facilidades", width=btn_width, command=self.open_mis_facilidades).grid(
            row=3, column=1, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="DDJJ en Linea", width=btn_width, command=self.open_declaracion_linea).grid(
            row=3, column=2, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Pago Devoluciones", width=btn_width, command=self.open_pago_devoluciones).grid(
            row=3, column=3, padx=4, pady=4, sticky="nsew"
        )

        ttk.Button(btns, text="Aportes en Linea", width=btn_width, command=self.open_aportes_linea).grid(
            row=4, column=0, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Apocrifos", width=btn_width, command=self.open_apoc).grid(
            row=4, column=1, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Consulta CUIT", width=btn_width, command=self.open_cuit).grid(
            row=4, column=2, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="SRT Alicuotas ART", width=btn_width, command=self.open_srt_alicuotas).grid(
            row=4, column=3, padx=4, pady=4, sticky="nsew"
        )

        ttk.Button(btns, text="Conversion PEM a Excel", width=btn_width, command=self.open_procesar_pem).grid(
            row=5, column=0, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Webservices", width=btn_width, command=self.open_webservices).grid(
            row=5, column=1, padx=4, pady=4, sticky="nsew"
        )

        ttk.Button(btns, text="Ret-Per Provinciales", width=btn_width, command=self.open_ret_per_provinciales).grid(
            row=6, column=0, columnspan=4, padx=4, pady=4, sticky="nsew"
        )

        ttk.Button(btns, text="Control Monotributistas", width=btn_width, command=self.open_control_monotributistas).grid(
            row=7, column=0, columnspan=2, padx=4, pady=4, sticky="nsew"
        )
        ttk.Button(btns, text="Consultas BCRA", width=btn_width, command=self.open_bcra).grid(
            row=7, column=2, columnspan=2, padx=4, pady=4, sticky="nsew"
        )

        btns.columnconfigure((0, 1, 2, 3), weight=1, uniform="menu")
        for r in range(8):
            btns.rowconfigure(r, weight=1)

    def current_config(self) -> tuple[str, str, str]:
        return self.config_pane.get_config()

    def open_env_file(self) -> None:
        env_path = os.path.abspath(ENV_FILE)
        if not os.path.exists(env_path):
            try:
                with open(env_path, "w", encoding="utf-8") as fh:
                    fh.write(
                        "# URL=https://api-bots.mrbot.com.ar/\n"
                        "# API_KEY=\n"
                        "# MAIL=\n"
                        "# NOTIFICACION_MESSAGEBOX=false\n"
                        "# WSAA_TESTING=true\n"
                        "# WSAA_SERVICE opciones: veconsumerws | wsfe\n"
                        "# WSAA_SERVICE=veconsumerws\n"
                        "# CERT_API_URL=https://api-certificados.mrbot.com.ar/\n"
                        "# CERT_API_EMAIL=\n"
                        "# CERT_API_KEY=\n"
                        "# CERT_API_CN=mrbot\n"
                        "# CERT_API_CUIT_REPRESENTANTE=\n"
                        "# AFIP_CERT_PATH=\n"
                        "# AFIP_KEY_PATH=\n"
                        "# AFIP_CERT_DIR=\n"
                    )
            except Exception as exc:
                messagebox.showerror("Error", f"No se pudo crear {env_path}: {exc}")
                return
        if not open_with_default_app(env_path):
            messagebox.showerror("Error", f"No se pudo abrir {env_path}. Edita el archivo manualmente.")

    def reload_env_values(self) -> None:
        base_url, api_key, email = self.config_pane.load_from_env()
        refreshed_windows = 0
        for widget in self.winfo_children():
            callback = getattr(widget, "on_env_reloaded", None)
            if callable(callback):
                try:
                    callback()
                    refreshed_windows += 1
                except Exception as exc:
                    messagebox.showwarning(
                        "Recargar .env",
                        f"No se pudo refrescar una ventana abierta: {exc}",
                    )

        messagebox.showinfo(
            "Configuración recargada",
            (
                f"Se recargaron valores de {os.path.abspath(ENV_FILE)}.\n\n"
                f"URL: {base_url}\nMail: {email}\n(API_KEY oculto)\n"
                f"Ventanas refrescadas: {refreshed_windows}"
            ),
        )

    def open_mis_comprobantes(self) -> None:
        GuiDescargaMC(self, self.config_pane, self.example_paths)

    def open_rcel(self) -> None:
        RcelWindow(self, self.current_config, self.example_paths)

    def open_sct(self) -> None:
        SctWindow(self, self.current_config, self.example_paths)

    def open_srt_alicuotas(self) -> None:
        SrtAlicuotasWindow(self, self.current_config, self.example_paths)

    def open_ccma(self) -> None:
        CcmaWindow(self, self.current_config, self.example_paths)

    def open_mis_retenciones(self) -> None:
        MisRetencionesWindow(self, self.current_config, self.example_paths)

    def open_sifere(self) -> None:
        SifereWindow(self, self.current_config, self.example_paths)

    def open_declaracion_linea(self) -> None:
        DeclaracionEnLineaWindow(self, self.current_config, self.example_paths)

    def open_mis_facilidades(self) -> None:
        MisFacilidadesWindow(self, self.current_config, self.example_paths)

    def open_pago_devoluciones(self) -> None:
        PagoDevolucionesWindow(self, self.current_config, self.example_paths)

    def open_portal_iva(self) -> None:
        PortalIvaWindow(self, self.current_config, self.example_paths)

    def open_aportes_linea(self) -> None:
        AportesEnLineaWindow(self, self.current_config, self.example_paths)

    def open_apoc(self) -> None:
        ApocrifosWindow(self, self.current_config, self.example_paths)

    def open_hacienda(self) -> None:
        HaciendaWindow(self, self.current_config, self.example_paths)

    def open_liquidacion_granos(self) -> None:
        LiquidacionGranosWindow(self, self.current_config, self.example_paths)

    def open_cuit(self) -> None:
        ConsultaCuitWindow(self, self.current_config, self.example_paths)

    def open_control_monotributistas(self) -> None:
        ControlMonotributistasWindow(self, self.current_config, self.example_paths)

    def open_bcra(self) -> None:
        BcraWindow(self, self.example_paths)

    def open_webservices(self) -> None:
        WebservicesWindow(self, self.current_config, self.example_paths)

    def open_procesar_pem(self) -> None:
        ProcesarPemWindow(self, self.current_config, self.example_paths)

    def open_ret_per_provinciales(self) -> None:
        RetPerProvincialesWindow(self, self.current_config, self.example_paths)

    def open_usuario(self) -> None:
        UsuarioWindow(self, self.current_config)


if __name__ == "__main__":
    app = MainMenu()
    app.mainloop()
