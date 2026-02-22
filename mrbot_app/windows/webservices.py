import json
import os
import re
import webbrowser
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from mrbot_app.helpers import get_unique_filename, parse_bool_cell
from mrbot_app.windows.base import BaseWindow
from mrbot_app.wsaa import DEFAULT_WSAA_SERVICE, TokenSignManager


WEBSERVICE_CHOICES: List[Tuple[str, str]] = [
    ("Domicilio Fiscal Electrónico (DFE)", "veconsumerws"),
    ("Facturación electrónica", "wsfe"),
]
SERVICE_WEB_URLS: Dict[str, str] = {
    "veconsumerws": "https://e-ventanilla.mrbot.com.ar/",
    "wsfe": "https://facturador-web.mrbot.com.ar/",
}


class WebservicesWindow(BaseWindow):
    """
    Ventana para generar token/sign de webservices AFIP/ARCA
    usando api-certificados.
    """

    def __init__(self, master=None, config_provider=None, example_paths: Optional[Dict[str, str]] = None):
        super().__init__(master, title="Webservices (Token/Sign)", config_provider=config_provider)
        self.geometry("1120x760")
        self.resizable(True, True)
        try:
            self.iconbitmap(os.path.join("bin", "ABP-blanco-en-fondo-negro.ico"))
        except Exception:
            pass

        self.example_paths = example_paths or {}
        self.token_manager = TokenSignManager()
        self.last_token_sign_response: Optional[Dict[str, Any]] = None

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.add_section_label(container, "Webservices AFIP/ARCA")
        self.add_info_label(
            container,
            "Genera Token/Sign en forma automática usando https://api-certificados.mrbot.com.ar/. "
            "Selecciona el webservice destino para obtener credenciales compatibles.",
        )

        cert_api_frame = ttk.LabelFrame(container, text="API de certificados")
        cert_api_frame.pack(fill="x", pady=(2, 4))

        self.cert_api_url_var = tk.StringVar(value=os.getenv("CERT_API_URL", "https://api-certificados.mrbot.com.ar/"))
        self.cert_api_email_var = tk.StringVar(value=os.getenv("CERT_API_EMAIL", ""))
        self.cert_api_key_var = tk.StringVar(value=os.getenv("CERT_API_KEY", ""))
        self.cert_api_cn_var = tk.StringVar(value=os.getenv("CERT_API_CN", "mrbot") or "mrbot")

        ttk.Label(cert_api_frame, text="URL API cert").grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(cert_api_frame, textvariable=self.cert_api_url_var, width=62).grid(
            row=0, column=1, padx=4, pady=2, sticky="ew"
        )
        ttk.Label(cert_api_frame, text="CN").grid(row=0, column=2, padx=4, pady=2, sticky="w")
        ttk.Entry(cert_api_frame, textvariable=self.cert_api_cn_var, width=20).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )

        ttk.Label(cert_api_frame, text="Email API cert").grid(row=1, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(cert_api_frame, textvariable=self.cert_api_email_var, width=36).grid(
            row=1, column=1, padx=4, pady=2, sticky="ew"
        )
        ttk.Label(cert_api_frame, text="API key API cert").grid(row=1, column=2, padx=4, pady=2, sticky="w")
        ttk.Entry(cert_api_frame, textvariable=self.cert_api_key_var, width=36, show="*").grid(
            row=1, column=3, padx=4, pady=2, sticky="ew"
        )

        cert_api_frame.columnconfigure(1, weight=1)
        cert_api_frame.columnconfigure(3, weight=1)

        auth_frame = ttk.LabelFrame(container, text="Datos de representación y certificados")
        auth_frame.pack(fill="x", pady=(2, 4))

        default_cuit_rep = os.getenv("CERT_API_CUIT_REPRESENTANTE", "").strip()
        self.cuit_representante_var = tk.StringVar(value=default_cuit_rep)
        self.cuit_var = tk.StringVar(value=default_cuit_rep)
        self.testing_var = tk.BooleanVar(value=bool(parse_bool_cell(os.getenv("WSAA_TESTING", "false"), default=False)))
        self.force_refresh_var = tk.BooleanVar(value=False)

        self.cert_path_var = tk.StringVar(value=os.getenv("AFIP_CERT_PATH", ""))
        self.key_path_var = tk.StringVar(value=os.getenv("AFIP_KEY_PATH", ""))

        self.token_var = tk.StringVar()
        self.sign_var = tk.StringVar()
        self._service_label_to_id = {label: service_id for label, service_id in WEBSERVICE_CHOICES}
        self._service_id_to_label = {service_id: label for label, service_id in WEBSERVICE_CHOICES}
        env_service = str(os.getenv("WSAA_SERVICE", DEFAULT_WSAA_SERVICE or "veconsumerws") or "").strip().lower()
        self.default_service_id = env_service if env_service in self._service_id_to_label else "veconsumerws"
        self.service_label_var = tk.StringVar(value=self._service_id_to_label[self.default_service_id])

        ttk.Label(auth_frame, text="CUIT representada *").grid(row=0, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(auth_frame, textvariable=self.cuit_var, width=22).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        ttk.Label(auth_frame, text="CUIT representante").grid(row=0, column=2, padx=4, pady=2, sticky="w")
        ttk.Entry(auth_frame, textvariable=self.cuit_representante_var, width=22).grid(
            row=0, column=3, padx=4, pady=2, sticky="ew"
        )

        ttk.Checkbutton(auth_frame, text="Testing (homologación)", variable=self.testing_var).grid(
            row=1, column=0, padx=4, pady=2, sticky="w"
        )
        ttk.Checkbutton(auth_frame, text="Forzar renovación token", variable=self.force_refresh_var).grid(
            row=1, column=1, padx=4, pady=2, sticky="w"
        )
        ttk.Label(auth_frame, text="Webservice").grid(row=1, column=2, padx=4, pady=2, sticky="w")
        ttk.Combobox(
            auth_frame,
            textvariable=self.service_label_var,
            values=[label for label, _service_id in WEBSERVICE_CHOICES],
            state="readonly",
            width=32,
        ).grid(row=1, column=3, padx=4, pady=2, sticky="ew")

        ttk.Label(auth_frame, text="Certificado PEM/CRT").grid(row=3, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(auth_frame, textvariable=self.cert_path_var, width=62).grid(
            row=3, column=1, columnspan=2, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(auth_frame, text="Seleccionar...", command=self.seleccionar_certificado).grid(
            row=3, column=3, padx=4, pady=2, sticky="ew"
        )

        ttk.Label(auth_frame, text="Clave privada PEM/KEY").grid(row=4, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(auth_frame, textvariable=self.key_path_var, width=62).grid(
            row=4, column=1, columnspan=2, padx=4, pady=2, sticky="ew"
        )
        ttk.Button(auth_frame, text="Seleccionar...", command=self.seleccionar_llave_privada).grid(
            row=4, column=3, padx=4, pady=2, sticky="ew"
        )

        ttk.Button(auth_frame, text="Obtener token/sign", command=self.obtener_token_sign).grid(
            row=5, column=0, columnspan=4, padx=4, pady=(4, 2), sticky="ew"
        )

        ttk.Label(auth_frame, text="Token").grid(row=6, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(auth_frame, textvariable=self.token_var, width=72).grid(
            row=6, column=1, columnspan=3, padx=4, pady=2, sticky="ew"
        )

        ttk.Label(auth_frame, text="Sign").grid(row=7, column=0, padx=4, pady=2, sticky="w")
        ttk.Entry(auth_frame, textvariable=self.sign_var, width=72).grid(
            row=7, column=1, columnspan=3, padx=4, pady=2, sticky="ew"
        )

        auth_frame.columnconfigure(1, weight=1)
        auth_frame.columnconfigure(3, weight=1)

        actions_frame = ttk.Frame(container)
        actions_frame.pack(fill="x", pady=(2, 4))
        ttk.Button(
            actions_frame,
            text="Abrir servicio web",
            command=self.abrir_servicio_web,
        ).grid(row=0, column=0, padx=4, pady=2, sticky="ew")
        ttk.Button(
            actions_frame,
            text="Guardar token y sign",
            command=self.guardar_token_sign_json,
        ).grid(row=0, column=1, padx=4, pady=2, sticky="ew")
        actions_frame.columnconfigure((0, 1), weight=1)

        self.result_box = self.add_preview(container, height=14)
        self.set_preview(
            self.result_box,
            "Selecciona el webservice y genera token/sign.\n"
            "Luego usa 'Abrir servicio web' para abrir la aplicación correspondiente.",
        )

        self.progress_frame = self.add_progress_bar(container, label="Estado")
        self.log_text = self.add_collapsible_log(container, title="Logs de ejecución", height=10, service="webservices")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _sanitize_identifier(self, value: str, fallback: str = "desconocido") -> str:
        cleaned = re.sub(r"[^0-9A-Za-z._-]", "_", (value or "").strip())
        cleaned = cleaned.strip("_")
        return cleaned or fallback

    def _has_valid_last_token_sign(self) -> bool:
        data = self.last_token_sign_response
        if not isinstance(data, dict):
            return False
        if not bool(data.get("success")):
            return False
        token = str(data.get("token") or "").strip()
        sign = str(data.get("sign") or "").strip()
        return bool(token and sign)

    def _persist_last_token_sign_json(self) -> Dict[str, Any]:
        if not isinstance(self.last_token_sign_response, dict):
            return {
                "success": False,
                "message": "No hay respuesta de token/sign para guardar.",
            }

        response_body = self.last_token_sign_response.get("response_body")
        if response_body is None:
            response_body = self.last_token_sign_response.get("raw_response")
        if response_body is None:
            nested_response = self.last_token_sign_response.get("response")
            if isinstance(nested_response, dict):
                response_body = nested_response.get("raw_response")
        if response_body is None:
            return {
                "success": False,
                "message": "No hay body de response disponible para guardar. Vuelve a obtener token/sign.",
            }

        cuit_repr = str(self.last_token_sign_response.get("cuit_representada") or "sin_cuit").strip()
        service_id = self._sanitize_identifier(str(self.last_token_sign_response.get("service") or "servicio"), "servicio")
        target_dir = os.path.join("descargas", "webservices", service_id, self._sanitize_identifier(cuit_repr, "sin_cuit"))
        try:
            os.makedirs(target_dir, exist_ok=True)
            base_name = (
                f"token_sign_{service_id}_{self._sanitize_identifier(cuit_repr)}_"
                f"{datetime.now().strftime('%Y%m%d-%H_%M_%S')}.json"
            )
            filename = get_unique_filename(target_dir, base_name)
            out_path = os.path.join(target_dir, filename)
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(response_body, fh, ensure_ascii=False, indent=2, default=str)
            return {
                "success": True,
                "path": out_path,
            }
        except Exception as exc:
            return {
                "success": False,
                "message": str(exc),
            }

    def guardar_token_sign_json(self) -> None:
        if self._has_valid_last_token_sign():
            save_result = self._persist_last_token_sign_json()
            if not save_result.get("success"):
                message = save_result.get("message") or "No se pudo guardar el JSON."
                self.log_error(f"No se pudo guardar token/sign en JSON: {message}")
                messagebox.showerror("Guardar", f"No se pudo guardar el JSON: {message}")
                return
            out_path = str(save_result.get("path") or "").strip()
            self.log_info(f"Token/sign guardados en JSON: {out_path}")
            messagebox.showinfo("Guardar", f"Archivo JSON generado:\n{out_path}")
            return

        defaults = self._collect_defaults()
        if not defaults["cuit_representada"]:
            messagebox.showerror("Guardar", "No hay token/sign y falta CUIT representada para obtenerlos.")
            return

        self.clear_logs()
        self.log_start(
            "Webservices",
            {
                "modo": "guardar_token_sign_json",
                "cuit_representada": defaults["cuit_representada"],
                "service": defaults["service"],
            },
        )
        self.run_in_thread(self._worker_guardar_token_sign_json, defaults)

    def _worker_guardar_token_sign_json(self, defaults: Dict[str, Any]) -> None:
        self.log_info("No hay token/sign vigentes en memoria. Intentando obtenerlos automáticamente...")
        self._worker_obtener_token_sign(defaults)

        if not self._has_valid_last_token_sign():
            message = "No se pudo obtener token/sign automáticamente. Revisa credenciales y certificados."
            self.log_error(message)
            self.after(0, lambda: messagebox.showerror("Guardar", message))
            return

        save_result = self._persist_last_token_sign_json()
        if not save_result.get("success"):
            message = save_result.get("message") or "No se pudo guardar el JSON."
            self.log_error(f"No se pudo guardar token/sign en JSON: {message}")
            self.after(0, lambda: messagebox.showerror("Guardar", f"No se pudo guardar el JSON: {message}"))
            return

        out_path = str(save_result.get("path") or "").strip()
        self.log_info(f"Token/sign guardados en JSON: {out_path}")
        self.after(0, lambda: messagebox.showinfo("Guardar", f"Archivo JSON generado:\n{out_path}"))

    def abrir_servicio_web(self) -> None:
        service_id = self._selected_service_id()
        service_label = self.service_label_var.get().strip() or service_id
        portal_url = SERVICE_WEB_URLS.get(service_id, "").strip()
        if not portal_url:
            messagebox.showerror(
                "Abrir servicio web",
                f"No hay URL configurada para {service_label} ({service_id}).",
            )
            return
        try:
            opened = webbrowser.open(portal_url, new=2)
            if not opened:
                raise RuntimeError("No fue posible abrir el navegador automáticamente.")
            self.log_info(f"Servicio web abierto ({service_id}): {portal_url}")
        except Exception as exc:
            messagebox.showerror(
                "Abrir servicio web",
                f"No se pudo abrir el navegador: {exc}\n\nAccede manualmente a:\n{portal_url}",
            )

    def _seleccionar_archivo(
        self,
        variable: tk.StringVar,
        title: str,
        filetypes: List[Tuple[str, str]],
    ) -> None:
        path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        self.bring_to_front()
        if not path:
            return
        variable.set(path)

    def seleccionar_certificado(self) -> None:
        self._seleccionar_archivo(
            self.cert_path_var,
            "Seleccionar certificado",
            [
                ("Certificados", "*.crt *.cer *.pem"),
                ("Todos", "*.*"),
            ],
        )

    def seleccionar_llave_privada(self) -> None:
        self._seleccionar_archivo(
            self.key_path_var,
            "Seleccionar llave privada",
            [
                ("Llaves privadas", "*.key *.pem"),
                ("Todos", "*.*"),
            ],
        )

    def _selected_service_id(self) -> str:
        label = self.service_label_var.get().strip()
        return self._service_label_to_id.get(label, self.default_service_id)

    def _collect_defaults(self) -> Dict[str, Any]:
        _base_url, api_key, email = self._get_config()
        cert_api_email = self.cert_api_email_var.get().strip() or os.getenv("CERT_API_EMAIL", "").strip() or email
        cert_api_key = self.cert_api_key_var.get().strip() or os.getenv("CERT_API_KEY", "").strip() or api_key

        return {
            "cuit_representada": self.cuit_var.get().strip(),
            "cuit_representante": self.cuit_representante_var.get().strip(),
            "testing": bool(self.testing_var.get()),
            "force_refresh": bool(self.force_refresh_var.get()),
            "cert_api_url": self.cert_api_url_var.get().strip() or os.getenv("CERT_API_URL", "").strip(),
            "cert_api_email": cert_api_email,
            "cert_api_key": cert_api_key,
            "cert_api_cn": self.cert_api_cn_var.get().strip() or os.getenv("CERT_API_CN", "mrbot").strip() or "mrbot",
            "service": self._selected_service_id(),
            "service_label": self.service_label_var.get().strip(),
            "cert_path": self.cert_path_var.get().strip(),
            "key_path": self.key_path_var.get().strip(),
        }

    def obtener_token_sign(self) -> None:
        defaults = self._collect_defaults()
        if not defaults["cuit_representada"]:
            messagebox.showerror("CUIT requerido", "Ingresa el CUIT representado para obtener token/sign.")
            return

        self.clear_logs()
        self.log_start(
            "Webservices",
            {
                "modo": "obtener_token_sign",
                "cuit_representada": defaults["cuit_representada"],
                "service": defaults["service"],
            },
        )
        self.run_in_thread(self._worker_obtener_token_sign, defaults)

    def _set_token_sign(self, token: str, sign: str) -> None:
        def _update() -> None:
            self.token_var.set(token or "")
            self.sign_var.set(sign or "")

        self.after(0, _update)

    def _worker_obtener_token_sign(self, defaults: Dict[str, Any]) -> None:
        cuit_representante = defaults["cuit_representante"] or defaults["cuit_representada"]

        result = self.token_manager.get_token_sign(
            cuit_representada=defaults["cuit_representada"],
            cuit_representante=cuit_representante,
            service=defaults["service"],
            testing=defaults["testing"],
            cert_path=defaults["cert_path"],
            key_path=defaults["key_path"],
            force_refresh=defaults["force_refresh"],
            cert_api_url=defaults["cert_api_url"],
            cert_api_email=defaults["cert_api_email"],
            cert_api_key=defaults["cert_api_key"],
            cert_api_cn=defaults["cert_api_cn"],
        )

        if not result.get("success"):
            message = result.get("message") or "No se pudo obtener token/sign."
            self.log_error(message)
            self.last_token_sign_response = {
                "success": False,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "service": defaults["service"],
                "cuit_representada": defaults["cuit_representada"],
                "cuit_representante": cuit_representante,
                "response": result,
            }
            self.set_preview(self.result_box, json.dumps(result, ensure_ascii=False, indent=2, default=str))
            return

        token = str(result.get("token") or "").strip()
        sign = str(result.get("sign") or "").strip()
        self._set_token_sign(token, sign)

        expiration = result.get("expiration_time_raw") or "N/D"
        source = result.get("source") or "api_certificados"
        self.log_info(f"Token/sign listos (source={source}, vencimiento={expiration}).")

        self.last_token_sign_response = {
            "success": True,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "service": defaults["service"],
            "cuit_representada": defaults["cuit_representada"],
            "cuit_representante": result.get("cuit_representante") or cuit_representante,
            "token": token,
            "sign": sign,
            "response_body": result.get("raw_response"),
        }

        out = {
            "success": True,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "cached": bool(result.get("cached", False)),
            "service": defaults["service"],
            "cuit_representada": defaults["cuit_representada"],
            "cuit_representante": result.get("cuit_representante") or cuit_representante,
            "expiration_time": expiration,
            "api_url": result.get("api_url") or defaults["cert_api_url"],
            "cert_path": result.get("cert_path"),
            "key_path": result.get("key_path"),
            "token_len": len(token),
            "sign_len": len(sign),
        }
        self.set_preview(self.result_box, json.dumps(out, ensure_ascii=False, indent=2, default=str))
