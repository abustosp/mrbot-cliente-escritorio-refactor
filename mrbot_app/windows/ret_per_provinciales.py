import os
from typing import Any, Dict, Optional

import tkinter as tk
from tkinter import ttk, messagebox

from mrbot_app.constants import BG, FG
from mrbot_app.windows.base import BaseWindow
from mrbot_app.windows.ret_per_provinciales_arba import RetPerArbaWindow
from mrbot_app.windows.ret_per_provinciales_agip import RetPerAgipWindow
from mrbot_app.windows.ret_per_provinciales_misiones import RetPerMisionesWindow


class RetPerProvincialesWindow(BaseWindow):
    MODULE_DIR = "ret_per_provinciales"

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Retenciones/Percepciones Provinciales", config_provider=config_provider)
        self.config_provider = config_provider
        self.example_paths = example_paths or {}

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)
        self.add_section_label(container, "Modulo Ret-Per Provinciales")
        self.add_info_label(
            container,
            "Seleccione la provincia para descargar retenciones y percepciones de Ingresos Brutos.",
        )

        btn_width = 30
        btn_frame = ttk.Frame(container)
        btn_frame.pack(expand=True, pady=20)

        ttk.Button(
            btn_frame, text="ARBA (Provincia de Buenos Aires)", width=btn_width,
            command=self.open_arba,
        ).pack(pady=6)

        ttk.Button(
            btn_frame, text="AGIP (CABA)", width=btn_width,
            command=self.open_agip,
        ).pack(pady=6)

        ttk.Button(
            btn_frame, text="Misiones (DGR Misiones)", width=btn_width,
            command=self.open_misiones,
        ).pack(pady=6)

        ttk.Button(
            container, text="Cerrar", command=self.destroy,
        ).pack(pady=10)

        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event=None) -> None:
        if event and event.widget is not self:
            return
        pass

    def open_arba(self) -> None:
        RetPerArbaWindow(self, self.config_provider, self.example_paths)

    def open_agip(self) -> None:
        RetPerAgipWindow(self, self.config_provider, self.example_paths)

    def open_misiones(self) -> None:
        RetPerMisionesWindow(self, self.config_provider, self.example_paths)
