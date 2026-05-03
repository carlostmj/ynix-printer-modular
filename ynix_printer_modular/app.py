from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import math
import hashlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tkinter import colorchooser, filedialog, font as tkfont, messagebox, ttk
import tkinter as tk
from urllib.parse import unquote, urlparse

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

from .edit_history import EditHistory
from .geometry import mm_to_px, px_to_mm
from .imaging import RenderSettings, fit_image, fit_image_with_meta, open_mono
from .installer import DEFAULT_TOMATE_NAME
from .print_queue import PrintJob, PrintQueue
from .printers import DEFAULT_CONTRACT, contract_by_display_name, contract_names, list_printers
from .profiles import LabelProfile, all_profiles, delete_custom_profile, get_profile, is_builtin_profile, profile_names, save_custom_profile
from .quality import get_quality, quality_names
from .tspl import build_tspl
from .config.settings import AppSettings, load_settings, save_settings
from .core.element_modules import ModuleField, module_for_overlay
from .core.overlays import duplicate_overlay, normalize_overlay, reorder
from .core.qrcode_renderer import normalize_qr_fill, render_qrcode_layer
from .domain.layer import Layer
from .domain.models import CanvasSpec, PrintConfig
from .domain.project import YnixProject
from .storage.project_serializer import load_project, save_project
from .ui.context_menu import LayerContextMenu
from .ui.left_toolbar import LeftToolbar
from .ui.right_panel import LayerList
from .utils.logger import get_logger


SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
SUPPORTED_FILES = "*.pdf *.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_ICON = PROJECT_ROOT / "assets" / "icone.png"


def normalize_input_path(value: str | Path) -> Path:
    text = str(value).strip()
    if text.startswith("file://"):
        parsed = urlparse(text)
        return Path(unquote(parsed.path))
    return Path(text)


class ScrollableSidebarPage(ttk.Frame):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, style="App.TFrame")
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background="#f1f3f4")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=10, style="App.TFrame")
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._fit_inner_width)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self.inner.bind("<Enter>", self._bind_mousewheel)
        self.inner.bind("<Leave>", self._unbind_mousewheel)

    def _update_scroll_region(self, _event: tk.Event | None = None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_inner_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _bind_mousewheel(self, _event: tk.Event | None = None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event | None = None) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        bbox = self.canvas.bbox("all")
        if not bbox or bbox[3] <= self.canvas.winfo_height():
            return
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 * int(event.delta / 120)
        self.canvas.yview_scroll(delta, "units")


class ThermalLabelApp:
    def __init__(self, root: tk.Tk, files):
        self.root = root
        self.root.title("Ynix Printer Modular")
        self.root.geometry("1240x800")
        self.app_icon_tk = None
        self._set_window_icon()
        self.app_settings: AppSettings = load_settings()
        self.logger = get_logger("app")
        self.project_path: Path | None = None

        self.printer_name = tk.StringVar(value="Tomate_MDK_007")
        self.output_mode = tk.StringVar(value="Térmica TSPL")
        self.print_quality = tk.StringVar(value="Normal")
        self.profile_name = tk.StringVar(value="10x15")
        self.dpi = tk.IntVar(value=203)
        self.size_unit = tk.StringVar(value="mm")
        self.size_width = tk.DoubleVar(value=100.0)
        self.size_height = tk.DoubleVar(value=150.0)
        self.calculated_px = tk.StringVar(value="")
        self.status_message = tk.StringVar(value="Pronto")
        self.active_tool = tk.StringVar(value="select")
        self.snap_enabled = tk.BooleanVar(value=bool(self.app_settings.preferences.get("snap_enabled", False)))
        self.grid_size = tk.IntVar(value=int(self.app_settings.preferences.get("grid_size", 16)))
        self.layer_x = tk.DoubleVar(value=0)
        self.layer_y = tk.DoubleVar(value=0)
        self.layer_w = tk.DoubleVar(value=0)
        self.layer_h = tk.DoubleVar(value=0)
        self.layer_rotation = tk.DoubleVar(value=0)
        self.layer_font_family = tk.StringVar(value="DejaVu Sans")
        self.layer_font_size = tk.IntVar(value=28)
        self.layer_bold = tk.BooleanVar(value=False)
        self.layer_italic = tk.BooleanVar(value=False)
        self.layer_color = tk.StringVar(value="#000000")
        self.layer_fill_color = tk.StringVar(value="none")
        self.layer_stroke_color = tk.StringVar(value="#000000")
        self.layer_line_width = tk.IntVar(value=3)
        self.layer_align = tk.StringVar(value="left")
        self.layer_text = tk.StringVar(value="")
        self.module_field_vars: dict[str, tk.Variable] = {}
        self.module_field_specs: dict[str, ModuleField] = {}
        self._module_panel_key: tuple[str, str] | None = None
        self.maximized_enabled = tk.BooleanVar(value=True)
        self.layer_name = tk.StringVar(value="")
        self.layer_opacity = tk.IntVar(value=100)
        self.layer_visible = tk.BooleanVar(value=True)
        self.layer_locked = tk.BooleanVar(value=False)
        self.show_grid = tk.BooleanVar(value=bool(self.app_settings.preferences.get("show_grid", False)))
        self.show_rulers = tk.BooleanVar(value=bool(self.app_settings.preferences.get("show_rulers", True)))
        self.mouse_position = tk.StringVar(value="")
        self.zoom_percent = tk.IntVar(value=100)
        self._font_families_cache: list[str] | None = None

        self.width_mm = 100.0
        self.height_mm = 150.0
        self.margin_px = tk.IntVar(value=16)
        self.offset_x_px = tk.IntVar(value=0)
        self.offset_y_px = tk.IntVar(value=0)
        self.scale_x_percent = tk.IntVar(value=100)
        self.scale_y_percent = tk.IntVar(value=100)
        self.scale_uniform_percent = tk.IntVar(value=100)
        self.rotation_degrees = tk.IntVar(value=0)
        self.crop_left_percent = tk.IntVar(value=0)
        self.crop_right_percent = tk.IntVar(value=0)
        self.crop_top_percent = tk.IntVar(value=0)
        self.crop_bottom_percent = tk.IntVar(value=0)
        self.invert = tk.BooleanVar(value=False)
        self.auto_rotate = tk.BooleanVar(value=True)
        self.fit_mode = tk.StringVar(value="contain")
        self.page_range = tk.StringVar(value="")
        self.profile_status = tk.StringVar(value="")

        self.files = [normalize_input_path(f) for f in files if normalize_input_path(f).is_file()]
        self.project_source_files: list[Path] = list(self.files)
        self.page_sources: list[Path] = []
        self.blank_document = False
        self.current_index = 0
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ynix-printer-modular."))

        self.preview_image = None
        self.preview_tk = None
        self.preview_scale = 1.0
        self.preview_image_box = None
        self.preview_content_box = None
        self.preview_job = None
        self.syncing = False
        self.loading_page_settings = False
        self.page_adjustments: dict[int, dict[str, object]] = {}
        self.default_page_adjustment: dict[str, object] | None = None
        self.edit_history = EditHistory()
        self.history_paused = False
        self.drag_start = None
        self.resize_start = None
        self.rotate_start = None
        self.overlay_drag_start = None
        self.overlay_resize_start = None
        self.overlay_rotate_start = None
        self.edit_mode = tk.StringVar(value="Redimensionar")
        self.page_overlays: dict[int, list[dict[str, object]]] = {}
        self.selected_overlay_id: str | None = None
        self.clipboard_overlay: dict[str, object] | None = None
        self.overlay_undo_stack: list[dict[str, object]] = []
        self.overlay_redo_stack: list[dict[str, object]] = []
        self.overlay_history_paused = False
        self.next_overlay_id = 1
        self.detected_printers = list_printers()
        if self.detected_printers:
            self.printer_name.set(self.detected_printers[0])
        if self.app_settings.last_printer:
            self.printer_name.set(self.app_settings.last_printer)
        if self.app_settings.last_output_mode:
            self.output_mode.set(self.app_settings.last_output_mode)
        self.print_queue = PrintQueue(self._queue_job_changed)

        self._build_ui()
        self._maximize_window()
        self._bind_auto_preview()
        self.apply_profile("10x15", refresh=False)
        if self.files:
            self.load_files(self.files)
        else:
            self.new_blank_project()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._bind_shortcuts()

    def _set_window_icon(self) -> None:
        if not APP_ICON.exists():
            return
        try:
            self.app_icon_tk = tk.PhotoImage(file=str(APP_ICON))
            self.root.iconphoto(True, self.app_icon_tk)
        except tk.TclError:
            pass

    def _finish_dialog(self, window: tk.Toplevel, min_width: int, min_height: int) -> None:
        window.minsize(min_width, min_height)
        window.update_idletasks()
        width = max(min_width, window.winfo_reqwidth() + 24)
        height = max(min_height, window.winfo_reqheight() + 24)
        screen_w = max(width, window.winfo_screenwidth())
        screen_h = max(height, window.winfo_screenheight())
        width = min(width, screen_w - 80)
        height = min(height, screen_h - 100)
        x = max(20, (screen_w - width) // 2)
        y = max(20, (screen_h - height) // 2)
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.deiconify()
        window.lift()
        window.focus_force()

    def _maximize_window(self) -> None:
        self.maximized_enabled.set(True)
        try:
            self.root.attributes("-fullscreen", False)
        except tk.TclError:
            pass
        try:
            self.root.state("zoomed")
            return
        except tk.TclError:
            pass
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_w}x{screen_h}+0+0")

    def _build_ui(self) -> None:
        self._configure_style()
        self._build_menu()

        main = ttk.Frame(self.root, padding=12, style="App.TFrame")
        main.pack(fill="both", expand=True)

        toolbar = ttk.Frame(main, style="Toolbar.TFrame")
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="Novo projeto", style="Accent.TButton", command=self.new_blank_project).pack(side="left")
        ttk.Button(toolbar, text="Abrir arquivos", command=self.pick_files).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Abrir projeto", command=self.open_project).pack(side="left", padx=(6, 0))
        ttk.Button(toolbar, text="Salvar", command=self.save_project).pack(side="left", padx=(6, 0))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=10)
        self.undo_button = ttk.Button(toolbar, text="Desfazer", command=self.undo_edit)
        self.undo_button.pack(side="left")
        self.redo_button = ttk.Button(toolbar, text="Refazer", command=self.redo_edit)
        self.redo_button.pack(side="left", padx=(6, 10))
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=(0, 10))
        ttk.Button(toolbar, text="Anterior", command=self.prev_page).pack(side="left")
        ttk.Button(toolbar, text="Próxima", command=self.next_page).pack(side="left", padx=(6, 0))
        self.page_info = ttk.Label(toolbar, text="Página 0/0", style="Muted.TLabel")
        self.page_info.pack(side="left", padx=12)
        ttk.Button(toolbar, text="Imprimir página", style="Accent.TButton", command=self.print_current).pack(side="right")

        propertybar = ttk.Frame(main, padding=(8, 6), style="PropertyBar.TFrame")
        propertybar.pack(fill="x", pady=(0, 10))
        ttk.Label(propertybar, text="Perfil", style="Property.TLabel").pack(side="left")
        self.profile_combo = ttk.Combobox(propertybar, textvariable=self.profile_name, values=profile_names(), state="readonly", width=10)
        self.profile_combo.pack(side="left", padx=(4, 12))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_combo_select)
        ttk.Label(propertybar, text="Impressora", style="Property.TLabel").pack(side="left")
        printer_values = self.detected_printers or [self.printer_name.get()]
        self.top_printer_combo = ttk.Combobox(propertybar, textvariable=self.printer_name, values=printer_values, state="readonly", width=24)
        self.top_printer_combo.pack(side="left", padx=(4, 12), fill="x", expand=True)
        ttk.Label(propertybar, text="Tipo", style="Property.TLabel").pack(side="left")
        self.top_output_combo = ttk.Combobox(propertybar, textvariable=self.output_mode, values=["Térmica TSPL", "Impressora normal"], state="readonly", width=18)
        self.top_output_combo.pack(side="left", padx=(4, 12))
        ttk.Label(propertybar, text="Qualidade", style="Property.TLabel").pack(side="left")
        self.top_quality_combo = ttk.Combobox(propertybar, textvariable=self.print_quality, values=quality_names(), state="readonly", width=12)
        self.top_quality_combo.pack(side="left", padx=(4, 0))

        content = ttk.PanedWindow(main, orient="horizontal")
        content.pack(fill="both", expand=True)

        self.left_toolbar = LeftToolbar(content, self.active_tool, self.set_active_tool)
        content.add(self.left_toolbar, weight=0)

        preview_shell = ttk.Frame(content, padding=12, style="PreviewShell.TFrame")
        content.add(preview_shell, weight=1)
        preview_header = ttk.Frame(preview_shell, style="PreviewShell.TFrame")
        preview_header.pack(fill="x", pady=(0, 8))
        ttk.Label(preview_header, text="Preview da etiqueta", style="PreviewTitle.TLabel").pack(side="left")
        ttk.Label(preview_header, textvariable=self.calculated_px, style="PreviewPill.TLabel").pack(side="right")

        preview_frame = ttk.Frame(preview_shell, padding=10, style="PreviewCanvas.TFrame")
        preview_frame.pack(fill="both", expand=True)
        self.preview_canvas = tk.Canvas(preview_frame, background="#2b2b2b", highlightthickness=0, borderwidth=0)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_canvas.bind("<ButtonPress-1>", self._start_preview_action)
        self.preview_canvas.bind("<B1-Motion>", self._drag_preview_action)
        self.preview_canvas.bind("<ButtonRelease-1>", self._end_preview_action)
        self.preview_canvas.bind("<Double-Button-1>", self._handle_preview_double_click)
        self.preview_canvas.bind("<Button-3>", self._show_context_menu)
        self.preview_canvas.bind("<Motion>", self._update_preview_cursor)
        self.preview_canvas.bind("<MouseWheel>", self._on_canvas_zoom)
        preview_frame.bind("<Configure>", lambda _event: self.schedule_preview())
        self._enable_file_drop(preview_frame)
        self._enable_file_drop(self.preview_canvas)

        right = ttk.Frame(content, width=470, padding=(12, 0, 0, 0), style="App.TFrame")
        right.pack_propagate(False)
        content.add(right, weight=0)

        tabbar = ttk.Frame(right, style="App.TFrame")
        tabbar.pack(fill="x", pady=(0, 8))
        pages = ttk.Frame(right, style="App.TFrame")
        pages.pack(fill="both", expand=True)
        self.sidebar_pages = {
            "Camadas": ScrollableSidebarPage(pages),
            "Perfis": ScrollableSidebarPage(pages),
            "Ajustes": ScrollableSidebarPage(pages),
            "Impressão": ScrollableSidebarPage(pages),
            "Fila": ScrollableSidebarPage(pages),
        }
        self.sidebar_tab_buttons = {}
        tab_rows = (("Camadas", "Perfis", "Ajustes"), ("Impressão", "Fila"))
        for row_index, tab_names in enumerate(tab_rows):
            row_frame = ttk.Frame(tabbar, style="App.TFrame")
            row_frame.pack(fill="x", pady=(0, 4 if row_index == 0 else 0))
            for column_index, tab_name in enumerate(tab_names):
                button = ttk.Button(row_frame, text=tab_name, style="Tab.TButton", command=lambda name=tab_name: self._show_sidebar_tab(name))
                button.grid(row=0, column=column_index, sticky="ew", padx=(0 if column_index == 0 else 4, 0))
                row_frame.columnconfigure(column_index, weight=1, uniform=f"tabs-{row_index}")
                self.sidebar_tab_buttons[tab_name] = button

        layers_tab = self.sidebar_pages["Camadas"].inner
        profiles_tab = self.sidebar_pages["Perfis"].inner
        setup_tab = self.sidebar_pages["Ajustes"].inner
        print_tab = self.sidebar_pages["Impressão"].inner
        queue_tab = self.sidebar_pages["Fila"].inner

        self._build_layers_panel(layers_tab)

        ttk.Label(profiles_tab, text="Perfis de papel", style="Title.TLabel").pack(anchor="w")
        ttk.Label(profiles_tab, text="Escolha o tamanho base do trabalho.", style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        self.profile_tree = ttk.Treeview(
            profiles_tab,
            columns=("size", "dpi"),
            show="tree headings",
            height=7,
        )
        self.profile_tree.heading("#0", text="Perfil")
        self.profile_tree.heading("size", text="Tamanho")
        self.profile_tree.heading("dpi", text="DPI / Tipo")
        self.profile_tree.column("#0", width=70, stretch=False)
        self.profile_tree.column("size", width=160, stretch=True)
        self.profile_tree.column("dpi", width=96, stretch=False, anchor="center")
        self.profile_tree.pack(fill="x")
        self._refresh_profile_controls("10x15")
        self.profile_tree.bind("<<TreeviewSelect>>", self._on_profile_select)

        measure_box = ttk.LabelFrame(profiles_tab, text="Medidas", padding=10)
        measure_box.pack(fill="x", pady=(12, 0))
        measure_row = 0

        ttk.Label(measure_box, text="DPI real").grid(row=measure_row, column=0, sticky="w", pady=4)
        ttk.Spinbox(measure_box, from_=150, to=600, increment=1, textvariable=self.dpi, width=10).grid(row=measure_row, column=1, sticky="w", pady=4)
        measure_row += 1

        ttk.Label(measure_box, text="Unidade").grid(row=measure_row, column=0, sticky="w", pady=4)
        self.unit_cb = ttk.Combobox(measure_box, textvariable=self.size_unit, values=["px", "mm", "cm"], state="readonly")
        self.unit_cb.grid(row=measure_row, column=1, sticky="ew", pady=4)
        measure_row += 1

        self.size1_label = ttk.Label(measure_box, text="Largura (mm)")
        self.size1_label.grid(row=measure_row, column=0, sticky="w", pady=4)
        self.size1_spin = ttk.Spinbox(measure_box, width=12, textvariable=self.size_width)
        self.size1_spin.grid(row=measure_row, column=1, sticky="w", pady=4)
        measure_row += 1

        self.size2_label = ttk.Label(measure_box, text="Altura (mm)")
        self.size2_label.grid(row=measure_row, column=0, sticky="w", pady=4)
        self.size2_spin = ttk.Spinbox(measure_box, width=12, textvariable=self.size_height)
        self.size2_spin.grid(row=measure_row, column=1, sticky="w", pady=4)
        measure_row += 1

        ttk.Label(measure_box, text="Margem (px)").grid(row=measure_row, column=0, sticky="w", pady=4)
        ttk.Spinbox(measure_box, from_=0, to=250, increment=1, textvariable=self.margin_px, width=10).grid(row=measure_row, column=1, sticky="w", pady=4)
        measure_row += 1

        ttk.Label(measure_box, text="Bitmap").grid(row=measure_row, column=0, sticky="w", pady=4)
        ttk.Label(measure_box, textvariable=self.calculated_px, style="Value.TLabel").grid(row=measure_row, column=1, sticky="w", pady=4)
        measure_box.columnconfigure(1, weight=1)

        profile_actions = ttk.Frame(profiles_tab, style="App.TFrame")
        profile_actions.pack(fill="x", pady=(12, 0))
        ttk.Button(profile_actions, text="Novo perfil...", command=self.open_profile_window).pack(side="left", fill="x", expand=True)
        ttk.Button(profile_actions, text="Excluir salvo", command=self.delete_selected_profile).pack(side="left", fill="x", expand=True, padx=(8, 0))
        ttk.Label(profiles_tab, textvariable=self.profile_status, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        grid = ttk.Frame(setup_tab)
        grid.pack(fill="x")
        row = 0

        ttk.Label(grid, text="Offset X (px)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=-500, to=500, increment=1, textvariable=self.offset_x_px, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Offset Y (px)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=-500, to=500, increment=1, textvariable=self.offset_y_px, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Ajuste").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(grid, textvariable=self.fit_mode, values=["contain", "cover"], state="readonly").grid(row=row, column=1, sticky="ew", pady=4)
        row += 1

        ttk.Separator(grid).grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1

        ttk.Label(grid, text="Escala horizontal (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=10, to=300, increment=1, textvariable=self.scale_x_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Escala vertical (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=10, to=300, increment=1, textvariable=self.scale_y_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Escala diagonal (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=10, to=300, increment=1, textvariable=self.scale_uniform_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Button(grid, text="Redefinir escala", command=self.reset_scale).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        row += 1

        ttk.Label(grid, text="Rotação (°)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=-180, to=180, increment=1, textvariable=self.rotation_degrees, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Modo do preview").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Label(grid, textvariable=self.edit_mode, style="Value.TLabel").grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Separator(grid).grid(row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1

        ttk.Label(grid, text="Corte esq. (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=0, to=95, increment=1, textvariable=self.crop_left_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Corte dir. (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=0, to=95, increment=1, textvariable=self.crop_right_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Corte topo (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=0, to=95, increment=1, textvariable=self.crop_top_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Label(grid, text="Corte baixo (%)").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Spinbox(grid, from_=0, to=95, increment=1, textvariable=self.crop_bottom_percent, width=10).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

        ttk.Button(grid, text="Limpar corte", command=self.reset_crop).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        row += 1

        ttk.Checkbutton(grid, text="Auto-rotação", variable=self.auto_rotate).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 2))
        row += 1
        ttk.Checkbutton(grid, text="Inverter cores na impressão", variable=self.invert).grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        row += 1

        grid.columnconfigure(1, weight=1)

        ttk.Label(print_tab, text="Envio para impressora", style="Title.TLabel").pack(anchor="w")
        ttk.Label(print_tab, text="Use os controles do topo para perfil, impressora, tipo e qualidade.", style="Muted.TLabel").pack(anchor="w", pady=(2, 12))
        print_summary = ttk.LabelFrame(print_tab, text="Configuração atual", padding=10)
        print_summary.pack(fill="x", pady=(0, 12))
        ttk.Label(print_summary, text="Impressora").grid(row=0, column=0, sticky="w")
        ttk.Label(print_summary, textvariable=self.printer_name, style="Value.TLabel").grid(row=0, column=1, sticky="e")
        ttk.Label(print_summary, text="Tipo").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(print_summary, textvariable=self.output_mode, style="Value.TLabel").grid(row=1, column=1, sticky="e", pady=(6, 0))
        ttk.Label(print_summary, text="Qualidade").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(print_summary, textvariable=self.print_quality, style="Value.TLabel").grid(row=2, column=1, sticky="e", pady=(6, 0))
        print_summary.columnconfigure(1, weight=1)
        ttk.Button(print_tab, text="Imprimir Página Atual", style="Accent.TButton", command=self.print_current).pack(fill="x")
        ttk.Button(print_tab, text="Imprimir Todas as Páginas", command=self.print_all).pack(fill="x", pady=8)
        ttk.Button(print_tab, text="Imprimir Numeração", command=self.print_counter_sequence).pack(fill="x")

        range_box = ttk.LabelFrame(print_tab, text="Faixa de páginas", padding=10)
        range_box.pack(fill="x", pady=(8, 0))
        ttk.Label(range_box, text="Exemplo: 1,3-5").pack(anchor="w")
        range_row = ttk.Frame(range_box)
        range_row.pack(fill="x", pady=(6, 0))
        ttk.Entry(range_row, textvariable=self.page_range, width=18).pack(side="left", fill="x", expand=True)
        ttk.Button(range_row, text="Imprimir", command=self.print_range).pack(side="left", padx=(8, 0))

        ttk.Label(print_tab, text="O preview é atualizado automaticamente.", style="Muted.TLabel").pack(anchor="w", pady=(14, 0))

        ttk.Label(queue_tab, text="Fila de impressão", style="Title.TLabel").pack(anchor="w")
        ttk.Label(queue_tab, text="Acompanhe, cancele ou reimprima trabalhos.", style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        self.queue_tree = ttk.Treeview(queue_tab, columns=("status", "pages", "mode", "printer"), show="tree headings", height=10)
        self.queue_tree.heading("#0", text="#")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("pages", text="Pág.")
        self.queue_tree.heading("mode", text="Tipo")
        self.queue_tree.heading("printer", text="Impressora")
        self.queue_tree.column("#0", width=44, stretch=False)
        self.queue_tree.column("status", width=95, stretch=False)
        self.queue_tree.column("pages", width=44, stretch=False, anchor="center")
        self.queue_tree.column("mode", width=65, stretch=False, anchor="center")
        self.queue_tree.column("printer", width=120, stretch=True)
        self.queue_tree.pack(fill="both", expand=True)
        queue_actions = ttk.Frame(queue_tab)
        queue_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(queue_actions, text="Reimprimir", command=self.reprint_selected_job).pack(side="left")
        ttk.Button(queue_actions, text="Cancelar", command=self.cancel_selected_job).pack(side="left", padx=6)
        ttk.Button(queue_actions, text="Ver erro", command=self.show_selected_job_error).pack(side="left")

        self.driver_name = tk.StringVar(value=DEFAULT_TOMATE_NAME)
        self.driver_model = tk.StringVar(value=DEFAULT_CONTRACT.display_name)
        self.driver_uri = tk.StringVar(value="")
        self.driver_info_text = None
        self._show_sidebar_tab("Ajustes")

        status = ttk.Frame(main, style="Status.TFrame")
        status.pack(fill="x", pady=(10, 0))
        ttk.Label(status, textvariable=self.status_message, style="Muted.TLabel").pack(side="left")

    def _build_layers_panel(self, parent: tk.Widget) -> None:
        ttk.Label(parent, text="Camadas", style="Title.TLabel").pack(anchor="w")
        actions = ttk.Frame(parent, style="App.TFrame")
        actions.pack(fill="x", pady=(8, 6))
        ttk.Button(actions, text="Texto", command=self.add_text_overlay).pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Imagem", command=self.add_image_overlay).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.layer_list = LayerList(parent, self._select_layer_from_panel)
        self.layer_list.pack(fill="x", pady=(0, 8))
        order = ttk.Frame(parent, style="App.TFrame")
        order.pack(fill="x")
        ttk.Button(order, text="Frente", command=lambda: self.reorder_selected_overlay("front")).pack(side="left", fill="x", expand=True)
        ttk.Button(order, text="Trás", command=lambda: self.reorder_selected_overlay("back")).pack(side="left", fill="x", expand=True, padx=(6, 0))
        ttk.Button(order, text="↑", width=3, command=lambda: self.reorder_selected_overlay("up")).pack(side="left", padx=(6, 0))
        ttk.Button(order, text="↓", width=3, command=lambda: self.reorder_selected_overlay("down")).pack(side="left", padx=(6, 0))
        ttk.Button(parent, text="Duplicar camada", command=self.duplicate_selected_overlay).pack(fill="x", pady=(8, 0))
        ttk.Button(parent, text="Remover camada", command=self.delete_selected_overlay).pack(fill="x", pady=(6, 12))

        self.module_panel = ttk.Frame(parent, style="App.TFrame")
        self.module_panel.pack(fill="x", pady=(0, 10))

        props = ttk.LabelFrame(parent, text="Propriedades", padding=10)
        props.pack(fill="x")
        ttk.Label(props, text="Nome").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(props, textvariable=self.layer_name).grid(row=0, column=1, sticky="ew", pady=3)
        fields = (
            ("X", self.layer_x),
            ("Y", self.layer_y),
            ("Largura", self.layer_w),
            ("Altura", self.layer_h),
            ("Rotação", self.layer_rotation),
        )
        for row, (label, var) in enumerate(fields, start=1):
            ttk.Label(props, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Spinbox(props, from_=-5000, to=10000, increment=1, textvariable=var, width=12, command=self.apply_layer_properties).grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Label(props, text="Opacidade").grid(row=6, column=0, sticky="w", pady=3)
        ttk.Spinbox(props, from_=0, to=100, increment=5, textvariable=self.layer_opacity, width=12, command=self.apply_layer_properties).grid(row=6, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(props, text="Visível", variable=self.layer_visible, command=self.apply_layer_properties).grid(row=7, column=0, sticky="w", pady=3)
        ttk.Checkbutton(props, text="Bloquear", variable=self.layer_locked, command=self.apply_layer_properties).grid(row=7, column=1, sticky="w", pady=3)
        ttk.Label(props, text="Fonte").grid(row=8, column=0, sticky="w", pady=3)
        font_values = self._font_family_values()
        ttk.Combobox(props, textvariable=self.layer_font_family, values=font_values, width=18).grid(row=8, column=1, sticky="ew", pady=3)
        ttk.Label(props, text="Tamanho").grid(row=9, column=0, sticky="w", pady=3)
        ttk.Spinbox(props, from_=6, to=300, increment=1, textvariable=self.layer_font_size, width=12, command=self.apply_layer_properties).grid(row=9, column=1, sticky="ew", pady=3)
        ttk.Checkbutton(props, text="Negrito", variable=self.layer_bold, command=self.apply_layer_properties).grid(row=10, column=0, sticky="w", pady=3)
        ttk.Checkbutton(props, text="Itálico", variable=self.layer_italic, command=self.apply_layer_properties).grid(row=10, column=1, sticky="w", pady=3)
        ttk.Label(props, text="Alinhamento").grid(row=11, column=0, sticky="w", pady=3)
        ttk.Combobox(props, textvariable=self.layer_align, values=["left", "center", "right"], state="readonly").grid(row=11, column=1, sticky="ew", pady=3)
        color_row = ttk.Frame(props, style="App.TFrame")
        color_row.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(color_row, text="Cor", command=self.pick_layer_color).pack(side="left")
        ttk.Label(color_row, textvariable=self.layer_color, style="Value.TLabel").pack(side="left", padx=(8, 0))
        shape_color_row = ttk.Frame(props, style="App.TFrame")
        shape_color_row.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(shape_color_row, text="Linha", command=self.pick_stroke_color).pack(side="left")
        ttk.Label(shape_color_row, textvariable=self.layer_stroke_color, style="Value.TLabel").pack(side="left", padx=(6, 10))
        ttk.Button(shape_color_row, text="Fundo", command=self.pick_fill_color).pack(side="left")
        ttk.Label(shape_color_row, textvariable=self.layer_fill_color, style="Value.TLabel").pack(side="left", padx=(6, 0))
        ttk.Label(props, text="Espessura").grid(row=14, column=0, sticky="w", pady=3)
        ttk.Spinbox(props, from_=1, to=40, increment=1, textvariable=self.layer_line_width, width=12, command=self.apply_layer_properties).grid(row=14, column=1, sticky="ew", pady=3)
        ttk.Label(props, text="Texto / dados").grid(row=15, column=0, sticky="w", pady=3)
        ttk.Entry(props, textvariable=self.layer_text).grid(row=15, column=1, sticky="ew", pady=3)

        align_box = ttk.LabelFrame(parent, text="Alinhar e distribuir", padding=8)
        align_box.pack(fill="x", pady=(10, 0))
        for index, (label, action) in enumerate((("Esq", "left"), ("Centro H", "center_h"), ("Dir", "right"), ("Topo", "top"), ("Centro V", "center_v"), ("Base", "bottom"))):
            ttk.Button(align_box, text=label, command=lambda value=action: self.align_selected_overlay(value)).grid(row=index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
        ttk.Button(align_box, text="Distribuir H", command=lambda: self.distribute_overlays("horizontal")).grid(row=2, column=0, columnspan=3, sticky="ew", pady=2)
        ttk.Button(align_box, text="Distribuir V", command=lambda: self.distribute_overlays("vertical")).grid(row=3, column=0, columnspan=3, sticky="ew", pady=2)
        for col in range(3):
            align_box.columnconfigure(col, weight=1)

        transform_box = ttk.LabelFrame(parent, text="Transformar", padding=8)
        transform_box.pack(fill="x", pady=(10, 0))
        ttk.Button(transform_box, text="Espelhar H", command=lambda: self.flip_selected_overlay("horizontal")).pack(side="left", fill="x", expand=True)
        ttk.Button(transform_box, text="Espelhar V", command=lambda: self.flip_selected_overlay("vertical")).pack(side="left", fill="x", expand=True, padx=(6, 0))
        ttk.Button(parent, text="Resetar transformação", command=self.reset_selected_transform).pack(fill="x", pady=(6, 0))

        view_box = ttk.LabelFrame(parent, text="Área de trabalho", padding=8)
        view_box.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(view_box, text="Grade discreta", variable=self.show_grid, command=self._save_preferences).pack(anchor="w")
        ttk.Checkbutton(view_box, text="Réguas", variable=self.show_rulers, command=self._save_preferences).pack(anchor="w")
        ttk.Label(view_box, textvariable=self.mouse_position, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(parent, text="Snap à grade", variable=self.snap_enabled, command=self._save_preferences).pack(anchor="w", pady=(10, 2))
        snap_row = ttk.Frame(parent, style="App.TFrame")
        snap_row.pack(fill="x")
        ttk.Label(snap_row, text="Grade").pack(side="left")
        ttk.Spinbox(snap_row, from_=2, to=96, increment=1, textvariable=self.grid_size, width=8, command=self._save_preferences).pack(side="left", padx=(8, 0))
        ttk.Button(parent, text="Aplicar propriedades", style="Accent.TButton", command=self.apply_layer_properties).pack(fill="x", pady=(10, 0))
        props.columnconfigure(1, weight=1)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        bg = "#f1f3f4"
        panel = "#ffffff"
        preview_bg = "#2b2b2b"
        text = "#202124"
        muted = "#5f6368"
        accent = "#3c4043"

        self.root.configure(bg=bg)
        style.configure(".", font=("DejaVu Sans", 10))
        style.configure("App.TFrame", background=bg)
        style.configure("Toolbar.TFrame", background=bg)
        style.configure("PropertyBar.TFrame", background="#e8eaed", relief="flat")
        style.configure("Status.TFrame", background=bg)
        style.configure("PreviewShell.TFrame", background=preview_bg)
        style.configure("PreviewCanvas.TFrame", background=preview_bg, relief="flat", borderwidth=0)
        style.configure("Preview.TLabel", background=preview_bg, foreground="#dadce0")
        style.configure("TLabel", background=bg, foreground=text)
        style.configure("Property.TLabel", background="#e8eaed", foreground=text)
        style.configure("Title.TLabel", background=bg, foreground=text, font=("DejaVu Sans", 11, "bold"))
        style.configure("Muted.TLabel", background=bg, foreground=muted)
        style.configure("Value.TLabel", background=bg, foreground=text, font=("DejaVu Sans", 10, "bold"))
        style.configure("PreviewTitle.TLabel", background=preview_bg, foreground="#f1f3f4", font=("DejaVu Sans", 11, "bold"))
        style.configure("PreviewPill.TLabel", background="#3c4043", foreground="#f1f3f4", padding=(8, 3), font=("DejaVu Sans", 9, "bold"))
        style.configure("Pill.TLabel", background="#e8eaed", foreground="#3c4043", padding=(8, 3), font=("DejaVu Sans", 9, "bold"))
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 7), borderwidth=1, focuscolor=bg)
        style.map(
            "TNotebook.Tab",
            padding=[("selected", (14, 7)), ("active", (14, 7)), ("!selected", (14, 7))],
            background=[("selected", "#ffffff"), ("active", "#e8eaed"), ("!selected", "#f1f3f4")],
        )
        style.configure("TButton", padding=(10, 6), borderwidth=1, focusthickness=0, focuscolor=bg)
        style.map("TButton", padding=[("pressed", (10, 6)), ("active", (10, 6)), ("!active", (10, 6))])
        style.configure("Treeview", background=panel, fieldbackground=panel, foreground=text, rowheight=28, borderwidth=1)
        style.configure("Treeview.Heading", background="#e8eaed", foreground=text, padding=(6, 5), font=("DejaVu Sans", 9, "bold"))
        style.map("Treeview", background=[("selected", "#3c4043")], foreground=[("selected", "#ffffff")])
        style.configure("Tab.TButton", background="#e8eaed", foreground=text, padding=(10, 7), borderwidth=1, focusthickness=0, focuscolor=bg)
        style.map("Tab.TButton", padding=[("pressed", (10, 7)), ("active", (10, 7)), ("!active", (10, 7))], background=[("active", "#dadce0")])
        style.configure("SelectedTab.TButton", background="#ffffff", foreground=text, padding=(10, 7), borderwidth=1, focusthickness=0, focuscolor=bg)
        style.map("SelectedTab.TButton", padding=[("pressed", (10, 7)), ("active", (10, 7)), ("!active", (10, 7))], background=[("active", "#ffffff")])
        style.configure("LeftToolbar.TFrame", background="#202124")
        style.configure("Tool.TButton", background="#3c4043", foreground="#ffffff", padding=(5, 8), borderwidth=1)
        style.map("Tool.TButton", background=[("active", "#5f6368")], foreground=[("disabled", "#9aa0a6")])
        style.configure("SelectedTool.TButton", background="#8ab4f8", foreground="#202124", padding=(5, 8), borderwidth=1)
        style.map("SelectedTool.TButton", background=[("active", "#aecbfa")])
        style.configure("Accent.TButton", background=accent, foreground="#ffffff", padding=(12, 7), borderwidth=1, focusthickness=0, focuscolor=bg)
        style.map(
            "Accent.TButton",
            padding=[("pressed", (12, 7)), ("active", (12, 7)), ("!active", (12, 7))],
            background=[("active", "#202124"), ("pressed", "#171717")],
            foreground=[("disabled", "#dadce0")],
        )

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Novo projeto em branco", accelerator="Ctrl+N", command=self.new_blank_project)
        file_menu.add_command(label="Abrir arquivos...", accelerator="Ctrl+O", command=self.pick_files)
        file_menu.add_command(label="Abrir projeto...", accelerator="Ctrl+Shift+O", command=self.open_project)
        file_menu.add_command(label="Salvar projeto", accelerator="Ctrl+S", command=self.save_project)
        file_menu.add_command(label="Salvar projeto como...", accelerator="Ctrl+Shift+S", command=self.save_project_as)
        file_menu.add_separator()
        file_menu.add_command(label="Sair", command=self.on_close)
        menubar.add_cascade(label="Arquivo", menu=file_menu)

        print_menu = tk.Menu(menubar, tearoff=False)
        print_menu.add_command(label="Imprimir página atual", accelerator="Ctrl+P", command=self.print_current)
        print_menu.add_command(label="Imprimir todas as páginas", accelerator="Ctrl+Shift+P", command=self.print_all)
        print_menu.add_command(label="Imprimir faixa", command=self.print_range)
        menubar.add_cascade(label="Impressão", menu=print_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Desfazer", accelerator="Ctrl+Z", command=self.undo_edit)
        view_menu.add_command(label="Refazer", accelerator="Ctrl+Y", command=self.redo_edit)
        view_menu.add_separator()
        view_menu.add_command(label="Página anterior", accelerator="Ctrl+←", command=self.prev_page)
        view_menu.add_command(label="Próxima página", accelerator="Ctrl+→", command=self.next_page)
        view_menu.add_separator()
        view_menu.add_command(label="Alternar redimensionar/rotacionar", accelerator="Ctrl+R", command=self._toggle_preview_mode)
        view_menu.add_command(label="Redefinir escala/rotação", accelerator="Ctrl+0", command=self.reset_scale)
        view_menu.add_command(label="Limpar corte", accelerator="Ctrl+Shift+0", command=self.reset_crop)
        menubar.add_cascade(label="Navegação", menu=view_menu)

        layers_menu = tk.Menu(menubar, tearoff=False)
        layers_menu.add_command(label="Adicionar texto", command=self.add_text_overlay)
        layers_menu.add_command(label="Adicionar imagem", command=self.add_image_overlay)
        layers_menu.add_command(label="Adicionar numeração", command=self.open_counter_window)
        layers_menu.add_command(label="Editar camada selecionada", command=self.edit_selected_overlay)
        layers_menu.add_separator()
        layers_menu.add_command(label="Trazer para frente", command=lambda: self.reorder_selected_overlay("front"))
        layers_menu.add_command(label="Enviar para trás", command=lambda: self.reorder_selected_overlay("back"))
        layers_menu.add_command(label="Mover acima", command=lambda: self.reorder_selected_overlay("up"))
        layers_menu.add_command(label="Mover abaixo", command=lambda: self.reorder_selected_overlay("down"))
        layers_menu.add_command(label="Duplicar camada", command=self.duplicate_selected_overlay)
        layers_menu.add_command(label="Remover camada selecionada", accelerator="Delete", command=self.delete_selected_overlay)
        menubar.add_cascade(label="Camadas", menu=layers_menu)

        object_menu = tk.Menu(menubar, tearoff=False)
        object_menu.add_command(label="Retângulo", command=lambda: self.set_active_tool("rect"))
        object_menu.add_command(label="Círculo", command=lambda: self.set_active_tool("ellipse"))
        object_menu.add_command(label="Linha", command=lambda: self.set_active_tool("line"))
        object_menu.add_separator()
        object_menu.add_command(label="Alinhar à esquerda", command=lambda: self.align_selected_overlay("left"))
        object_menu.add_command(label="Centralizar horizontal", command=lambda: self.align_selected_overlay("center_h"))
        object_menu.add_command(label="Alinhar à direita", command=lambda: self.align_selected_overlay("right"))
        object_menu.add_command(label="Alinhar ao topo", command=lambda: self.align_selected_overlay("top"))
        object_menu.add_command(label="Centralizar vertical", command=lambda: self.align_selected_overlay("center_v"))
        object_menu.add_command(label="Alinhar à base", command=lambda: self.align_selected_overlay("bottom"))
        menubar.add_cascade(label="Objeto", menu=object_menu)

        export_menu = tk.Menu(menubar, tearoff=False)
        export_menu.add_command(label="Exportar PNG...", command=lambda: self.export_current("png"))
        export_menu.add_command(label="Exportar PDF...", command=lambda: self.export_current("pdf"))
        menubar.add_cascade(label="Exportar", menu=export_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Driver Tomate / CUPS...", command=self.open_driver_window)
        tools_menu.add_command(label="Verificar driver agora", command=lambda: self.open_driver_window(refresh=True))
        menubar.add_cascade(label="Ferramentas", menu=tools_menu)
        self.root.config(menu=menubar)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-n>", lambda _event: self.new_blank_project())
        self.root.bind_all("<Control-o>", lambda _event: self.pick_files())
        self.root.bind_all("<Control-O>", lambda _event: self.open_project())
        self.root.bind_all("<Control-s>", lambda _event: self.save_project())
        self.root.bind_all("<Control-S>", lambda _event: self.save_project_as())
        self.root.bind_all("<Control-p>", lambda _event: self.print_current())
        self.root.bind_all("<Control-P>", lambda _event: self.print_all())
        self.root.bind_all("<Control-Left>", lambda _event: self.prev_page())
        self.root.bind_all("<Control-Right>", lambda _event: self.next_page())
        self.root.bind_all("<Control-r>", lambda _event: self._toggle_preview_mode())
        self.root.bind_all("<Control-z>", lambda _event: self.undo_edit())
        self.root.bind_all("<Control-y>", lambda _event: self.redo_edit())
        self.root.bind_all("<Control-Z>", lambda _event: self.redo_edit())
        self.root.bind_all("<Control-c>", lambda _event: self.copy_selected_overlay())
        self.root.bind_all("<Control-v>", lambda _event: self.paste_overlay())
        self.root.bind_all("<Control-d>", lambda _event: self.duplicate_selected_overlay())
        self.root.bind_all("<Control-a>", lambda _event: self.select_all_overlays())
        self.root.bind_all("<Control-g>", lambda _event: self.status_message.set("Agrupamento preparado na arquitetura; seleção múltipla completa vem na próxima etapa."))
        self.root.bind_all("<Control-G>", lambda _event: self.status_message.set("Desagrupar preparado na arquitetura."))
        self.root.bind_all("<Control-0>", lambda _event: self.reset_scale())
        self.root.bind_all("<Control-parenright>", lambda _event: self.reset_crop())
        self.root.bind_all("<Delete>", lambda _event: self.delete_selected_overlay())
        self.root.bind_all("<Escape>", lambda _event: self._end_preview_action())

    def _queue_job_changed(self, job: PrintJob) -> None:
        self.root.after(0, lambda: self._refresh_queue_row(job))

    def _refresh_queue_row(self, job: PrintJob) -> None:
        item = str(job.id)
        values = (job.status, len(job.payloads), "Normal" if job.output_mode == "normal" else "TSPL", job.printer)
        if self.queue_tree.exists(item):
            self.queue_tree.item(item, text=f"#{job.id}", values=values)
        else:
            self.queue_tree.insert("", "end", iid=item, text=f"#{job.id}", values=values)
        self.status_message.set(f"Fila: #{job.id} {job.status.lower()} - {job.title}")

    def _select_queue_job_when_ready(self, job_id: int, attempts: int = 20) -> None:
        item = str(job_id)
        if not self.queue_tree.winfo_exists():
            return
        if self.queue_tree.exists(item):
            self.queue_tree.selection_set(item)
            self.queue_tree.focus(item)
            self.queue_tree.see(item)
        elif attempts > 0:
            self.root.after(50, lambda: self._select_queue_job_when_ready(job_id, attempts - 1))

    def _selected_job(self) -> PrintJob | None:
        selection = self.queue_tree.selection()
        if not selection:
            messagebox.showwarning("Fila de impressão", "Selecione um trabalho na fila.")
            return None
        return self.print_queue.get(int(selection[0]))

    def cancel_selected_job(self) -> None:
        job = self._selected_job()
        if job and not self.print_queue.cancel(job.id):
            messagebox.showinfo("Fila de impressão", "Este trabalho nao pode mais ser cancelado.")

    def reprint_selected_job(self) -> None:
        job = self._selected_job()
        if job:
            new_job = self.print_queue.requeue(job.id)
            if new_job:
                self._select_queue_job_when_ready(new_job.id)

    def show_selected_job_error(self) -> None:
        job = self._selected_job()
        if not job:
            return
        details = job.error or job.cups_result or "Nenhum erro registrado para este trabalho."
        messagebox.showinfo(f"Trabalho #{job.id}", details)

    def open_driver_window(self, refresh: bool = True) -> None:
        if hasattr(self, "driver_window") and self.driver_window.winfo_exists():
            self.driver_window.lift()
            if refresh:
                self.refresh_driver_info()
            return

        window = tk.Toplevel(self.root)
        window.title("Driver Tomate / CUPS")
        window.geometry("620x500")
        window.transient(self.root)
        self.driver_window = window

        container = ttk.Frame(window, padding=12, style="App.TFrame")
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Driver / CUPS", style="Title.TLabel").pack(anchor="w")
        ttk.Label(container, text="Escolha modelo, fila CUPS e porta/URI detectada ou manual.", style="Muted.TLabel").pack(anchor="w", pady=(2, 10))

        driver_grid = ttk.Frame(container)
        driver_grid.pack(fill="x")
        ttk.Label(driver_grid, text="Modelo").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(driver_grid, textvariable=self.driver_model, values=contract_names(), state="readonly").grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(driver_grid, text="Fila CUPS").grid(row=1, column=0, sticky="w", pady=4)
        printer_values = self.detected_printers or [DEFAULT_TOMATE_NAME]
        self.driver_name_combo = ttk.Combobox(driver_grid, textvariable=self.driver_name, values=printer_values)
        self.driver_name_combo.grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Label(driver_grid, text="Porta / URI").grid(row=2, column=0, sticky="w", pady=4)
        self.driver_uri_combo = ttk.Combobox(driver_grid, textvariable=self.driver_uri, values=[])
        self.driver_uri_combo.grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(driver_grid, text="Verificar", command=self.refresh_driver_info).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(driver_grid, text="Instalar/Reparar", command=self.install_driver).grid(row=3, column=1, sticky="ew", pady=(8, 0), padx=(8, 0))
        driver_grid.columnconfigure(1, weight=1)

        self.driver_info_text = tk.Text(container, height=12, wrap="word", borderwidth=1, relief="solid")
        self.driver_info_text.pack(fill="both", expand=True, pady=(10, 0))
        self.refresh_driver_info()

    def refresh_driver_info(self) -> None:
        if self.driver_info_text is None:
            self.open_driver_window(refresh=False)
            return
        contract = contract_by_display_name(self.driver_model.get())
        name = self.driver_name.get().strip() or contract.default_queue_name
        manual_uri = self.driver_uri.get().strip() or None
        info = contract.inspect(name, manual_uri)
        uri_values = info.available_uris or ([info.uri] if info.uri else [])
        if info.uri and info.uri not in uri_values:
            uri_values.insert(0, info.uri)
        if hasattr(self, "driver_uri_combo"):
            self.driver_uri_combo.configure(values=uri_values)
        if info.uri:
            self.driver_uri.set(info.uri)
        if hasattr(self, "driver_name_combo"):
            self.driver_name_combo.configure(values=list_printers() or [name])
        lines = [
            f"Contrato: {info.display_name} ({info.contract_id})",
            f"Instalada: {'sim' if info.installed else 'nao'}",
            f"Nome: {info.name}",
            f"URI detectada: {info.uri}",
            f"URIs disponiveis: {', '.join(uri_values) if uri_values else 'nenhuma'}",
            "",
            "Comando de instalacao/reparo:",
            " ".join(info.command),
            "",
            "Status:",
            info.status,
        ]
        self.driver_info_text.delete("1.0", "end")
        self.driver_info_text.insert("1.0", "\n".join(lines))

    def install_driver(self) -> None:
        if self.driver_info_text is None:
            self.open_driver_window(refresh=False)
        contract = contract_by_display_name(self.driver_model.get())
        name = self.driver_name.get().strip() or contract.default_queue_name
        uri = self.driver_uri.get().strip() or None
        ok, output = contract.install_or_repair(name, uri)
        self.refresh_driver_info()
        self.detected_printers = list_printers()
        printer_values = self.detected_printers or [name]
        if hasattr(self, "top_printer_combo"):
            self.top_printer_combo.configure(values=printer_values)
        if hasattr(self, "driver_name_combo"):
            self.driver_name_combo.configure(values=printer_values)
        if ok:
            self.printer_name.set(name)
            messagebox.showinfo("Driver / CUPS", output)
        else:
            messagebox.showerror("Driver / CUPS", output)

    def _show_sidebar_tab(self, name: str) -> None:
        for tab_name, frame in self.sidebar_pages.items():
            frame.pack_forget()
            style = "SelectedTab.TButton" if tab_name == name else "Tab.TButton"
            self.sidebar_tab_buttons[tab_name].configure(style=style)
        self.sidebar_pages[name].pack(fill="both", expand=True)

    def _has_document(self) -> bool:
        return self.blank_document or bool(self.page_sources)

    def _page_count(self) -> int:
        return 1 if self.blank_document else len(self.page_sources)

    def _font_family_values(self) -> list[str]:
        if self._font_families_cache is not None:
            return self._font_families_cache
        fallback = ["DejaVu Sans", "Arial", "Liberation Sans", "Noto Sans"]
        try:
            values = sorted(set(str(name) for name in tkfont.families() if str(name).strip()))
        except tk.TclError:
            values = []
        self._font_families_cache = values or fallback
        return self._font_families_cache

    def set_active_tool(self, tool: str) -> None:
        self.active_tool.set(tool)
        if hasattr(self, "left_toolbar"):
            self.left_toolbar.refresh()
        if tool == "text":
            self.status_message.set("Ferramenta texto: clique no canvas para criar texto.")
        elif tool == "image":
            self.add_image_overlay()
            self.active_tool.set("select")
            self.left_toolbar.refresh()
        elif tool in {"rect", "ellipse", "line", "barcode", "qrcode"}:
            labels = {"rect": "retângulo", "ellipse": "círculo", "line": "linha", "barcode": "código de barras", "qrcode": "QR Code"}
            self.status_message.set(f"Ferramenta {labels[tool]}: clique no canvas para criar.")
        else:
            self.status_message.set("Ferramenta ativa: seleção." if tool == "select" else "Ferramenta ativa: mover.")

    def _snap_value(self, value: float) -> float:
        if not bool(self.snap_enabled.get()):
            return value
        size = max(2, int(self.grid_size.get()))
        return round(value / size) * size

    def _save_preferences(self) -> None:
        self.app_settings.preferences["snap_enabled"] = bool(self.snap_enabled.get())
        self.app_settings.preferences["grid_size"] = int(self.grid_size.get())
        self.app_settings.preferences["show_grid"] = bool(self.show_grid.get())
        self.app_settings.preferences["show_rulers"] = bool(self.show_rulers.get())
        save_settings(self.app_settings)
        self.schedule_preview()

    def _enable_file_drop(self, widget) -> None:
        if not hasattr(widget, "drop_target_register"):
            return
        try:
            from tkinterdnd2 import DND_FILES

            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_files_dropped)
            widget.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            widget.dnd_bind("<<DragLeave>>", self._on_drag_leave)
        except Exception:
            self.status_message.set("Arrastar arquivo requer tkinterdnd2 nesta sessão.")

    def _on_drag_enter(self, _event=None):
        if not self._has_document():
            self._draw_empty_preview("Solte o PDF ou imagem aqui")
        return "copy"

    def _on_drag_leave(self, _event=None):
        if not self._has_document():
            self._draw_empty_preview("Novo projeto em branco ou arraste um PDF/imagem.")
        return "copy"

    def _on_files_dropped(self, event) -> str:
        paths = [normalize_input_path(path) for path in self.root.tk.splitlist(event.data)]
        files = [path for path in paths if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES]
        if files:
            self.load_files(files)
        else:
            self.status_message.set("Solte arquivos PDF ou imagem.")
        return "copy"

    def _new_overlay_id(self) -> str:
        overlay_id = f"layer-{self.next_overlay_id}"
        self.next_overlay_id += 1
        return overlay_id

    def _current_overlays(self) -> list[dict[str, object]]:
        return self.page_overlays.setdefault(self.current_index, [])

    def _overlay_snapshot(self) -> dict[str, object]:
        return {
            "page_overlays": deepcopy(self.page_overlays),
            "selected_overlay_id": self.selected_overlay_id,
        }

    def _restore_overlay_snapshot(self, snapshot: dict[str, object]) -> None:
        self.overlay_history_paused = True
        try:
            self.page_overlays = deepcopy(snapshot.get("page_overlays", {}))
            self.selected_overlay_id = snapshot.get("selected_overlay_id") if isinstance(snapshot.get("selected_overlay_id"), str) else None
        finally:
            self.overlay_history_paused = False
        self._sync_layer_panel()
        self.schedule_preview()

    def _record_overlay_history(self) -> None:
        if self.overlay_history_paused:
            return
        self.overlay_undo_stack.append(self._overlay_snapshot())
        if len(self.overlay_undo_stack) > 100:
            self.overlay_undo_stack.pop(0)
        self.overlay_redo_stack.clear()
        self._update_history_buttons()

    def undo_overlay_edit(self) -> bool:
        if not self.overlay_undo_stack:
            return False
        self.overlay_redo_stack.append(self._overlay_snapshot())
        self._restore_overlay_snapshot(self.overlay_undo_stack.pop())
        self.status_message.set("Ação de camada desfeita.")
        self._update_history_buttons()
        return True

    def redo_overlay_edit(self) -> bool:
        if not self.overlay_redo_stack:
            return False
        self.overlay_undo_stack.append(self._overlay_snapshot())
        self._restore_overlay_snapshot(self.overlay_redo_stack.pop())
        self.status_message.set("Ação de camada refeita.")
        self._update_history_buttons()
        return True

    def _canvas_point_from_event(self, event) -> tuple[float, float] | None:
        if not self.preview_image_box:
            return None
        x1, y1, _x2, _y2 = self.preview_image_box
        border = 2
        scale = max(self.preview_scale, 0.01)
        return ((event.x - x1 - border) / scale, (event.y - y1 - border) / scale)

    def _create_text_at_event(self, event) -> None:
        point = self._canvas_point_from_event(event)
        if not point:
            return
        self._record_overlay_history()
        width, height = self._canvas_size_px()
        x = self._snap_value(point[0])
        y = self._snap_value(point[1])
        font_size = max(18, round(height * 0.035))
        overlay = {
            "id": self._new_overlay_id(),
            "type": "text",
            "name": "Texto",
            "text": "Texto",
            "x": max(0, round(x)),
            "y": max(0, round(y)),
            "w": max(140, round(width * 0.25)),
            "h": max(44, font_size + 12),
            "font_size": font_size,
            "font_family": self.layer_font_family.get(),
            "bold": bool(self.layer_bold.get()),
            "italic": bool(self.layer_italic.get()),
            "color": self.layer_color.get(),
            "align": self.layer_align.get(),
            "rotation": 0,
        }
        self._current_overlays().append(overlay)
        self.selected_overlay_id = str(overlay["id"])
        self._sync_layer_panel()
        self._show_sidebar_tab("Camadas")
        self.status_message.set("Texto criado. Edite o conteúdo no painel Camadas ou dê duplo clique.")
        self.schedule_preview()

    def _create_shape_at_event(self, event, shape_type: str) -> None:
        point = self._canvas_point_from_event(event)
        if not point:
            return
        self._record_overlay_history()
        width, height = self._canvas_size_px()
        x = max(0, round(self._snap_value(point[0])))
        y = max(0, round(self._snap_value(point[1])))
        square_size = max(80, round(min(width, height) * 0.18))
        defaults = {
            "rect": ("Quadrado", square_size, square_size),
            "ellipse": ("Círculo", max(70, round(width * 0.14)), max(70, round(width * 0.14))),
            "line": ("Linha", max(120, round(width * 0.25)), 4),
            "barcode": ("Código de barras", max(180, round(width * 0.35)), 70),
            "qrcode": ("QR Code", 110, 110),
        }
        name, w, h = defaults[shape_type]
        overlay = {
            "id": self._new_overlay_id(),
            "type": "shape",
            "shape": shape_type,
            "name": name,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "rotation": 0,
            "color": "#000000",
            "stroke_color": "#000000",
            "fill_color": "none",
            "line_width": 3,
            "visible": True,
            "locked": False,
            "opacity": 100,
        }
        if shape_type in {"barcode", "qrcode"}:
            overlay["data"] = "YNIX"
        self._current_overlays().append(overlay)
        self.selected_overlay_id = str(overlay["id"])
        self._sync_layer_panel()
        self._show_sidebar_tab("Camadas")
        self.set_active_tool("select")
        self.schedule_preview()

    def _select_layer_from_panel(self, layer_id: str) -> None:
        if self.selected_overlay_id == layer_id:
            return
        self.selected_overlay_id = layer_id
        self._sync_layer_panel()
        self._draw_selection_overlay()

    def _sync_layer_panel(self, *, update_module: bool = True, update_list: bool = True) -> None:
        overlay = self._selected_overlay()
        if overlay:
            self.layer_name.set(str(overlay.get("name", "")))
            self.layer_x.set(round(float(overlay.get("x", 0)), 2))
            self.layer_y.set(round(float(overlay.get("y", 0)), 2))
            self.layer_w.set(round(float(overlay.get("w", 0)), 2))
            self.layer_h.set(round(float(overlay.get("h", 0)), 2))
            self.layer_rotation.set(round(float(overlay.get("rotation", 0)), 2))
            self.layer_font_family.set(str(overlay.get("font_family", "DejaVu Sans")))
            self.layer_font_size.set(int(overlay.get("font_size", 28)))
            self.layer_bold.set(bool(overlay.get("bold", False)))
            self.layer_italic.set(bool(overlay.get("italic", False)))
            self.layer_color.set(str(overlay.get("color", "#000000")))
            self.layer_stroke_color.set(str(overlay.get("stroke_color", overlay.get("color", "#000000"))))
            self.layer_fill_color.set(str(overlay.get("fill_color", "none")))
            self.layer_line_width.set(int(float(overlay.get("line_width", 3))))
            self.layer_align.set(str(overlay.get("align", "left")))
            if overlay.get("type") == "text":
                self.layer_text.set(str(overlay.get("text", "")))
            elif overlay.get("type") == "shape" and overlay.get("shape") in {"barcode", "qrcode"}:
                self.layer_text.set(str(overlay.get("data", "")))
            else:
                self.layer_text.set("")
            self.layer_opacity.set(int(float(overlay.get("opacity", 100))))
            self.layer_visible.set(bool(overlay.get("visible", True)))
            self.layer_locked.set(bool(overlay.get("locked", False)))
        if update_list and hasattr(self, "layer_list"):
            self.layer_list.set_layers(self._current_overlays(), self.selected_overlay_id)
        if update_module:
            self._render_module_panel(overlay)

    def _module_var_for_field(self, field: ModuleField, value: object) -> tk.Variable:
        if field.kind == "bool":
            return tk.BooleanVar(value=bool(value))
        if field.kind == "int":
            try:
                return tk.IntVar(value=int(value))
            except (TypeError, ValueError, tk.TclError):
                return tk.IntVar(value=int(field.default or 0))
        return tk.StringVar(value=str(value))

    def _render_module_panel(self, overlay: dict[str, object] | None) -> None:
        if not hasattr(self, "module_panel"):
            return
        module = module_for_overlay(overlay)
        key = (str(overlay.get("id")), module.id) if overlay and module else None
        if key == self._module_panel_key:
            return
        self._module_panel_key = key
        for child in self.module_panel.winfo_children():
            child.destroy()
        self.module_field_vars.clear()
        self.module_field_specs.clear()
        if not module or overlay is None:
            return
        box = ttk.LabelFrame(self.module_panel, text=module.title, padding=8)
        box.pack(fill="x")
        for row, field in enumerate(module.fields):
            value = overlay.get(field.key, field.default)
            var = self._module_var_for_field(field, value)
            self.module_field_vars[field.key] = var
            self.module_field_specs[field.key] = field
            ttk.Label(box, text=field.label).grid(row=row, column=0, sticky="w", pady=3, padx=(0, 8))
            if field.kind == "choice":
                choices = field.choices
                if field.key == "font_family":
                    choices = tuple(self._font_family_values())
                ttk.Combobox(box, textvariable=var, values=choices, width=22).grid(row=row, column=1, sticky="ew", pady=3)
            elif field.kind == "int":
                ttk.Spinbox(box, from_=field.min_value, to=field.max_value, increment=1, textvariable=var, width=12).grid(row=row, column=1, sticky="ew", pady=3)
            elif field.kind == "bool":
                ttk.Checkbutton(box, variable=var).grid(row=row, column=1, sticky="w", pady=3)
            elif field.kind == "color":
                row_frame = ttk.Frame(box, style="App.TFrame")
                row_frame.grid(row=row, column=1, sticky="ew", pady=3)
                ttk.Entry(row_frame, textvariable=var).pack(side="left", fill="x", expand=True)
                ttk.Button(row_frame, text="...", width=3, command=lambda key=field.key: self.pick_module_color(key)).pack(side="left", padx=(6, 0))
            else:
                ttk.Entry(box, textvariable=var).grid(row=row, column=1, sticky="ew", pady=3)
        box.columnconfigure(1, weight=1)
        ttk.Button(box, text=f"Aplicar {module.title}", style="Accent.TButton", command=self.apply_module_properties).grid(
            row=len(module.fields),
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
        )

    def pick_module_color(self, key: str) -> None:
        var = self.module_field_vars.get(key)
        if not var:
            return
        current = str(var.get())
        color = colorchooser.askcolor(color="#ffffff" if current == "none" else current, title="Cor")
        if color and color[1]:
            var.set(color[1])

    def apply_module_properties(self) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            return
        self._record_overlay_history()
        try:
            for key, var in self.module_field_vars.items():
                field = self.module_field_specs[key]
                if field.kind == "int":
                    value = max(field.min_value, min(field.max_value, int(var.get())))
                elif field.kind == "bool":
                    value = bool(var.get())
                else:
                    value = str(var.get())
                overlay[key] = value
            if overlay.get("type") == "text":
                overlay["name"] = str(overlay.get("text", "") or "Texto")[:24]
                self._autosize_text_overlay(overlay)
            elif overlay.get("type") == "counter":
                self._autosize_text_overlay(overlay)
            elif overlay.get("type") == "shape" and overlay.get("shape") in {"qrcode", "barcode"}:
                overlay["data"] = str(overlay.get("data", "")).strip() or "YNIX"
            if "stroke_color" in overlay:
                overlay["color"] = overlay["stroke_color"]
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Módulo", f"Revise os campos do módulo:\n{exc}")
            return
        self._sync_layer_panel()
        self.schedule_preview()
        self.status_message.set("Módulo atualizado.")

    def apply_layer_properties(self) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            return
        self._record_overlay_history()
        try:
            overlay["name"] = self.layer_name.get().strip() or str(overlay.get("name") or "Camada")
            overlay["x"] = round(self._snap_value(float(self.layer_x.get())), 2)
            overlay["y"] = round(self._snap_value(float(self.layer_y.get())), 2)
            overlay["w"] = max(4, round(float(self.layer_w.get()), 2))
            overlay["h"] = max(4, round(float(self.layer_h.get()), 2))
            overlay["rotation"] = round(float(self.layer_rotation.get()), 2)
            overlay["font_family"] = self.layer_font_family.get()
            overlay["font_size"] = max(6, int(self.layer_font_size.get()))
            overlay["bold"] = bool(self.layer_bold.get())
            overlay["italic"] = bool(self.layer_italic.get())
            overlay["color"] = self.layer_color.get()
            overlay["stroke_color"] = self.layer_stroke_color.get()
            overlay["fill_color"] = self.layer_fill_color.get()
            overlay["line_width"] = max(1, int(self.layer_line_width.get()))
            overlay["align"] = self.layer_align.get()
            overlay["opacity"] = max(0, min(100, int(self.layer_opacity.get())))
            overlay["visible"] = bool(self.layer_visible.get())
            overlay["locked"] = bool(self.layer_locked.get())
            if overlay.get("type") == "text":
                overlay["text"] = self.layer_text.get()
                overlay["name"] = self.layer_text.get()[:24] or "Texto"
                self._autosize_text_overlay(overlay)
            elif overlay.get("type") == "shape" and overlay.get("shape") in {"barcode", "qrcode"}:
                overlay["data"] = self.layer_text.get().strip() or "YNIX"
        except (tk.TclError, ValueError):
            return
        self._sync_layer_panel()
        self.schedule_preview()

    def pick_layer_color(self) -> None:
        color = colorchooser.askcolor(color=self.layer_color.get(), title="Cor da camada")
        if color and color[1]:
            self.layer_color.set(color[1])
            self.layer_stroke_color.set(color[1])
            self.apply_layer_properties()

    def pick_stroke_color(self) -> None:
        color = colorchooser.askcolor(color=self.layer_stroke_color.get(), title="Cor da linha")
        if color and color[1]:
            self.layer_stroke_color.set(color[1])
            self.layer_color.set(color[1])
            self.apply_layer_properties()

    def pick_fill_color(self) -> None:
        current = self.layer_fill_color.get()
        color = colorchooser.askcolor(color="#ffffff" if current == "none" else current, title="Cor do fundo")
        if color and color[1]:
            self.layer_fill_color.set(color[1])
            self.apply_layer_properties()

    def reorder_selected_overlay(self, action: str) -> None:
        if not self.selected_overlay_id:
            return
        self._record_overlay_history()
        if reorder(self._current_overlays(), self.selected_overlay_id, action):
            self._sync_layer_panel()
            self.schedule_preview()

    def duplicate_selected_overlay(self) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            return
        self._record_overlay_history()
        clone = duplicate_overlay(overlay)
        self._current_overlays().append(clone)
        self.selected_overlay_id = str(clone["id"])
        self._sync_layer_panel()
        self.schedule_preview()

    def copy_selected_overlay(self) -> None:
        overlay = self._selected_overlay()
        if overlay:
            self.clipboard_overlay = deepcopy(overlay)
            self.status_message.set("Camada copiada.")

    def paste_overlay(self) -> None:
        if not self.clipboard_overlay:
            return
        self._record_overlay_history()
        clone = duplicate_overlay(self.clipboard_overlay)
        self._current_overlays().append(clone)
        self.selected_overlay_id = str(clone["id"])
        self._sync_layer_panel()
        self.schedule_preview()

    def select_all_overlays(self) -> None:
        overlays = self._current_overlays()
        if overlays:
            self.selected_overlay_id = str(overlays[-1].get("id"))
            self._sync_layer_panel()
            self._draw_selection_overlay()
            self.status_message.set(f"{len(overlays)} camada(s) no documento. Seleção múltipla completa preparada para próxima etapa.")

    def _show_context_menu(self, event) -> None:
        selected_overlay = self._selected_overlay()
        overlay = selected_overlay if selected_overlay and self._overlay_handle_at(selected_overlay, event.x, event.y) else self._overlay_at(event.x, event.y)
        if not overlay:
            return
        self.selected_overlay_id = str(overlay["id"])
        self._sync_layer_panel()
        self._draw_selection_overlay()
        if not hasattr(self, "context_menu"):
            self.context_menu = LayerContextMenu(self.preview_canvas, self._handle_context_action)
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _handle_context_action(self, action: str) -> None:
        if action == "edit":
            self.edit_selected_overlay()
        elif action == "duplicate":
            self.duplicate_selected_overlay()
        elif action == "delete":
            self.delete_selected_overlay()
        else:
            self.reorder_selected_overlay(action)

    def align_selected_overlay(self, action: str) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            return
        self._record_overlay_history()
        width, height = self._canvas_size_px()
        w = float(overlay.get("w", 1))
        h = float(overlay.get("h", 1))
        if action == "left":
            overlay["x"] = 0
        elif action == "right":
            overlay["x"] = max(0, width - w)
        elif action == "center_h":
            overlay["x"] = max(0, (width - w) / 2)
        elif action == "top":
            overlay["y"] = 0
        elif action == "bottom":
            overlay["y"] = max(0, height - h)
        elif action == "center_v":
            overlay["y"] = max(0, (height - h) / 2)
        self._sync_layer_panel()
        self.schedule_preview()

    def distribute_overlays(self, axis: str) -> None:
        overlays = [overlay for overlay in self._current_overlays() if overlay.get("visible", True) and not overlay.get("locked", False)]
        if len(overlays) < 3:
            self.status_message.set("Distribuição precisa de pelo menos 3 camadas desbloqueadas.")
            return
        self._record_overlay_history()
        key = "x" if axis == "horizontal" else "y"
        size_key = "w" if axis == "horizontal" else "h"
        overlays.sort(key=lambda item: float(item.get(key, 0)))
        first = float(overlays[0].get(key, 0))
        last = float(overlays[-1].get(key, 0))
        total_size = sum(float(item.get(size_key, 0)) for item in overlays)
        available = max(0.0, last + float(overlays[-1].get(size_key, 0)) - first - total_size)
        gap = available / (len(overlays) - 1)
        cursor = first
        for overlay in overlays:
            overlay[key] = round(cursor, 2)
            cursor += float(overlay.get(size_key, 0)) + gap
        self._sync_layer_panel()
        self.schedule_preview()

    def flip_selected_overlay(self, axis: str) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            return
        self._record_overlay_history()
        overlay["flip_x" if axis == "horizontal" else "flip_y"] = not bool(overlay.get("flip_x" if axis == "horizontal" else "flip_y", False))
        self.schedule_preview()

    def reset_selected_transform(self) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            return
        self._record_overlay_history()
        overlay["rotation"] = 0
        overlay["flip_x"] = False
        overlay["flip_y"] = False
        self._sync_layer_panel()
        self.schedule_preview()

    def add_text_overlay(self) -> None:
        if not self._has_document():
            self.new_blank_project()
            if not self._has_document():
                return
        self.set_active_tool("text")

    def _require_document_for_layer(self) -> bool:
        if self._has_document():
            return True
        self.new_blank_project()
        return self._has_document()

    def _ensure_blank_canvas_message(self) -> None:
        if self.blank_document:
            self.status_message.set("Projeto em branco pronto para editar.")

    def _open_text_window_requires_document(self) -> bool:
        if self._has_document():
            return True
        messagebox.showinfo("Camadas", "Crie um projeto em branco ou abra um arquivo antes de editar texto.")
        return False

    def _document_page_indexes(self) -> list[int]:
        return list(range(self._page_count()))

    def _base_canvas_image(self) -> Image.Image:
        width, height = self._canvas_size_px()
        return Image.new("1", (width, height), 255)

    def _base_fit_result(self):
        from .imaging import FitResult

        width, height = self._canvas_size_px()
        return FitResult(self._base_canvas_image(), (0, 0, width, height))

    def _document_title(self) -> str:
        return "Projeto em branco" if self.blank_document else "Documento"

    def open_text_window(self, overlay: dict[str, object] | None = None) -> None:
        if not self._open_text_window_requires_document():
            return
        if hasattr(self, "text_window") and self.text_window.winfo_exists():
            self.text_window.lift()
            return

        editing = overlay is not None
        window = tk.Toplevel(self.root)
        window.title("Editar texto" if editing else "Texto")
        window.geometry("560x520")
        window.minsize(520, 460)
        window.transient(self.root)
        window.configure(bg="#f1f3f4")
        self.text_window = window

        width, height = self._canvas_size_px()
        text_var = tk.StringVar(value=str(overlay.get("text", "")) if overlay else "")
        size_var = tk.IntVar(value=int(overlay.get("font_size", max(18, round(height * 0.035)))) if overlay else max(18, round(height * 0.035)))
        family_var = tk.StringVar(value=str(overlay.get("font_family", self.layer_font_family.get())) if overlay else self.layer_font_family.get())
        bold_var = tk.BooleanVar(value=bool(overlay.get("bold", self.layer_bold.get())) if overlay else bool(self.layer_bold.get()))
        italic_var = tk.BooleanVar(value=bool(overlay.get("italic", self.layer_italic.get())) if overlay else bool(self.layer_italic.get()))
        color_var = tk.StringVar(value=str(overlay.get("color", self.layer_color.get())) if overlay else self.layer_color.get())
        align_var = tk.StringVar(value=str(overlay.get("align", self.layer_align.get())) if overlay else self.layer_align.get())
        status_var = tk.StringVar(value="Duplo clique na camada para editar depois.")

        container = ttk.Frame(window, padding=12, style="App.TFrame")
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Texto", style="Title.TLabel").pack(anchor="w")
        ttk.Label(container, text="Edite o texto que será impresso por cima da página.", style="Muted.TLabel").pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(container, style="App.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="Texto").grid(row=0, column=0, sticky="w", pady=5, padx=(0, 10))
        text_entry = ttk.Entry(form, textvariable=text_var)
        text_entry.grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Tamanho").grid(row=1, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Spinbox(form, from_=6, to=300, increment=1, textvariable=size_var, width=14).grid(row=1, column=1, sticky="w", pady=5)
        ttk.Label(form, text="Fonte").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Combobox(form, textvariable=family_var, values=self._font_family_values(), width=22).grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Alinhamento").grid(row=3, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Combobox(form, textvariable=align_var, values=["left", "center", "right"], state="readonly", width=14).grid(row=3, column=1, sticky="w", pady=5)
        ttk.Checkbutton(form, text="Negrito", variable=bold_var).grid(row=4, column=0, sticky="w", pady=5)
        ttk.Checkbutton(form, text="Itálico", variable=italic_var).grid(row=4, column=1, sticky="w", pady=5)
        color_row = ttk.Frame(form, style="App.TFrame")
        color_row.grid(row=5, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Button(color_row, text="Cor", command=lambda: self._choose_text_color(color_var)).pack(side="left")
        ttk.Label(color_row, textvariable=color_var, style="Value.TLabel").pack(side="left", padx=(8, 0))
        form.columnconfigure(1, weight=1)

        ttk.Label(container, textvariable=status_var, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        actions = ttk.Frame(container, style="App.TFrame")
        actions.pack(fill="x", side="bottom", pady=(14, 0))
        ttk.Button(actions, text="Cancelar", width=14, command=window.destroy).pack(side="right")
        ttk.Button(actions, text="Salvar", width=14, style="Accent.TButton", command=lambda: self.save_text_overlay_from_window(window, overlay, text_var, size_var, status_var, family_var, bold_var, italic_var, color_var, align_var)).pack(side="right", padx=(0, 8))
        window.bind("<Escape>", lambda _event: window.destroy())
        window.bind("<Return>", lambda _event: self.save_text_overlay_from_window(window, overlay, text_var, size_var, status_var, family_var, bold_var, italic_var, color_var, align_var))
        text_entry.focus_set()
        self._finish_dialog(window, 560, 520)
        window.grab_set()

    def _choose_text_color(self, color_var: tk.StringVar) -> None:
        color = colorchooser.askcolor(color=color_var.get(), title="Cor do texto")
        if color and color[1]:
            color_var.set(color[1])

    def save_text_overlay_from_window(
        self,
        window: tk.Toplevel,
        overlay: dict[str, object] | None,
        text_var: tk.StringVar,
        size_var: tk.IntVar,
        status_var: tk.StringVar,
        family_var: tk.StringVar,
        bold_var: tk.BooleanVar,
        italic_var: tk.BooleanVar,
        color_var: tk.StringVar,
        align_var: tk.StringVar,
    ) -> None:
        text = text_var.get().strip()
        if not text:
            status_var.set("Digite um texto.")
            return
        try:
            font_size = max(6, int(size_var.get()))
        except (tk.TclError, ValueError):
            status_var.set("Revise o tamanho.")
            return
        width, height = self._canvas_size_px()
        if overlay is None:
            overlay = {
                "id": self._new_overlay_id(),
                "type": "text",
                "text": text,
                "x": round(width * 0.1),
                "y": round(height * 0.1),
                "w": max(120, round(width * 0.35)),
                "h": max(44, font_size + 12),
                "font_size": font_size,
                "font_family": family_var.get(),
                "bold": bool(bold_var.get()),
                "italic": bool(italic_var.get()),
                "color": color_var.get(),
                "align": align_var.get(),
                "rotation": 0,
            }
            self._current_overlays().append(overlay)
            self.status_message.set("Texto adicionado como camada.")
        else:
            overlay["text"] = text
            overlay["font_size"] = font_size
            overlay["h"] = max(float(overlay.get("h", 44)), font_size + 12)
            self.status_message.set("Texto atualizado.")
        overlay["name"] = str(text[:24] or "Texto")
        overlay["font_family"] = family_var.get()
        overlay["bold"] = bool(bold_var.get())
        overlay["italic"] = bool(italic_var.get())
        overlay["color"] = color_var.get()
        overlay["align"] = align_var.get()
        self._autosize_text_overlay(overlay)
        self.selected_overlay_id = str(overlay["id"])
        window.destroy()
        self._sync_layer_panel()
        self.schedule_preview()

    def add_image_overlay(self) -> None:
        if not self._require_document_for_layer():
            return
        path = filedialog.askopenfilename(
            title="Adicionar imagem",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("Todos", "*.*"),
            ],
        )
        if not path:
            return
        source = normalize_input_path(path)
        if not source.is_file():
            return
        width, height = self._canvas_size_px()
        try:
            with Image.open(source) as img:
                ratio = min(width * 0.35 / img.width, height * 0.35 / img.height, 1.0)
                overlay_w = max(1, round(img.width * ratio))
                overlay_h = max(1, round(img.height * ratio))
        except Exception as exc:
            messagebox.showerror("Camadas", f"Não foi possível abrir a imagem:\n{exc}")
            return
        overlay = {
            "id": self._new_overlay_id(),
            "type": "image",
            "name": source.name,
            "path": str(source),
            "x": round(width * 0.1),
            "y": round(height * 0.1),
            "w": overlay_w,
            "h": overlay_h,
            "rotation": 0,
        }
        self._current_overlays().append(overlay)
        self.selected_overlay_id = str(overlay["id"])
        self.status_message.set("Imagem adicionada como camada.")
        self._sync_layer_panel()
        self.schedule_preview()

    def open_counter_window(self, overlay: dict[str, object] | None = None) -> None:
        if not self._require_document_for_layer():
            return
        if hasattr(self, "counter_window") and self.counter_window.winfo_exists():
            if self.counter_window.winfo_children():
                self.counter_window.lift()
                return
            self.counter_window.destroy()

        editing = overlay is not None
        window = tk.Toplevel(self.root)
        self.counter_window = window
        window.withdraw()
        try:
            window.title("Editar numeração" if editing else "Numeração")
            window.geometry("520x460")
            window.minsize(500, 420)
            window.transient(self.root)
            window.configure(bg="#f1f3f4")

            start_var = tk.IntVar(value=int(overlay.get("start", 1)) if overlay else 1)
            end_var = tk.IntVar(value=int(overlay.get("end", 1500)) if overlay else 1500)
            digits_var = tk.IntVar(value=int(overlay.get("digits", 0)) if overlay else 0)
            prefix_var = tk.StringVar(value=str(overlay.get("prefix", "")) if overlay else "")
            suffix_var = tk.StringVar(value=str(overlay.get("suffix", "")) if overlay else "")
            size_var = tk.IntVar(value=int(overlay.get("font_size", 28)) if overlay else 28)
            status_var = tk.StringVar(value="A camada será criada na página atual.")

            container = ttk.Frame(window, padding=12, style="App.TFrame")
            container.pack(fill="both", expand=True)
            ttk.Label(container, text="Numeração", style="Title.TLabel").pack(anchor="w")
            ttk.Label(container, text="Crie comandas/etiquetas sequenciais.", style="Muted.TLabel").pack(anchor="w", pady=(2, 12))

            form = ttk.Frame(container, style="App.TFrame")
            form.pack(fill="x")
            ttk.Label(form, text="Início").grid(row=0, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Spinbox(form, from_=0, to=999999, increment=1, textvariable=start_var, width=14).grid(row=0, column=1, sticky="w", pady=5)
            ttk.Label(form, text="Fim").grid(row=1, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Spinbox(form, from_=0, to=999999, increment=1, textvariable=end_var, width=14).grid(row=1, column=1, sticky="w", pady=5)
            ttk.Label(form, text="Zeros").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Spinbox(form, from_=0, to=12, increment=1, textvariable=digits_var, width=14).grid(row=2, column=1, sticky="w", pady=5)
            ttk.Label(form, text="Prefixo").grid(row=3, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Entry(form, textvariable=prefix_var).grid(row=3, column=1, sticky="ew", pady=5)
            ttk.Label(form, text="Sufixo").grid(row=4, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Entry(form, textvariable=suffix_var).grid(row=4, column=1, sticky="ew", pady=5)
            ttk.Label(form, text="Tamanho").grid(row=5, column=0, sticky="w", pady=5, padx=(0, 10))
            ttk.Spinbox(form, from_=6, to=300, increment=1, textvariable=size_var, width=14).grid(row=5, column=1, sticky="w", pady=5)
            form.columnconfigure(1, weight=1)

            ttk.Label(container, textvariable=status_var, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
            actions = ttk.Frame(container, style="App.TFrame")
            actions.pack(fill="x", side="bottom", pady=(14, 0))
            ttk.Button(actions, text="Cancelar", width=14, command=window.destroy).pack(side="right")
            ttk.Button(
                actions,
                text="Salvar" if editing else "Criar",
                width=14,
                style="Accent.TButton",
                command=lambda: self.add_counter_overlay_from_window(window, overlay, start_var, end_var, digits_var, prefix_var, suffix_var, size_var, status_var),
            ).pack(side="right", padx=(0, 8))
            window.bind("<Escape>", lambda _event: window.destroy())
            window.bind("<Return>", lambda _event: self.add_counter_overlay_from_window(window, overlay, start_var, end_var, digits_var, prefix_var, suffix_var, size_var, status_var))
            self._finish_dialog(window, 520, 460)
            window.grab_set()
        except Exception as exc:
            window.destroy()
            messagebox.showerror("Numeração", f"Não foi possível abrir o formulário:\n{exc}")

    def add_counter_overlay_from_window(
        self,
        window: tk.Toplevel,
        overlay: dict[str, object] | None,
        start_var: tk.IntVar,
        end_var: tk.IntVar,
        digits_var: tk.IntVar,
        prefix_var: tk.StringVar,
        suffix_var: tk.StringVar,
        size_var: tk.IntVar,
        status_var: tk.StringVar,
    ) -> None:
        try:
            start = int(start_var.get())
            end = int(end_var.get())
            digits = max(0, int(digits_var.get()))
            font_size = max(6, int(size_var.get()))
        except (tk.TclError, ValueError):
            status_var.set("Revise início, fim, zeros e tamanho.")
            return
        if end < start:
            status_var.set("O fim precisa ser maior ou igual ao início.")
            return
        if end - start + 1 > 10000:
            status_var.set("Limite inicial: até 10.000 folhas por sequência.")
            return
        width, height = self._canvas_size_px()
        if overlay is None:
            overlay = {
                "id": self._new_overlay_id(),
                "type": "counter",
                "name": "Numeracao",
                "x": round(width * 0.1),
                "y": round(height * 0.1),
                "w": max(120, round(width * 0.3)),
                "h": max(48, font_size + 12),
                "rotation": 0,
            }
            self._current_overlays().append(overlay)
            self.status_message.set(f"Numeração criada: {start} até {end}.")
        else:
            self.status_message.set(f"Numeração atualizada: {start} até {end}.")
        overlay["start"] = start
        overlay["end"] = end
        overlay["digits"] = digits
        overlay["prefix"] = prefix_var.get()
        overlay["suffix"] = suffix_var.get()
        overlay["font_size"] = font_size
        overlay["h"] = max(float(overlay.get("h", 48)), font_size + 12)
        self._autosize_text_overlay(overlay)
        self.selected_overlay_id = str(overlay["id"])
        window.destroy()
        self._sync_layer_panel()
        self.schedule_preview()

    def delete_selected_overlay(self) -> None:
        if not self.selected_overlay_id:
            return
        overlays = self._current_overlays()
        remaining = [overlay for overlay in overlays if overlay.get("id") != self.selected_overlay_id]
        if len(remaining) == len(overlays):
            return
        self._record_overlay_history()
        self.page_overlays[self.current_index] = remaining
        self.selected_overlay_id = None
        self.overlay_drag_start = None
        self.status_message.set("Camada removida.")
        self._sync_layer_panel()
        self.schedule_preview()

    def _selected_overlay(self) -> dict[str, object] | None:
        if not self.selected_overlay_id:
            return None
        for overlay in self._current_overlays():
            if overlay.get("id") == self.selected_overlay_id:
                return overlay
        return None

    def edit_selected_overlay(self) -> None:
        overlay = self._selected_overlay()
        if not overlay:
            self.status_message.set("Selecione uma camada para editar.")
            return
        if overlay.get("type") == "text":
            self.open_text_window(overlay)
        elif overlay.get("type") == "counter":
            self.open_counter_window(overlay)
        elif overlay.get("type") == "image":
            messagebox.showinfo("Camadas", "Imagem ainda permite mover/remover. Edição de imagem fica para a próxima etapa.")
        elif overlay.get("type") == "shape" and overlay.get("shape") in {"barcode", "qrcode"}:
            self._show_sidebar_tab("Camadas")
            self.status_message.set("Edite o conteúdo em Propriedades > Texto / dados e clique em Aplicar.")

    def _overlay_canvas_box(self, overlay: dict[str, object]) -> tuple[float, float, float, float] | None:
        if not self.preview_image_box:
            return None
        x1, y1, _x2, _y2 = self.preview_image_box
        border = 2
        scale = self.preview_scale
        ox = float(overlay.get("x", 0))
        oy = float(overlay.get("y", 0))
        ow = float(overlay.get("w", 1))
        oh = float(overlay.get("h", 1))
        return (x1 + border + ox * scale, y1 + border + oy * scale, x1 + border + (ox + ow) * scale, y1 + border + (oy + oh) * scale)

    def _overlay_at(self, x: int, y: int) -> dict[str, object] | None:
        for overlay in reversed(self._current_overlays()):
            if not overlay.get("visible", True):
                continue
            box = self._overlay_canvas_box(overlay)
            if not box:
                continue
            x1, y1, x2, y2 = box
            if x1 <= x <= x2 and y1 <= y <= y2:
                return overlay
        return None

    def _overlay_handle_at(self, overlay: dict[str, object], x: int, y: int) -> str | None:
        box = self._overlay_canvas_box(overlay)
        if not box:
            return None
        x1, y1, x2, y2 = box
        handles = {"se": (x2, y2), "rotate": ((x1 + x2) / 2, y1 - 24)}
        for name, (hx, hy) in handles.items():
            if abs(x - hx) <= 16 and abs(y - hy) <= 16:
                return name
        return None

    def _begin_overlay_handle_action(self, overlay: dict[str, object], handle: str, event) -> bool:
        if overlay.get("locked"):
            self.status_message.set("Camada bloqueada.")
            return True
        self.selected_overlay_id = str(overlay["id"])
        scale = max(self.preview_scale, 0.01)
        self._record_overlay_history()
        if handle == "se":
            self.overlay_resize_start = (
                event.x,
                event.y,
                float(overlay.get("w", 1)),
                float(overlay.get("h", 1)),
                scale,
                int(overlay.get("font_size", 24)),
                float(overlay.get("x", 0)),
                float(overlay.get("y", 0)),
            )
            self.preview_canvas.configure(cursor="sizing")
            self._sync_layer_panel()
            self._draw_selection_overlay()
            return True
        if handle == "rotate":
            self.overlay_rotate_start = (
                event.x,
                event.y,
                float(overlay.get("rotation", 0)),
                float(overlay.get("x", 0)),
                float(overlay.get("y", 0)),
                float(overlay.get("w", 1)),
                float(overlay.get("h", 1)),
                scale,
            )
            self.preview_canvas.configure(cursor="exchange")
            self._sync_layer_panel()
            self._draw_selection_overlay()
            return True
        return False

    def _toggle_preview_mode(self, _event=None) -> None:
        self.edit_mode.set("Rotacionar" if self.edit_mode.get() == "Redimensionar" else "Redimensionar")
        self._draw_selection_overlay()

    def _handle_preview_double_click(self, event) -> None:
        overlay = self._overlay_at(event.x, event.y)
        if overlay:
            self.selected_overlay_id = str(overlay["id"])
            self.overlay_drag_start = None
            self._draw_selection_overlay()
            self.edit_selected_overlay()
            return
        self._toggle_preview_mode()

    def _point_in_preview_box(self, x: int, y: int) -> bool:
        if not self.preview_content_box:
            return False
        x1, y1, x2, y2 = self.preview_content_box
        return x1 <= x <= x2 and y1 <= y <= y2

    def _preview_handle_at(self, x: int, y: int) -> str | None:
        if not self.preview_content_box:
            return None
        x1, y1, x2, y2 = self.preview_content_box
        handles = {
            "nw": (x1, y1),
            "ne": (x2, y1),
            "se": (x2, y2),
            "sw": (x1, y2),
        }
        for name, (hx, hy) in handles.items():
            if abs(x - hx) <= 8 and abs(y - hy) <= 8:
                return name
        return None

    def _start_preview_action(self, event) -> None:
        if not self._has_document():
            return
        if self.active_tool.get() == "text":
            self._create_text_at_event(event)
            self.set_active_tool("select")
            return
        if self.active_tool.get() in {"rect", "ellipse", "line", "barcode", "qrcode"}:
            self._create_shape_at_event(event, self.active_tool.get())
            return
        selected_overlay = self._selected_overlay()
        if selected_overlay:
            selected_handle = self._overlay_handle_at(selected_overlay, event.x, event.y)
            if selected_handle and self._begin_overlay_handle_action(selected_overlay, selected_handle, event):
                return
        overlay = self._overlay_at(event.x, event.y)
        if overlay:
            if overlay.get("locked"):
                self.status_message.set("Camada bloqueada.")
                return
            self.selected_overlay_id = str(overlay["id"])
            scale = max(self.preview_scale, 0.01)
            handle = self._overlay_handle_at(overlay, event.x, event.y)
            if handle and self._begin_overlay_handle_action(overlay, handle, event):
                self._sync_layer_panel()
                self._draw_selection_overlay()
                return
            self._record_overlay_history()
            self.overlay_drag_start = (event.x, event.y, float(overlay.get("x", 0)), float(overlay.get("y", 0)), scale)
            self.preview_canvas.configure(cursor="fleur")
            self._sync_layer_panel()
            self._draw_selection_overlay()
            return
        self.selected_overlay_id = None
        self._sync_layer_panel()
        handle = self._preview_handle_at(event.x, event.y)
        if self.edit_mode.get() == "Rotacionar":
            self._begin_interactive_adjustment()
            self.rotate_start = (event.x, event.y, int(self.rotation_degrees.get()))
            self.preview_canvas.configure(cursor="exchange")
            return
        if handle:
            self._begin_interactive_adjustment()
            self.resize_start = (
                handle,
                event.x,
                event.y,
                int(self.scale_x_percent.get()),
                int(self.scale_y_percent.get()),
                int(self.scale_uniform_percent.get()),
            )
            self.preview_canvas.configure(cursor="sizing")
            return
        if self._point_in_preview_box(event.x, event.y):
            self._begin_interactive_adjustment()
            self.drag_start = (event.x, event.y, int(self.offset_x_px.get()), int(self.offset_y_px.get()))
            self.preview_canvas.configure(cursor="fleur")

    def _drag_preview_action(self, event) -> None:
        if not self._has_document():
            return
        if self.rotate_start:
            start_x, start_y, start_angle = self.rotate_start
            cx, cy = self._preview_center()
            a0 = math.degrees(math.atan2(start_y - cy, start_x - cx))
            a1 = math.degrees(math.atan2(event.y - cy, event.x - cx))
            self.rotation_degrees.set(round(start_angle + a1 - a0))
            self._preview_interactive_adjustment()
            return
        if self.resize_start:
            handle, start_x, start_y, scale_x, scale_y, scale_uniform = self.resize_start
            dx = event.x - start_x
            dy = event.y - start_y
            direction_x = -1 if "w" in handle else 1
            direction_y = -1 if "n" in handle else 1
            if event.state & 0x0001:
                delta = round(((dx * direction_x) + (dy * direction_y)) / 3)
                self.scale_uniform_percent.set(max(10, min(300, scale_uniform + delta)))
            else:
                self.scale_x_percent.set(max(10, min(300, scale_x + round(dx * direction_x / 2))))
                self.scale_y_percent.set(max(10, min(300, scale_y + round(dy * direction_y / 2))))
            self._preview_interactive_adjustment()
            return
        if self.drag_start:
            start_x, start_y, offset_x, offset_y = self.drag_start
            scale = max(self.preview_scale, 0.01)
            self.offset_x_px.set(round(offset_x + (event.x - start_x) / scale))
            self.offset_y_px.set(round(offset_y + (event.y - start_y) / scale))
            self._preview_interactive_adjustment()
            return
        if self.overlay_drag_start and self.selected_overlay_id:
            start_x, start_y, overlay_x, overlay_y, scale = self.overlay_drag_start
            for overlay in self._current_overlays():
                if overlay.get("id") == self.selected_overlay_id:
                    overlay["x"] = round(self._snap_value(overlay_x + (event.x - start_x) / scale))
                    overlay["y"] = round(self._snap_value(overlay_y + (event.y - start_y) / scale))
                    self._sync_layer_panel(update_module=False, update_list=False)
                    self.schedule_preview()
                    return
        if self.overlay_resize_start and self.selected_overlay_id:
            start_x, start_y, start_w, start_h, scale, start_font_size, start_overlay_x, start_overlay_y = self.overlay_resize_start
            for overlay in self._current_overlays():
                if overlay.get("id") == self.selected_overlay_id:
                    dx = (event.x - start_x) / scale
                    dy = (event.y - start_y) / scale
                    from_center = bool(event.state & 0x0004)
                    aspect_locked = overlay.get("shape") in {"qrcode"} or bool(event.state & 0x0001)
                    raw_w = start_w + (dx * 2 if from_center else dx)
                    raw_h = start_h + (dy * 2 if from_center else dy)
                    if aspect_locked:
                        side = max(4, max(raw_w, raw_h))
                        raw_w = raw_h = side
                    new_w = max(4, round(self._snap_value(raw_w)))
                    new_h = max(4, round(self._snap_value(raw_h)))
                    if from_center:
                        overlay["x"] = round(self._snap_value(start_overlay_x - (new_w - start_w) / 2), 2)
                        overlay["y"] = round(self._snap_value(start_overlay_y - (new_h - start_h) / 2), 2)
                    if overlay.get("type") in {"text", "counter"}:
                        ratio_w = new_w / max(1, start_w)
                        ratio_h = new_h / max(1, start_h)
                        ratio = (ratio_w + ratio_h) / 2 if event.state & 0x0001 else max(ratio_w, ratio_h)
                        new_font_size = max(6, min(600, round(start_font_size * ratio)))
                        overlay["font_size"] = new_font_size
                        overlay["h"] = max(new_h, new_font_size + 12)
                        overlay["w"] = new_w
                    else:
                        overlay["w"] = new_w
                        overlay["h"] = new_h
                    self._sync_layer_panel(update_module=False, update_list=False)
                    self.schedule_preview()
                    return
        if self.overlay_rotate_start and self.selected_overlay_id:
            _sx, _sy, start_angle, ox, oy, ow, oh, scale = self.overlay_rotate_start
            for overlay in self._current_overlays():
                if overlay.get("id") == self.selected_overlay_id:
                    box = self._overlay_canvas_box(overlay)
                    if not box:
                        return
                    cx = (box[0] + box[2]) / 2
                    cy = (box[1] + box[3]) / 2
                    a0 = math.degrees(math.atan2(_sy - cy, _sx - cx))
                    a1 = math.degrees(math.atan2(event.y - cy, event.x - cx))
                    angle = (start_angle + a1 - a0) % 360
                    if event.state & 0x0004:
                        angle = round(angle / 15) * 15
                    overlay["rotation"] = round(angle, 1)
                    self._sync_layer_panel(update_module=False, update_list=False)
                    self.schedule_preview()
                    return

    def _end_preview_action(self, _event=None) -> None:
        had_interactive_adjustment = bool(self.drag_start or self.resize_start or self.rotate_start)
        self.drag_start = None
        self.resize_start = None
        self.rotate_start = None
        self.overlay_drag_start = None
        self.overlay_resize_start = None
        self.overlay_rotate_start = None
        if had_interactive_adjustment:
            self._commit_interactive_adjustment()
        self.preview_canvas.configure(cursor="")

    def _preview_center(self) -> tuple[float, float]:
        if not self.preview_content_box:
            return self.preview_canvas.winfo_width() / 2, self.preview_canvas.winfo_height() / 2
        x1, y1, x2, y2 = self.preview_content_box
        return (x1 + x2) / 2, (y1 + y2) / 2

    def _update_preview_cursor(self, event) -> None:
        if not self._has_document():
            return
        point = self._canvas_point_from_event(event)
        if point:
            dpi = max(1, int(self.dpi.get()))
            self.mouse_position.set(f"Mouse: {px_to_mm(round(point[0]), dpi):.1f} mm, {px_to_mm(round(point[1]), dpi):.1f} mm | Zoom {int(self.zoom_percent.get())}%")
        selected_overlay = self._selected_overlay()
        if selected_overlay and self._overlay_handle_at(selected_overlay, event.x, event.y) == "se":
            self.preview_canvas.configure(cursor="sizing")
        elif selected_overlay and self._overlay_handle_at(selected_overlay, event.x, event.y) == "rotate":
            self.preview_canvas.configure(cursor="exchange")
        elif self._overlay_at(event.x, event.y):
            self.preview_canvas.configure(cursor="fleur")
        elif self.edit_mode.get() == "Rotacionar" and self._point_in_preview_box(event.x, event.y):
            self.preview_canvas.configure(cursor="exchange")
        elif self._preview_handle_at(event.x, event.y):
            self.preview_canvas.configure(cursor="sizing")
        elif self._point_in_preview_box(event.x, event.y):
            self.preview_canvas.configure(cursor="fleur")
        else:
            self.preview_canvas.configure(cursor="")

    def _on_canvas_zoom(self, event) -> None:
        if event.state & 0x0004:
            delta = 10 if event.delta > 0 else -10
            self.zoom_percent.set(max(25, min(400, int(self.zoom_percent.get()) + delta)))
            self.schedule_preview()

    def _bind_auto_preview(self) -> None:
        self.dpi.trace_add("write", lambda *_args: self._on_dpi_changed())
        self.size_unit.trace_add("write", lambda *_args: self._on_unit_changed())
        self.size_width.trace_add("write", lambda *_args: self._on_size_changed())
        self.size_height.trace_add("write", lambda *_args: self._on_size_changed())
        for var in (
            self.margin_px,
            self.offset_x_px,
            self.offset_y_px,
            self.scale_x_percent,
            self.scale_y_percent,
            self.scale_uniform_percent,
            self.rotation_degrees,
            self.crop_left_percent,
            self.crop_right_percent,
            self.crop_top_percent,
            self.crop_bottom_percent,
            self.invert,
            self.auto_rotate,
            self.fit_mode,
        ):
            var.trace_add("write", lambda *_args: self._on_render_setting_changed())

    def _current_page_adjustment(self) -> dict[str, object]:
        return {
            "margin_px": int(self.margin_px.get()),
            "offset_x_px": int(self.offset_x_px.get()),
            "offset_y_px": int(self.offset_y_px.get()),
            "scale_x_percent": int(self.scale_x_percent.get()),
            "scale_y_percent": int(self.scale_y_percent.get()),
            "scale_uniform_percent": int(self.scale_uniform_percent.get()),
            "rotation_degrees": int(self.rotation_degrees.get()),
            "crop_left_percent": int(self.crop_left_percent.get()),
            "crop_right_percent": int(self.crop_right_percent.get()),
            "crop_top_percent": int(self.crop_top_percent.get()),
            "crop_bottom_percent": int(self.crop_bottom_percent.get()),
            "fit_mode": self.fit_mode.get(),
            "auto_rotate": bool(self.auto_rotate.get()),
        }

    def _set_page_adjustment(self, adjustment: dict[str, object]) -> None:
        self.history_paused = True
        self.loading_page_settings = True
        try:
            self.margin_px.set(int(adjustment["margin_px"]))
            self.offset_x_px.set(int(adjustment["offset_x_px"]))
            self.offset_y_px.set(int(adjustment["offset_y_px"]))
            self.scale_x_percent.set(int(adjustment["scale_x_percent"]))
            self.scale_y_percent.set(int(adjustment["scale_y_percent"]))
            self.scale_uniform_percent.set(int(adjustment["scale_uniform_percent"]))
            self.rotation_degrees.set(int(adjustment["rotation_degrees"]))
            self.crop_left_percent.set(int(adjustment.get("crop_left_percent", 0)))
            self.crop_right_percent.set(int(adjustment.get("crop_right_percent", 0)))
            self.crop_top_percent.set(int(adjustment.get("crop_top_percent", 0)))
            self.crop_bottom_percent.set(int(adjustment.get("crop_bottom_percent", 0)))
            self.fit_mode.set(str(adjustment["fit_mode"]))
            self.auto_rotate.set(bool(adjustment["auto_rotate"]))
        finally:
            self.loading_page_settings = False
            self.history_paused = False

    def _reset_edit_history(self) -> None:
        self.edit_history.reset(self._current_page_adjustment())
        self.overlay_undo_stack.clear()
        self.overlay_redo_stack.clear()
        self._update_history_buttons()

    def _record_edit_history(self) -> None:
        if self.history_paused:
            return
        self.edit_history.record(self._current_page_adjustment())
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        can_undo = self.edit_history.can_undo or bool(self.overlay_undo_stack)
        can_redo = self.edit_history.can_redo or bool(self.overlay_redo_stack)
        if hasattr(self, "undo_button"):
            self.undo_button.configure(state="normal" if can_undo else "disabled")
        if hasattr(self, "redo_button"):
            self.redo_button.configure(state="normal" if can_redo else "disabled")

    def _begin_interactive_adjustment(self) -> None:
        self.edit_history.begin_batch(self._current_page_adjustment())
        self.history_paused = True

    def _preview_interactive_adjustment(self) -> None:
        self._save_current_page_adjustment()
        self._update_calculated_px()
        self.schedule_preview()

    def _commit_interactive_adjustment(self) -> None:
        self.history_paused = False
        self.edit_history.commit_batch(self._current_page_adjustment())
        self._save_current_page_adjustment()
        self._update_history_buttons()
        self._update_calculated_px()
        self.schedule_preview()

    def undo_edit(self) -> None:
        if self.undo_overlay_edit():
            return
        previous = self.edit_history.undo(self._current_page_adjustment())
        if previous is None:
            self.status_message.set("Nada para desfazer")
            return
        self._set_page_adjustment(previous)
        self._save_current_page_adjustment()
        self._update_history_buttons()
        self._update_calculated_px()
        self.schedule_preview()
        self.status_message.set("Ajuste desfeito")

    def redo_edit(self) -> None:
        if self.redo_overlay_edit():
            return
        next_adjustment = self.edit_history.redo(self._current_page_adjustment())
        if next_adjustment is None:
            self.status_message.set("Nada para refazer")
            return
        self._set_page_adjustment(next_adjustment)
        self._save_current_page_adjustment()
        self._update_history_buttons()
        self._update_calculated_px()
        self.schedule_preview()
        self.status_message.set("Ajuste refeito")

    def _save_current_page_adjustment(self) -> None:
        if not self._has_document() or self.loading_page_settings:
            return
        self.page_adjustments[self.current_index] = self._current_page_adjustment()

    def _load_page_adjustment(self) -> None:
        if not self._has_document():
            return
        adjustment = self.page_adjustments.get(self.current_index)
        default_adjustment = self.default_page_adjustment or self._current_page_adjustment()
        self.loading_page_settings = True
        try:
            if adjustment is None:
                adjustment = default_adjustment
            if adjustment is not None:
                self._set_page_adjustment(adjustment)
        finally:
            self.loading_page_settings = False
        self._reset_edit_history()

    def _settings_from_adjustment(self, adjustment: dict[str, object]) -> RenderSettings:
        width_px, height_px = self._canvas_size_px()
        return RenderSettings(
            width_px=width_px,
            height_px=height_px,
            margin_px=int(adjustment["margin_px"]),
            offset_x_px=int(adjustment["offset_x_px"]),
            offset_y_px=int(adjustment["offset_y_px"]),
            fit_mode=str(adjustment["fit_mode"]),
            auto_rotate=bool(adjustment["auto_rotate"]),
            scale_x_percent=int(adjustment["scale_x_percent"]),
            scale_y_percent=int(adjustment["scale_y_percent"]),
            scale_uniform_percent=int(adjustment["scale_uniform_percent"]),
            rotation_degrees=int(adjustment["rotation_degrees"]),
            crop_left_percent=int(adjustment.get("crop_left_percent", 0)),
            crop_right_percent=int(adjustment.get("crop_right_percent", 0)),
            crop_top_percent=int(adjustment.get("crop_top_percent", 0)),
            crop_bottom_percent=int(adjustment.get("crop_bottom_percent", 0)),
        )

    def on_close(self) -> None:
        self.app_settings.last_printer = self.printer_name.get()
        self.app_settings.last_output_mode = self.output_mode.get()
        self.app_settings.last_project = str(self.project_path or "")
        self.app_settings.preferences["snap_enabled"] = bool(self.snap_enabled.get())
        self.app_settings.preferences["grid_size"] = int(self.grid_size.get())
        self.app_settings.preferences["show_grid"] = bool(self.show_grid.get())
        self.app_settings.preferences["show_rulers"] = bool(self.show_rulers.get())
        save_settings(self.app_settings)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        self.root.destroy()

    def apply_profile(self, name: str, refresh: bool = True) -> None:
        profile = get_profile(name)
        self.syncing = True
        try:
            self.page_adjustments = {}
            self.profile_name.set(profile.name)
            self.dpi.set(profile.dpi)
            self.width_mm = profile.width_mm
            self.height_mm = profile.height_mm
            self.size_unit.set("mm")
            self.margin_px.set(mm_to_px(profile.margin_mm, profile.dpi))
            self.offset_x_px.set(0)
            self.offset_y_px.set(0)
            self.scale_x_percent.set(100)
            self.scale_y_percent.set(100)
            self.scale_uniform_percent.set(100)
            self.rotation_degrees.set(0)
            self.crop_left_percent.set(0)
            self.crop_right_percent.set(0)
            self.crop_top_percent.set(0)
            self.crop_bottom_percent.set(0)
            self.fit_mode.set("contain")
            self.auto_rotate.set(True)
            self.invert.set(False)
            self._sync_size_fields_from_mm()
            self.default_page_adjustment = self._current_page_adjustment()
        finally:
            self.syncing = False
        if hasattr(self, "profile_tree") and self.profile_tree.exists(profile.name):
            self.profile_tree.selection_set(profile.name)
            self.profile_tree.focus(profile.name)
            self.profile_tree.see(profile.name)
        self._reset_edit_history()
        if refresh:
            self.schedule_preview()

    def _refresh_profile_controls(self, selected: str | None = None) -> None:
        profiles = all_profiles()
        names = [profile.name for profile in profiles]
        selected_name = selected or self.profile_name.get() or (names[0] if names else "")
        if hasattr(self, "profile_combo"):
            self.profile_combo.configure(values=names)
        if hasattr(self, "profile_tree"):
            for item in self.profile_tree.get_children():
                self.profile_tree.delete(item)
            for profile in profiles:
                marker = "Padrão" if is_builtin_profile(profile.name) else "Salvo"
                values = (f"{profile.width_mm:g} x {profile.height_mm:g} mm", f"{profile.dpi} | {marker}")
                self.profile_tree.insert("", "end", iid=profile.name, text=profile.name, values=values)
            if selected_name in names:
                self.profile_tree.selection_set(selected_name)
                self.profile_tree.focus(selected_name)
                self.profile_tree.see(selected_name)

    def open_profile_window(self) -> None:
        if hasattr(self, "profile_window") and self.profile_window.winfo_exists():
            self.profile_window.lift()
            return

        window = tk.Toplevel(self.root)
        window.title("Novo perfil")
        window.geometry("520x430")
        window.minsize(500, 390)
        window.transient(self.root)
        window.configure(bg="#f1f3f4")
        self.profile_window = window

        name_var = tk.StringVar(value="")
        width_var = tk.DoubleVar(value=round(self.width_mm, 2))
        height_var = tk.DoubleVar(value=round(self.height_mm, 2))
        dpi_var = tk.IntVar(value=max(1, int(self.dpi.get())))
        margin_var = tk.DoubleVar(value=round(px_to_mm(max(0, int(self.margin_px.get())), max(1, int(self.dpi.get()))), 2))
        status_var = tk.StringVar(value="Baseado nas medidas atuais.")

        container = ttk.Frame(window, padding=12, style="App.TFrame")
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Novo perfil", style="Title.TLabel").pack(anchor="w")
        ttk.Label(container, text="Salve uma medida para reutilizar depois.", style="Muted.TLabel").pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(container, style="App.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="Nome").grid(row=0, column=0, sticky="w", pady=5, padx=(0, 10))
        name_entry = ttk.Entry(form, textvariable=name_var)
        name_entry.grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Largura (mm)").grid(row=1, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Spinbox(form, from_=10, to=1000, increment=0.5, textvariable=width_var, width=14).grid(row=1, column=1, sticky="w", pady=5)
        ttk.Label(form, text="Altura (mm)").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Spinbox(form, from_=10, to=1500, increment=0.5, textvariable=height_var, width=14).grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(form, text="DPI").grid(row=3, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Spinbox(form, from_=150, to=600, increment=1, textvariable=dpi_var, width=14).grid(row=3, column=1, sticky="w", pady=5)
        ttk.Label(form, text="Margem (mm)").grid(row=4, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Spinbox(form, from_=0, to=50, increment=0.1, textvariable=margin_var, width=14).grid(row=4, column=1, sticky="w", pady=5)
        form.columnconfigure(1, weight=1)

        ttk.Label(container, textvariable=status_var, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        actions = ttk.Frame(container, style="App.TFrame")
        actions.pack(fill="x", side="bottom", pady=(14, 0))
        ttk.Button(actions, text="Cancelar", width=14, command=window.destroy).pack(side="right")
        ttk.Button(actions, text="Salvar", width=14, style="Accent.TButton", command=lambda: self.save_profile_from_window(window, name_var, width_var, height_var, dpi_var, margin_var, status_var)).pack(side="right", padx=(0, 8))
        window.bind("<Escape>", lambda _event: window.destroy())
        window.bind("<Return>", lambda _event: self.save_profile_from_window(window, name_var, width_var, height_var, dpi_var, margin_var, status_var))
        name_entry.focus_set()
        self._finish_dialog(window, 520, 430)
        window.grab_set()

    def save_profile_from_window(
        self,
        window: tk.Toplevel,
        name_var: tk.StringVar,
        width_var: tk.DoubleVar,
        height_var: tk.DoubleVar,
        dpi_var: tk.IntVar,
        margin_var: tk.DoubleVar,
        status_var: tk.StringVar,
    ) -> None:
        name = name_var.get().strip()
        if not name:
            status_var.set("Digite um nome para o perfil.")
            return
        if is_builtin_profile(name):
            status_var.set("Use outro nome: perfis padrão não são sobrescritos.")
            return
        try:
            width_mm = float(width_var.get())
            height_mm = float(height_var.get())
            dpi = int(dpi_var.get())
            margin_mm = float(margin_var.get())
        except (tk.TclError, ValueError):
            status_var.set("Revise os valores numéricos.")
            return
        if width_mm <= 0 or height_mm <= 0 or dpi <= 0 or margin_mm < 0:
            status_var.set("Medidas, DPI e margem precisam ser válidos.")
            return
        profile = LabelProfile(name, width_mm, height_mm, dpi, margin_mm)
        try:
            save_custom_profile(profile)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Perfis", f"Não foi possível salvar o perfil:\n{exc}")
            return
        self.profile_status.set(f"Perfil salvo: {name}")
        self._refresh_profile_controls(name)
        self.apply_profile(name)
        window.destroy()

    def delete_selected_profile(self) -> None:
        selection = self.profile_tree.selection()
        name = selection[0] if selection else self.profile_name.get()
        if not name:
            self.profile_status.set("Selecione um perfil salvo para excluir.")
            return
        if is_builtin_profile(name):
            self.profile_status.set("Perfis padrão não podem ser excluídos.")
            return
        if not messagebox.askyesno("Excluir perfil", f"Excluir o perfil salvo '{name}'?"):
            return
        if delete_custom_profile(name):
            self.profile_status.set(f"Perfil excluído: {name}")
            self._refresh_profile_controls("10x15")
            self.apply_profile("10x15")
        else:
            self.profile_status.set("Perfil salvo não encontrado.")

    def _on_profile_select(self, _event=None) -> None:
        selection = self.profile_tree.selection()
        if selection and selection[0] != self.profile_name.get():
            self.apply_profile(selection[0])

    def _on_profile_combo_select(self, _event=None) -> None:
        if self.profile_name.get():
            self.apply_profile(self.profile_name.get())

    def _on_dpi_changed(self) -> None:
        if self.syncing:
            return
        self.syncing = True
        try:
            self._sync_size_fields_from_mm()
        finally:
            self.syncing = False
        self._update_calculated_px()
        self.schedule_preview()

    def _on_unit_changed(self) -> None:
        if self.syncing:
            return
        self.syncing = True
        try:
            self._sync_size_fields_from_mm()
        finally:
            self.syncing = False
        self.schedule_preview()

    def _on_size_changed(self) -> None:
        if self.syncing:
            return
        self._sync_mm_from_size_fields()
        self._update_calculated_px()
        self.schedule_preview()

    def _on_render_setting_changed(self) -> None:
        if self.syncing or self.loading_page_settings or self.history_paused:
            return
        self._record_edit_history()
        self._save_current_page_adjustment()
        self._update_calculated_px()
        self.schedule_preview()

    def _sync_mm_from_size_fields(self) -> None:
        try:
            width = float(self.size_width.get())
            height = float(self.size_height.get())
            dpi = int(self.dpi.get())
        except (tk.TclError, ValueError):
            return

        if dpi <= 0:
            return

        unit = self.size_unit.get()
        if unit == "px":
            self.width_mm = px_to_mm(round(width), dpi)
            self.height_mm = px_to_mm(round(height), dpi)
        elif unit == "cm":
            self.width_mm = width * 10.0
            self.height_mm = height * 10.0
        else:
            self.width_mm = width
            self.height_mm = height

    def _sync_size_fields_from_mm(self) -> None:
        self._configure_size_fields()
        unit = self.size_unit.get()
        dpi = int(self.dpi.get())
        if unit == "px":
            self.size_width.set(mm_to_px(self.width_mm, dpi))
            self.size_height.set(mm_to_px(self.height_mm, dpi))
        elif unit == "cm":
            self.size_width.set(round(self.width_mm / 10.0, 2))
            self.size_height.set(round(self.height_mm / 10.0, 2))
        else:
            self.size_width.set(round(self.width_mm, 2))
            self.size_height.set(round(self.height_mm, 2))
        self._update_calculated_px()

    def _configure_size_fields(self) -> None:
        unit = self.size_unit.get()
        if unit == "px":
            self.size1_label.configure(text="Largura (px)")
            self.size2_label.configure(text="Altura (px)")
            self.size1_spin.configure(from_=100, to=10000, increment=1)
            self.size2_spin.configure(from_=100, to=14000, increment=1)
        elif unit == "cm":
            self.size1_label.configure(text="Largura (cm)")
            self.size2_label.configure(text="Altura (cm)")
            self.size1_spin.configure(from_=1, to=100, increment=0.1)
            self.size2_spin.configure(from_=1, to=150, increment=0.1)
        else:
            self.size1_label.configure(text="Largura (mm)")
            self.size2_label.configure(text="Altura (mm)")
            self.size1_spin.configure(from_=10, to=1000, increment=0.5)
            self.size2_spin.configure(from_=10, to=1500, increment=0.5)

    def _update_calculated_px(self) -> None:
        width, height = self._canvas_size_px()
        self.calculated_px.set(f"{width} x {height}")

    def _canvas_size_px(self) -> tuple[int, int]:
        dpi = max(1, int(self.dpi.get()))
        return mm_to_px(self.width_mm, dpi), mm_to_px(self.height_mm, dpi)

    def current_render_settings(self) -> RenderSettings:
        return self._settings_from_adjustment(self._current_page_adjustment())

    def render_settings_for_index(self, index: int) -> RenderSettings:
        return self._settings_from_adjustment(self.page_adjustments.get(index, self._current_page_adjustment()))

    def reset_scale(self) -> None:
        self.scale_x_percent.set(100)
        self.scale_y_percent.set(100)
        self.scale_uniform_percent.set(100)
        self.rotation_degrees.set(0)

    def reset_crop(self) -> None:
        self.crop_left_percent.set(0)
        self.crop_right_percent.set(0)
        self.crop_top_percent.set(0)
        self.crop_bottom_percent.set(0)

    def pick_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Selecionar PDF/Imagem",
            filetypes=[
                ("Arquivos suportados", SUPPORTED_FILES),
                ("Todos", "*.*"),
            ],
        )
        if paths:
            self.load_files([normalize_input_path(path) for path in paths])

    def new_blank_project(self) -> None:
        self.page_sources = []
        self.project_source_files = []
        self.blank_document = True
        self.current_index = 0
        self.page_adjustments = {0: self._current_page_adjustment()}
        self.page_overlays = {}
        self.selected_overlay_id = None
        self.overlay_drag_start = None
        self.overlay_resize_start = None
        self.overlay_rotate_start = None
        self.project_path = None
        self.default_page_adjustment = self._current_page_adjustment()
        self._reset_edit_history()
        self._sync_layer_panel()
        self._show_sidebar_tab("Camadas")
        self.status_message.set("Novo projeto em branco criado.")
        self.refresh_preview()

    def _build_project(self) -> YnixProject:
        layers_by_page = {
            page: [Layer.from_overlay(normalize_overlay(overlay)) for overlay in overlays]
            for page, overlays in self.page_overlays.items()
        }
        return YnixProject(
            canvas=CanvasSpec(self.width_mm, self.height_mm, max(1, int(self.dpi.get()))),
            layers_by_page=layers_by_page,
            source_files=list(self.project_source_files or self.page_sources),
            page_adjustments={int(page): dict(data) for page, data in self.page_adjustments.items()},
            settings={
                "profile_name": self.profile_name.get(),
                "fit_mode": self.fit_mode.get(),
                "snap_enabled": bool(self.snap_enabled.get()),
                "grid_size": int(self.grid_size.get()),
                "blank_document": bool(self.blank_document),
            },
            print_config=PrintConfig(
                printer_name=self.printer_name.get(),
                output_mode=self.output_mode.get(),
                quality=self.print_quality.get(),
                invert=bool(self.invert.get()),
            ),
        )

    def save_project(self) -> None:
        if self.project_path is None:
            self.save_project_as()
            return
        try:
            save_project(self._build_project(), self.project_path)
        except Exception as exc:
            messagebox.showerror("Projeto", f"Não foi possível salvar o projeto:\n{exc}")
            return
        self.status_message.set(f"Projeto salvo: {self.project_path.name}")

    def save_project_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Salvar projeto Ynix",
            defaultextension=".ynix",
            filetypes=[("Projeto Ynix", "*.ynix"), ("JSON", "*.json"), ("Todos", "*.*")],
        )
        if not path:
            return
        self.project_path = Path(path)
        self.save_project()

    def open_project(self) -> None:
        path = filedialog.askopenfilename(
            title="Abrir projeto Ynix",
            filetypes=[("Projeto Ynix", "*.ynix"), ("JSON", "*.json"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            project = load_project(Path(path))
        except Exception as exc:
            messagebox.showerror("Projeto", f"Não foi possível abrir o projeto:\n{exc}")
            return
        self.project_path = Path(path)
        self._apply_project(project)

    def _apply_project(self, project: YnixProject) -> None:
        opened_path = self.project_path
        self.syncing = True
        try:
            self.width_mm = project.canvas.width_mm
            self.height_mm = project.canvas.height_mm
            self.dpi.set(project.canvas.dpi)
            self.size_unit.set("mm")
            self._sync_size_fields_from_mm()
            if project.print_config:
                self.printer_name.set(project.print_config.printer_name)
                self.output_mode.set(project.print_config.output_mode)
                self.print_quality.set(project.print_config.quality)
                self.invert.set(project.print_config.invert)
            self.snap_enabled.set(bool(project.settings.get("snap_enabled", self.snap_enabled.get())))
            self.grid_size.set(int(project.settings.get("grid_size", self.grid_size.get())))
        finally:
            self.syncing = False
        sources = [path for path in project.source_files if path.is_file()]
        if sources:
            self.load_files(sources)
        else:
            self.new_blank_project()
            self.blank_document = bool(project.settings.get("blank_document", True))
        self.project_path = opened_path
        self.page_adjustments = {int(page): dict(data) for page, data in project.page_adjustments.items()}
        self.page_overlays = {
            int(page): [layer.to_overlay() for layer in layers]
            for page, layers in project.layers_by_page.items()
        }
        self.selected_overlay_id = None
        self._load_page_adjustment()
        self._sync_layer_panel()
        self.refresh_preview()
        self.status_message.set(f"Projeto aberto: {self.project_path.name if self.project_path else ''}")

    def load_files(self, files: list[Path]) -> None:
        self.page_sources = []
        self.blank_document = False
        self.current_index = 0
        self.page_adjustments = {}
        self.page_overlays = {}
        self.selected_overlay_id = None
        self.overlay_drag_start = None
        files = [normalize_input_path(file) for file in files]
        self.project_source_files = list(files)
        skipped = [file for file in files if file.suffix.lower() not in SUPPORTED_SUFFIXES]
        files = [file for file in files if file.is_file() and file.suffix.lower() in SUPPORTED_SUFFIXES]
        for pdf_page in self.tmpdir.glob("*.png"):
            pdf_page.unlink(missing_ok=True)

        dpi = max(1, int(self.dpi.get()))
        for source in files:
            if source.suffix.lower() == ".pdf":
                base = self.tmpdir / source.stem
                subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(source), str(base)], check=True)
                self.page_sources.extend(sorted(self.tmpdir.glob(f"{source.stem}-*.png")))
            else:
                self.page_sources.append(source)
        if skipped:
            self.status_message.set(f"{len(skipped)} arquivo(s) ignorado(s): formato nao suportado.")
        if self.page_sources:
            first = files[0].name if files else "arquivo"
            self.status_message.set(f"{first} carregado - {len(self.page_sources)} página(s)")
        else:
            self.status_message.set("Nenhum arquivo carregado")
        self._reset_edit_history()
        self.refresh_preview()

    def prev_page(self) -> None:
        if not self._has_document():
            return
        self._save_current_page_adjustment()
        self.current_index = max(0, self.current_index - 1)
        self.selected_overlay_id = None
        self._load_page_adjustment()
        self.refresh_preview()

    def next_page(self) -> None:
        if not self._has_document():
            return
        self._save_current_page_adjustment()
        self.current_index = min(self._page_count() - 1, self.current_index + 1)
        self.selected_overlay_id = None
        self._load_page_adjustment()
        self.refresh_preview()

    def _current_fitted(self):
        if not self._has_document():
            return None
        if self.blank_document:
            return self._apply_overlays(self._base_canvas_image(), self.current_index)
        src = open_mono(self.page_sources[self.current_index])
        return self._apply_overlays(fit_image(src, self.current_render_settings()), self.current_index)

    def _fitted_for_index(self, index: int):
        if self.blank_document:
            return self._base_canvas_image()
        src = open_mono(self.page_sources[index])
        return fit_image(src, self.render_settings_for_index(index))

    def _font_for_size(self, size: int, family: str = "DejaVu Sans", bold: bool = False, italic: bool = False) -> ImageFont.ImageFont:
        style = ""
        if bold:
            style += "Bold"
        if italic:
            style += "Oblique"
        candidates = []
        if family:
            compact = family.replace(" ", "")
            candidates.extend(
                [
                    f"/usr/share/fonts/truetype/dejavu/{compact}-{style}.ttf",
                    f"/usr/share/fonts/truetype/dejavu/{compact}.ttf",
                    f"/usr/share/fonts/truetype/liberation2/{compact}-{style}.ttf",
                    f"/usr/share/fonts/truetype/liberation2/{compact}.ttf",
                ]
            )
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf" if bold and italic else "",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf" if italic else "",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
        for font_path in candidates:
            if not font_path:
                continue
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _measure_overlay_text(self, overlay: dict[str, object]) -> tuple[int, int]:
        font_size = max(6, int(overlay.get("font_size", 24)))
        font = self._font_for_size(
            font_size,
            str(overlay.get("font_family", "DejaVu Sans")),
            bool(overlay.get("bold", False)),
            bool(overlay.get("italic", False)),
        )
        if overlay.get("type") == "counter":
            text = self._format_counter_overlay(overlay)
        else:
            text = str(overlay.get("text", ""))
        probe = Image.new("L", (1, 1), 255)
        draw = ImageDraw.Draw(probe)
        try:
            box = draw.multiline_textbbox((0, 0), text or " ", font=font, spacing=4)
            return max(1, box[2] - box[0]), max(1, box[3] - box[1])
        except Exception:
            return max(1, len(text) * font_size // 2), max(1, font_size)

    def _autosize_text_overlay(self, overlay: dict[str, object], padding: int = 10) -> None:
        if overlay.get("type") not in {"text", "counter"}:
            return
        text_w, text_h = self._measure_overlay_text(overlay)
        width_px, height_px = self._canvas_size_px()
        x = max(0, float(overlay.get("x", 0)))
        y = max(0, float(overlay.get("y", 0)))
        desired_w = min(max(4, width_px - x), text_w + padding * 2)
        desired_h = min(max(4, height_px - y), text_h + padding * 2)
        overlay["w"] = max(float(overlay.get("w", 1)), desired_w)
        overlay["h"] = max(float(overlay.get("h", 1)), desired_h)

    def _text_fill_for_overlay(self, overlay: dict[str, object]) -> int:
        color = str(overlay.get("color", "#000000"))
        return self._mono_from_color(color)

    def _mono_from_color(self, color: str, default: int = 0) -> int:
        if color.startswith("#") and len(color) == 7:
            try:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                return 0 if (r * 0.299 + g * 0.587 + b * 0.114) < 180 else 255
            except ValueError:
                pass
        return default

    def _format_counter_overlay(self, overlay: dict[str, object], value: int | None = None) -> str:
        number = int(overlay.get("start", 1) if value is None else value)
        digits = max(0, int(overlay.get("digits", 0)))
        body = str(number).zfill(digits) if digits else str(number)
        return f"{overlay.get('prefix', '')}{body}{overlay.get('suffix', '')}"

    def _counter_overlay_for_index(self, index: int) -> dict[str, object] | None:
        for overlay in self.page_overlays.get(index, []):
            if overlay.get("type") == "counter":
                return overlay
        return None

    def _apply_overlays(self, img: Image.Image, index: int, counter_value: int | None = None) -> Image.Image:
        canvas = img.convert("L")
        for overlay in self.page_overlays.get(index, []):
            if not overlay.get("visible", True):
                continue
            x = round(float(overlay.get("x", 0)))
            y = round(float(overlay.get("y", 0)))
            w = max(1, round(float(overlay.get("w", 1))))
            h = max(1, round(float(overlay.get("h", 1))))
            opacity = max(0, min(100, int(float(overlay.get("opacity", 100)))))
            if opacity <= 0:
                continue
            if overlay.get("type") in {"text", "counter"}:
                layer_img = Image.new("L", (w, h), 255)
                draw = ImageDraw.Draw(layer_img)
                font_size = max(6, int(overlay.get("font_size", 24)))
                font = self._font_for_size(
                    font_size,
                    str(overlay.get("font_family", "DejaVu Sans")),
                    bool(overlay.get("bold", False)),
                    bool(overlay.get("italic", False)),
                )
                text = self._format_counter_overlay(overlay, counter_value) if overlay.get("type") == "counter" else str(overlay.get("text", ""))
                align = str(overlay.get("align", "left"))
                fill = self._text_fill_for_overlay(overlay)
                if align == "center":
                    anchor_x = w / 2
                    anchor = "ma"
                elif align == "right":
                    anchor_x = w
                    anchor = "ra"
                else:
                    anchor_x = 0
                    anchor = "la"
                draw.multiline_text((anchor_x, 0), text, fill=fill, font=font, spacing=4, align=align, anchor=anchor)
                angle = float(overlay.get("rotation", 0))
                if angle:
                    layer_img = layer_img.rotate(-angle, expand=True, fillcolor=255)
                if overlay.get("flip_x"):
                    layer_img = ImageOps.mirror(layer_img)
                if overlay.get("flip_y"):
                    layer_img = ImageOps.flip(layer_img)
                canvas.paste(layer_img, (x, y))
            elif overlay.get("type") == "image":
                path = Path(str(overlay.get("path", "")))
                if not path.is_file():
                    continue
                try:
                    layer = ImageOps.exif_transpose(Image.open(path)).convert("L")
                except Exception:
                    continue
                layer = layer.resize((w, h), Image.Resampling.LANCZOS).convert("1").convert("L")
                angle = float(overlay.get("rotation", 0))
                if angle:
                    layer = layer.rotate(-angle, expand=True, fillcolor=255)
                if overlay.get("flip_x"):
                    layer = ImageOps.mirror(layer)
                if overlay.get("flip_y"):
                    layer = ImageOps.flip(layer)
                canvas.paste(layer, (x, y))
            elif overlay.get("type") == "shape":
                layer = Image.new("L", (w, h), 255)
                mask = Image.new("1", (w, h), 0)
                draw = ImageDraw.Draw(layer)
                mask_draw = ImageDraw.Draw(mask)
                stroke = self._mono_from_color(str(overlay.get("stroke_color", overlay.get("color", "#000000"))), 0)
                fill_color = str(overlay.get("fill_color", "none"))
                has_fill = fill_color not in {"", "none", "None", "transparent"}
                fill = self._mono_from_color(fill_color, 255) if has_fill else None
                line_width = max(1, int(overlay.get("line_width", 3)))
                shape = str(overlay.get("shape", "rect"))
                inset = max(0, line_width // 2)
                if shape == "ellipse":
                    bbox = (inset, inset, max(inset, w - inset - 1), max(inset, h - inset - 1))
                    draw.ellipse(bbox, outline=stroke, fill=fill, width=line_width)
                    mask_draw.ellipse(bbox, outline=1, fill=1 if has_fill else 0, width=line_width)
                elif shape == "line":
                    y_mid = h // 2
                    draw.line((0, y_mid, max(0, w - 1), y_mid), fill=stroke, width=line_width)
                    mask_draw.line((0, y_mid, max(0, w - 1), y_mid), fill=1, width=line_width)
                elif shape == "barcode":
                    data = str(overlay.get("data", "YNIX"))
                    digest = hashlib.sha256(data.encode("utf-8")).digest()
                    cursor = 4
                    index = 0
                    while cursor < w - 4:
                        bar_w = 1 + digest[index % len(digest)] % 5
                        gap = 1 + digest[(index + 7) % len(digest)] % 3
                        rect = (cursor, 0, min(w, cursor + bar_w), h)
                        draw.rectangle(rect, fill=stroke)
                        mask_draw.rectangle(rect, fill=1)
                        cursor += bar_w + gap
                        index += 1
                elif shape == "qrcode":
                    result = render_qrcode_layer(
                        str(overlay.get("data", "YNIX")),
                        (w, h),
                        stroke=stroke,
                        fill=normalize_qr_fill(fill_color, self._mono_from_color),
                        module_scale=line_width,
                    )
                    layer = result.layer
                    mask = result.mask
                else:
                    bbox = (inset, inset, max(inset, w - inset - 1), max(inset, h - inset - 1))
                    draw.rectangle(bbox, outline=stroke, fill=fill, width=line_width)
                    mask_draw.rectangle(bbox, outline=1, fill=1 if has_fill else 0, width=line_width)
                angle = float(overlay.get("rotation", 0))
                if angle:
                    layer = layer.rotate(-angle, expand=True, fillcolor=255)
                    mask = mask.rotate(-angle, expand=True, fillcolor=0)
                if overlay.get("flip_x"):
                    layer = ImageOps.mirror(layer)
                    mask = ImageOps.mirror(mask)
                if overlay.get("flip_y"):
                    layer = ImageOps.flip(layer)
                    mask = ImageOps.flip(mask)
                canvas.paste(layer, (x, y), mask)
        return canvas.convert("1")

    def _composed_for_index(self, index: int, counter_value: int | None = None) -> Image.Image:
        return self._apply_overlays(self._fitted_for_index(index), index, counter_value)

    def schedule_preview(self) -> None:
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after_idle(self.refresh_preview)

    def refresh_preview(self) -> None:
        self.preview_job = None
        if not self._has_document():
            self.page_info.configure(text="Página 0/0")
            self.preview_image_box = None
            self.preview_content_box = None
            self._draw_empty_preview("Novo projeto em branco ou arraste um PDF/imagem.")
            self.status_message.set("Crie um projeto em branco ou abra um arquivo para começar")
            return

        if self.blank_document:
            result = self._base_fit_result()
        else:
            src = open_mono(self.page_sources[self.current_index])
            result = fit_image_with_meta(src, self.current_render_settings())
        img = self._apply_overlays(result.image, self.current_index)
        self.preview_image = img

        available_w = max(240, self.preview_canvas.winfo_width() - 20)
        available_h = max(240, self.preview_canvas.winfo_height() - 20)
        ratio = min(available_w / img.width, available_h / img.height, 1.0) * max(10, int(self.zoom_percent.get())) / 100
        self.preview_scale = ratio
        show_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
        resampling = Image.Resampling.LANCZOS if ratio < 1 else Image.Resampling.NEAREST
        show = img.convert("L").resize(show_size, resampling)
        show = ImageOps.expand(show, border=1, fill=180)
        self.preview_tk = ImageTk.PhotoImage(show)
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        ruler_left = 34 if self.show_rulers.get() else 0
        ruler_top = 22 if self.show_rulers.get() else 0
        x = max(ruler_left + 16, (canvas_w - show.width + ruler_left) // 2)
        y = max(ruler_top + 16, (canvas_h - show.height + ruler_top) // 2)
        self.preview_image_box = (x, y, x + show.width, y + show.height)
        border = 2
        bx1, by1, bx2, by2 = result.content_box
        bx1 = max(0, min(img.width, bx1))
        by1 = max(0, min(img.height, by1))
        bx2 = max(0, min(img.width, bx2))
        by2 = max(0, min(img.height, by2))
        self.preview_content_box = (
            x + border + bx1 * ratio,
            y + border + by1 * ratio,
            x + border + bx2 * ratio,
            y + border + by2 * ratio,
        )
        self.preview_canvas.delete("all")
        self.preview_canvas.create_rectangle(x + 7, y + 8, x + show.width + 7, y + show.height + 8, fill="#151515", outline="", tags=("workspace",))
        self.preview_canvas.create_image(x, y, image=self.preview_tk, anchor="nw", tags=("preview_image",))
        self._draw_workspace_guides()
        self._draw_selection_overlay()
        self._sync_layer_panel(update_module=False)
        self.page_info.configure(text=f"Página {self.current_index + 1}/{self._page_count()}")

    def _draw_empty_preview(self, text: str) -> None:
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(
            self.preview_canvas.winfo_width() / 2,
            self.preview_canvas.winfo_height() / 2,
            text=text,
            fill="#dadce0",
            font=("DejaVu Sans", 11),
            width=max(200, self.preview_canvas.winfo_width() - 80),
        )

    def _draw_workspace_guides(self) -> None:
        self.preview_canvas.delete("workspace")
        if not self.preview_image_box:
            return
        x1, y1, x2, y2 = self.preview_image_box
        border = 1
        label_x1 = x1 + border
        label_y1 = y1 + border
        label_x2 = x2 - border
        label_y2 = y2 - border
        scale = max(self.preview_scale, 0.01)
        width_px, height_px = self._canvas_size_px()
        if self.show_grid.get():
            dpi = max(1, int(self.dpi.get()))
            minor_step = max(mm_to_px(5, dpi), int(self.grid_size.get()))
            major_step = max(minor_step, mm_to_px(25, dpi))
            for gx in range(0, width_px + 1, minor_step):
                x = label_x1 + gx * scale
                if label_x1 <= x <= label_x2:
                    self.preview_canvas.create_line(x, label_y1, x, label_y2, fill="#eef2f5", tags=("workspace",))
            for gy in range(0, height_px + 1, minor_step):
                y = label_y1 + gy * scale
                if label_y1 <= y <= label_y2:
                    self.preview_canvas.create_line(label_x1, y, label_x2, y, fill="#eef2f5", tags=("workspace",))
            for gx in range(0, width_px + 1, major_step):
                x = label_x1 + gx * scale
                if label_x1 <= x <= label_x2:
                    self.preview_canvas.create_line(x, label_y1, x, label_y2, fill="#dde6ee", tags=("workspace",))
            for gy in range(0, height_px + 1, major_step):
                y = label_y1 + gy * scale
                if label_y1 <= y <= label_y2:
                    self.preview_canvas.create_line(label_x1, y, label_x2, y, fill="#dde6ee", tags=("workspace",))
            cx = label_x1 + width_px * scale / 2
            cy = label_y1 + height_px * scale / 2
            self.preview_canvas.create_line(cx, label_y1, cx, label_y2, fill="#b8cdf8", dash=(6, 6), tags=("workspace",))
            self.preview_canvas.create_line(label_x1, cy, label_x2, cy, fill="#b8cdf8", dash=(6, 6), tags=("workspace",))
        else:
            cx = label_x1 + width_px * scale / 2
            cy = label_y1 + height_px * scale / 2
            tick = 8
            self.preview_canvas.create_line(cx - tick, cy, cx + tick, cy, fill="#d6dce2", tags=("workspace",))
            self.preview_canvas.create_line(cx, cy - tick, cx, cy + tick, fill="#d6dce2", tags=("workspace",))
        if self.show_rulers.get():
            top = max(0, label_y1 - 20)
            left = max(0, label_x1 - 30)
            self.preview_canvas.create_rectangle(label_x1, top, label_x2, label_y1 - 3, fill="#242628", outline="", tags=("workspace",))
            self.preview_canvas.create_rectangle(left, label_y1, label_x1 - 3, label_y2, fill="#242628", outline="", tags=("workspace",))
            mark_step = 25 if self.width_mm > 80 else 10
            for mm in range(0, int(self.width_mm) + 1, mark_step):
                x = label_x1 + mm_to_px(mm, max(1, int(self.dpi.get()))) * scale
                if x <= label_x2:
                    self.preview_canvas.create_line(x, label_y1 - 8, x, label_y1 - 3, fill="#9aa0a6", tags=("workspace",))
                    if mm:
                        self.preview_canvas.create_text(x + 3, label_y1 - 14, text=str(mm), fill="#cfd3d7", anchor="w", font=("DejaVu Sans", 7), tags=("workspace",))
            mark_step_y = 25 if self.height_mm > 80 else 10
            for mm in range(0, int(self.height_mm) + 1, mark_step_y):
                y = label_y1 + mm_to_px(mm, max(1, int(self.dpi.get()))) * scale
                if y <= label_y2:
                    self.preview_canvas.create_line(label_x1 - 8, y, label_x1 - 3, y, fill="#9aa0a6", tags=("workspace",))
                    if mm:
                        self.preview_canvas.create_text(label_x1 - 27, y + 2, text=str(mm), fill="#cfd3d7", anchor="w", font=("DejaVu Sans", 7), tags=("workspace",))

    def _draw_selection_overlay(self) -> None:
        self.preview_canvas.delete("selection")
        if not self.preview_content_box:
            return
        x1, y1, x2, y2 = self.preview_content_box
        color = "#fbbc04" if self.edit_mode.get() == "Rotacionar" else "#8ab4f8"
        self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=2, tags=("selection",))
        handle_size = 7
        for hx, hy in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
            self.preview_canvas.create_rectangle(
                hx - handle_size,
                hy - handle_size,
                hx + handle_size,
                hy + handle_size,
                fill="#ffffff",
                outline=color,
                width=2,
                tags=("selection",),
            )
        if self.edit_mode.get() == "Rotacionar":
            cx, cy = self._preview_center()
            self.preview_canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=color, outline=color, tags=("selection",))
            self.preview_canvas.create_text(
                x1,
                max(12, y1 - 14),
                text=f"Rotacionar: {self.rotation_degrees.get()}°",
                fill=color,
                anchor="w",
                tags=("selection",),
            )
        for overlay in self._current_overlays():
            box = self._overlay_canvas_box(overlay)
            if not box:
                continue
            ox1, oy1, ox2, oy2 = box
            selected = overlay.get("id") == self.selected_overlay_id
            outline = "#34a853" if selected else "#9aa0a6"
            dash = () if selected else (4, 3)
            self.preview_canvas.create_rectangle(ox1, oy1, ox2, oy2, outline=outline, width=2 if selected else 1, dash=dash, tags=("selection",))
            if selected:
                self.preview_canvas.create_text(ox1, max(12, oy1 - 14), text="Camada", fill=outline, anchor="w", tags=("selection",))
                self.preview_canvas.create_rectangle(ox2 - 7, oy2 - 7, ox2 + 7, oy2 + 7, fill="#ffffff", outline=outline, width=2, tags=("selection",))
                rx = (ox1 + ox2) / 2
                ry = oy1 - 24
                self.preview_canvas.create_line(rx, oy1, rx, ry, fill=outline, width=2, tags=("selection",))
                self.preview_canvas.create_oval(rx - 7, ry - 7, rx + 7, ry + 7, fill="#ffffff", outline=outline, width=2, tags=("selection",))

    def _payload_for_index(self, index: int, counter_value: int | None = None) -> bytes:
        img = self._composed_for_index(index, counter_value)
        quality = get_quality(self.print_quality.get())
        return build_tspl(
            img,
            self.width_mm,
            self.height_mm,
            invert=not bool(self.invert.get()),
            speed=quality.speed,
            density=quality.density,
        )

    def _normal_document_for_index(self, index: int, counter_value: int | None = None) -> bytes:
        img = self._composed_for_index(index, counter_value).convert("L")
        out = BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    def export_current(self, fmt: str) -> None:
        if not self._has_document():
            return
        suffix = ".pdf" if fmt == "pdf" else ".png"
        path = filedialog.asksaveasfilename(
            title=f"Exportar {fmt.upper()}",
            defaultextension=suffix,
            filetypes=[(fmt.upper(), f"*{suffix}"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            img = self._composed_for_index(self.current_index).convert("RGB")
            if fmt == "pdf":
                img.save(path, "PDF", resolution=max(1, int(self.dpi.get())))
            else:
                img.save(path, "PNG")
            self.status_message.set(f"Exportado: {Path(path).name}")
        except Exception as exc:
            messagebox.showerror("Exportar", str(exc))

    def _enqueue_print_job(self, title: str, indexes: list[int]) -> None:
        if not self._has_document():
            return
        if not indexes:
            messagebox.showwarning("Impressão térmica", "Nenhuma página selecionada para impressão.")
            return
        try:
            normal_mode = self.output_mode.get() == "Impressora normal"
            payloads = [self._normal_document_for_index(index) if normal_mode else self._payload_for_index(index) for index in indexes]
            job = self.print_queue.add(
                title,
                self.printer_name.get(),
                self.print_quality.get(),
                payloads,
                output_mode="normal" if normal_mode else "tspl",
            )
            self._show_sidebar_tab("Fila")
            self._select_queue_job_when_ready(job.id)
            self.status_message.set(f"Trabalho #{job.id} adicionado na fila.")
            self.refresh_preview()
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def print_counter_sequence(self) -> None:
        if not self._has_document():
            return
        counter = self._counter_overlay_for_index(self.current_index)
        if not counter:
            messagebox.showinfo("Numeração", "Adicione uma camada de numeração na página atual.")
            return
        start = int(counter.get("start", 1))
        end = int(counter.get("end", start))
        values = list(range(start, end + 1))
        if not values:
            return
        if len(values) > 2000 and not messagebox.askyesno("Numeração", f"Gerar {len(values)} folhas para a fila?"):
            return
        try:
            normal_mode = self.output_mode.get() == "Impressora normal"
            payloads = [
                self._normal_document_for_index(self.current_index, value) if normal_mode else self._payload_for_index(self.current_index, value)
                for value in values
            ]
            job = self.print_queue.add(
                f"Numeração {start}-{end}",
                self.printer_name.get(),
                self.print_quality.get(),
                payloads,
                output_mode="normal" if normal_mode else "tspl",
            )
            self._show_sidebar_tab("Fila")
            self._select_queue_job_when_ready(job.id)
            self.status_message.set(f"Numeração #{job.id}: {len(values)} folha(s) adicionadas.")
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))

    def print_current(self) -> None:
        if not self._has_document():
            return
        self._enqueue_print_job(f"Página {self.current_index + 1}", [self.current_index])

    def print_all(self) -> None:
        if not self._has_document():
            return
        self._enqueue_print_job("Todas as páginas", self._document_page_indexes())

    def _parse_page_range(self, expr: str) -> list[int]:
        expr = expr.strip()
        if not expr:
            return []

        pages = set()
        max_page = self._page_count()
        for part in expr.split(","):
            token = part.strip()
            if not token:
                continue
            match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
                if start > end:
                    start, end = end, start
                pages.update(page - 1 for page in range(start, end + 1) if 1 <= page <= max_page)
            elif token.isdigit():
                page = int(token)
                if 1 <= page <= max_page:
                    pages.add(page - 1)
            else:
                raise ValueError(f"Faixa inválida: {token}")
        return sorted(pages)

    def print_range(self) -> None:
        if not self._has_document():
            return
        try:
            indexes = self._parse_page_range(self.page_range.get())
            if not indexes:
                messagebox.showwarning("Impressão térmica", "Informe páginas válidas (ex: 1,3-5).")
                return
            self._enqueue_print_job(f"Faixa {self.page_range.get().strip()}", indexes)
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
