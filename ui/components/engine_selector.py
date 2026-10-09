"""Engine selector component for switching between Ollama and Google Gemini.
"""

from typing import Callable, List
import threading
import customtkinter as ctk
from ai.ollama_client import fetch_ollama_models, ensure_ollama_running


class EngineSelector(ctk.CTkFrame):
    """UI for selecting and configuring Ollama (Local) or Gemini 2.5 Flash (Cloud)."""

    def __init__(self, parent, on_config_change: Callable[[], None]):
        super().__init__(parent, fg_color="transparent")
        self.on_config_change = on_config_change
        self.api_key_visible = False

        # Provider switcher row
        provider_row = ctk.CTkFrame(self, fg_color="transparent")
        provider_row.pack(fill="x", pady=(2, 6))

        lbl_engine = ctk.CTkLabel(
            provider_row,
            text="KI-Engine:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
            width=130,
            anchor="w",
        )
        lbl_engine.pack(side="left")

        self.var_provider = ctk.StringVar(value="ollama")
        self.seg_provider = ctk.CTkSegmentedButton(
            provider_row,
            values=["🦙 Ollama (Lokal / Kostenlos)", "✨ Gemini 2.5 Flash (Cloud)"],
            command=self._on_provider_switched,
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            unselected_color="#27272a",
            unselected_hover_color="#3f3f46",
            height=34,
        )
        self.seg_provider.pack(side="left", padx=(0, 14))

        # Dynamic Engine Details Frame
        self.details_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.details_frame.pack(fill="x", pady=2)

        self._build_ollama_widgets()
        self._build_gemini_widgets()

    def _build_ollama_widgets(self):
        self.frame_ollama = ctk.CTkFrame(self.details_frame, fg_color="transparent")

        lbl_model = ctk.CTkLabel(
            self.frame_ollama,
            text="Lokales Modell:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
            width=130,
            anchor="w",
        )
        lbl_model.pack(side="left")

        self.var_ollama_model = ctk.StringVar(value="qwen2.5vl:latest")
        self.opt_ollama_model = ctk.CTkOptionMenu(
            self.frame_ollama,
            variable=self.var_ollama_model,
            values=["qwen2.5vl:latest", "llama3.2:1b"],
            fg_color="#27272a",
            button_color="#3f3f46",
            button_hover_color="#52525b",
            dropdown_fg_color="#27272a",
            dropdown_hover_color="#3f3f46",
            width=220,
            height=36,
            corner_radius=8,
            dynamic_resizing=False,
            command=lambda _: self.on_config_change(),
        )
        self.opt_ollama_model.pack(side="left", padx=(0, 8))

        self.btn_refresh = ctk.CTkButton(
            self.frame_ollama,
            text="🔄 Modelle laden",
            width=120,
            height=36,
            corner_radius=8,
            fg_color="#3f3f46",
            hover_color="#52525b",
            text_color="#fafafa",
            command=self.refresh_ollama_models,
        )
        self.btn_refresh.pack(side="left", padx=(0, 12))

        self.lbl_badge = ctk.CTkLabel(
            self.frame_ollama,
            text="● 100% Offline (Kein API-Key erforderlich)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#34d399",
            anchor="w",
        )
        self.lbl_badge.pack(side="left", padx=(4, 0))

    def _build_gemini_widgets(self):
        self.frame_gemini = ctk.CTkFrame(self.details_frame, fg_color="transparent")

        api_label = ctk.CTkLabel(
            self.frame_gemini,
            text="Gemini API-Key:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#e4e4e7",
            width=130,
            anchor="w",
        )
        api_label.pack(side="left")

        self.api_entry = ctk.CTkEntry(
            self.frame_gemini,
            placeholder_text="Gib deinen Google Gemini API-Key ein (z. B. AIzaSy...)",
            show="*",
            fg_color="#27272a",
            border_color="#3f3f46",
            text_color="#fafafa",
            height=36,
            corner_radius=8,
        )
        self.api_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_toggle_key = ctk.CTkButton(
            self.frame_gemini,
            text="👁️",
            width=42,
            height=36,
            corner_radius=8,
            fg_color="#27272a",
            hover_color="#3f3f46",
            text_color="#f4f4f5",
            command=self._toggle_api_visibility,
        )
        self.btn_toggle_key.pack(side="left", padx=(0, 8))

        self.btn_save_key = ctk.CTkButton(
            self.frame_gemini,
            text="💾 Key speichern",
            width=130,
            height=36,
            corner_radius=8,
            fg_color="#3f3f46",
            hover_color="#52525b",
            text_color="#fafafa",
            command=self.on_config_change,
        )
        self.btn_save_key.pack(side="left")

    def _toggle_api_visibility(self):
        if self.api_key_visible:
            self.api_entry.configure(show="*")
            self.btn_toggle_key.configure(text="👁️")
            self.api_key_visible = False
        else:
            self.api_entry.configure(show="")
            self.btn_toggle_key.configure(text="🔒")
            self.api_key_visible = True

    def _on_provider_switched(self, choice: str):
        if "Ollama" in choice:
            self.var_provider.set("ollama")
            self.frame_gemini.pack_forget()
            self.frame_ollama.pack(fill="x")
            self.refresh_ollama_models(auto_start=True)
        else:
            self.var_provider.set("gemini")
            self.frame_ollama.pack_forget()
            self.frame_gemini.pack(fill="x")
        self.on_config_change()

    def refresh_ollama_models(self, auto_start: bool = True):
        if getattr(self, "_is_refreshing_ollama", False):
            return
        self._is_refreshing_ollama = True

        top = None
        try:
            top = self.winfo_toplevel()
        except Exception:
            pass
        dispatch_fn = getattr(top, "dispatch_to_ui", None) if top else None

        def _dispatch(fn, *args, **kwargs):
            if dispatch_fn:
                dispatch_fn(fn, *args, **kwargs)
            else:
                try:
                    self.after(0, lambda: fn(*args, **kwargs))
                except Exception:
                    pass

        def worker():
            try:
                models = fetch_ollama_models()
                if not models and auto_start:
                    _dispatch(
                        self.lbl_badge.configure,
                        text="⏳ Starte lokalen Ollama-Dienst im Hintergrund...",
                        text_color="#60a5fa",
                    )
                    if ensure_ollama_running(timeout=12.0):
                        models = fetch_ollama_models()

                def apply_results(found_models):
                    if found_models:
                        self.opt_ollama_model.configure(values=found_models)
                        current = self.var_ollama_model.get()
                        if "qwen2.5vl:latest" in found_models and current not in found_models:
                            self.var_ollama_model.set("qwen2.5vl:latest")
                        elif current not in found_models:
                            self.var_ollama_model.set(found_models[0])
                        self.lbl_badge.configure(
                            text=f"● Ollama aktiv ({len(found_models)} Modell{'e' if len(found_models) != 1 else ''} gefunden)",
                            text_color="#34d399",
                        )
                    else:
                        self.lbl_badge.configure(
                            text="⚠️ Ollama nicht erreichbar. Läuft die Ollama-App?",
                            text_color="#f87171",
                        )

                _dispatch(apply_results, models)
            finally:
                self._is_refreshing_ollama = False

        threading.Thread(target=worker, daemon=True).start()

    def get_provider(self) -> str:
        return self.var_provider.get()

    def get_ollama_model(self) -> str:
        return self.var_ollama_model.get()

    def get_api_key(self) -> str:
        return self.api_entry.get().strip()

    def set_config(self, provider: str, ollama_model: str, api_key: str):
        if api_key:
            self.api_entry.delete(0, "end")
            self.api_entry.insert(0, api_key)

        if provider == "gemini":
            self.seg_provider.set("✨ Gemini 2.5 Flash (Cloud)")
            self._on_provider_switched("Gemini")
        else:
            self.seg_provider.set("🦙 Ollama (Lokal / Kostenlos)")
            self._on_provider_switched("Ollama")

        if ollama_model:
            self.var_ollama_model.set(ollama_model)
