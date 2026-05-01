from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import math
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from urllib.parse import unquote, urlparse

from PIL import Image, ImageOps, ImageTk

from .geometry import mm_to_px, px_to_mm
from .imaging import RenderSettings, fit_image, fit_image_with_meta, open_mono
from .installer import DEFAULT_TOMATE_NAME
from .print_queue import PrintJob, PrintQueue
from .printers import DEFAULT_CONTRACT, contract_by_display_name, contract_names, list_printers
from .profiles import LabelProfile, all_profiles, delete_custom_profile, get_profile, is_builtin_profile, profile_names, save_custom_profile
from .quality import get_quality, quality_names
from .tspl import build_tspl


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
        self.page_sources: list[Path] = []
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
        self.drag_start = None
        self.resize_start = None
        self.rotate_start = None
        self.edit_mode = tk.StringVar(value="Redimensionar")
        self.detected_printers = list_printers()
        if self.detected_printers:
            self.printer_name.set(self.detected_printers[0])
        self.print_queue = PrintQueue(self._queue_job_changed)

        self._build_ui()
        self._bind_auto_preview()
        self.apply_profile("10x15", refresh=False)
        if self.files:
            self.load_files(self.files)
        else:
            self.refresh_preview()

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

    def _build_ui(self) -> None:
        self._configure_style()
        self._build_menu()

        main = ttk.Frame(self.root, padding=12, style="App.TFrame")
        main.pack(fill="both", expand=True)

        toolbar = ttk.Frame(main, style="Toolbar.TFrame")
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="Abrir arquivos", style="Accent.TButton", command=self.pick_files).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=10)
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
        self.preview_canvas.bind("<Double-Button-1>", self._toggle_preview_mode)
        self.preview_canvas.bind("<Motion>", self._update_preview_cursor)
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
            "Perfis": ScrollableSidebarPage(pages),
            "Ajustes": ScrollableSidebarPage(pages),
            "Impressão": ScrollableSidebarPage(pages),
            "Fila": ScrollableSidebarPage(pages),
        }
        self.sidebar_tab_buttons = {}
        tab_rows = (("Perfis", "Ajustes"), ("Impressão", "Fila"))
        for row_index, tab_names in enumerate(tab_rows):
            row_frame = ttk.Frame(tabbar, style="App.TFrame")
            row_frame.pack(fill="x", pady=(0, 4 if row_index == 0 else 0))
            for column_index, tab_name in enumerate(tab_names):
                button = ttk.Button(row_frame, text=tab_name, style="Tab.TButton", command=lambda name=tab_name: self._show_sidebar_tab(name))
                button.grid(row=0, column=column_index, sticky="ew", padx=(0 if column_index == 0 else 4, 0))
                row_frame.columnconfigure(column_index, weight=1, uniform=f"tabs-{row_index}")
                self.sidebar_tab_buttons[tab_name] = button

        profiles_tab = self.sidebar_pages["Perfis"].inner
        setup_tab = self.sidebar_pages["Ajustes"].inner
        print_tab = self.sidebar_pages["Impressão"].inner
        queue_tab = self.sidebar_pages["Fila"].inner

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
        file_menu.add_command(label="Abrir arquivos...", accelerator="Ctrl+O", command=self.pick_files)
        file_menu.add_separator()
        file_menu.add_command(label="Sair", command=self.on_close)
        menubar.add_cascade(label="Arquivo", menu=file_menu)

        print_menu = tk.Menu(menubar, tearoff=False)
        print_menu.add_command(label="Imprimir página atual", accelerator="Ctrl+P", command=self.print_current)
        print_menu.add_command(label="Imprimir todas as páginas", accelerator="Ctrl+Shift+P", command=self.print_all)
        print_menu.add_command(label="Imprimir faixa", command=self.print_range)
        menubar.add_cascade(label="Impressão", menu=print_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Página anterior", accelerator="Ctrl+←", command=self.prev_page)
        view_menu.add_command(label="Próxima página", accelerator="Ctrl+→", command=self.next_page)
        view_menu.add_separator()
        view_menu.add_command(label="Alternar redimensionar/rotacionar", accelerator="Ctrl+R", command=self._toggle_preview_mode)
        view_menu.add_command(label="Redefinir escala/rotação", accelerator="Ctrl+0", command=self.reset_scale)
        view_menu.add_command(label="Limpar corte", accelerator="Ctrl+Shift+0", command=self.reset_crop)
        menubar.add_cascade(label="Navegação", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Driver Tomate / CUPS...", command=self.open_driver_window)
        tools_menu.add_command(label="Verificar driver agora", command=lambda: self.open_driver_window(refresh=True))
        menubar.add_cascade(label="Ferramentas", menu=tools_menu)
        self.root.config(menu=menubar)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-o>", lambda _event: self.pick_files())
        self.root.bind_all("<Control-p>", lambda _event: self.print_current())
        self.root.bind_all("<Control-P>", lambda _event: self.print_all())
        self.root.bind_all("<Control-Left>", lambda _event: self.prev_page())
        self.root.bind_all("<Control-Right>", lambda _event: self.next_page())
        self.root.bind_all("<Control-r>", lambda _event: self._toggle_preview_mode())
        self.root.bind_all("<Control-0>", lambda _event: self.reset_scale())
        self.root.bind_all("<Control-parenright>", lambda _event: self.reset_crop())
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
        if not self.page_sources:
            self._draw_empty_preview("Solte o PDF ou imagem aqui")
        return "copy"

    def _on_drag_leave(self, _event=None):
        if not self.page_sources:
            self._draw_empty_preview("Arraste um PDF/imagem para cá ou use Abrir arquivos.")
        return "copy"

    def _on_files_dropped(self, event) -> str:
        paths = [normalize_input_path(path) for path in self.root.tk.splitlist(event.data)]
        files = [path for path in paths if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES]
        if files:
            self.load_files(files)
        else:
            self.status_message.set("Solte arquivos PDF ou imagem.")
        return "copy"

    def _toggle_preview_mode(self, _event=None) -> None:
        self.edit_mode.set("Rotacionar" if self.edit_mode.get() == "Redimensionar" else "Redimensionar")
        self._draw_selection_overlay()

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
        if not self.page_sources:
            return
        handle = self._preview_handle_at(event.x, event.y)
        if self.edit_mode.get() == "Rotacionar":
            self.rotate_start = (event.x, event.y, int(self.rotation_degrees.get()))
            self.preview_canvas.configure(cursor="exchange")
            return
        if handle:
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
            self.drag_start = (event.x, event.y, int(self.offset_x_px.get()), int(self.offset_y_px.get()))
            self.preview_canvas.configure(cursor="fleur")

    def _drag_preview_action(self, event) -> None:
        if not self.page_sources:
            return
        if self.rotate_start:
            start_x, start_y, start_angle = self.rotate_start
            cx, cy = self._preview_center()
            a0 = math.degrees(math.atan2(start_y - cy, start_x - cx))
            a1 = math.degrees(math.atan2(event.y - cy, event.x - cx))
            self.rotation_degrees.set(round(start_angle + a1 - a0))
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
            return
        if self.drag_start:
            start_x, start_y, offset_x, offset_y = self.drag_start
            scale = max(self.preview_scale, 0.01)
            self.offset_x_px.set(round(offset_x + (event.x - start_x) / scale))
            self.offset_y_px.set(round(offset_y + (event.y - start_y) / scale))

    def _end_preview_action(self, _event=None) -> None:
        self.drag_start = None
        self.resize_start = None
        self.rotate_start = None
        self.preview_canvas.configure(cursor="")

    def _preview_center(self) -> tuple[float, float]:
        if not self.preview_content_box:
            return self.preview_canvas.winfo_width() / 2, self.preview_canvas.winfo_height() / 2
        x1, y1, x2, y2 = self.preview_content_box
        return (x1 + x2) / 2, (y1 + y2) / 2

    def _update_preview_cursor(self, event) -> None:
        if not self.page_sources:
            return
        if self.edit_mode.get() == "Rotacionar" and self._point_in_preview_box(event.x, event.y):
            self.preview_canvas.configure(cursor="exchange")
        elif self._preview_handle_at(event.x, event.y):
            self.preview_canvas.configure(cursor="sizing")
        elif self._point_in_preview_box(event.x, event.y):
            self.preview_canvas.configure(cursor="fleur")
        else:
            self.preview_canvas.configure(cursor="")

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

    def _save_current_page_adjustment(self) -> None:
        if not self.page_sources or self.loading_page_settings:
            return
        self.page_adjustments[self.current_index] = self._current_page_adjustment()

    def _load_page_adjustment(self) -> None:
        if not self.page_sources:
            return
        adjustment = self.page_adjustments.get(self.current_index)
        default_adjustment = self.default_page_adjustment or self._current_page_adjustment()
        self.loading_page_settings = True
        try:
            if adjustment is None:
                adjustment = default_adjustment
            if adjustment is not None:
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
        window.geometry("420x300")
        window.transient(self.root)
        window.grab_set()
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
        ttk.Label(form, text="Nome").grid(row=0, column=0, sticky="w", pady=4)
        name_entry = ttk.Entry(form, textvariable=name_var)
        name_entry.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Largura (mm)").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=10, to=1000, increment=0.5, textvariable=width_var, width=12).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(form, text="Altura (mm)").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=10, to=1500, increment=0.5, textvariable=height_var, width=12).grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(form, text="DPI").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=150, to=600, increment=1, textvariable=dpi_var, width=12).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(form, text="Margem (mm)").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Spinbox(form, from_=0, to=50, increment=0.1, textvariable=margin_var, width=12).grid(row=4, column=1, sticky="w", pady=4)
        form.columnconfigure(1, weight=1)

        ttk.Label(container, textvariable=status_var, style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        actions = ttk.Frame(container, style="App.TFrame")
        actions.pack(fill="x", side="bottom", pady=(14, 0))
        ttk.Button(actions, text="Cancelar", command=window.destroy).pack(side="right")
        ttk.Button(actions, text="Salvar", style="Accent.TButton", command=lambda: self.save_profile_from_window(window, name_var, width_var, height_var, dpi_var, margin_var, status_var)).pack(side="right", padx=(0, 8))
        name_entry.focus_set()

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
        if self.syncing or self.loading_page_settings:
            return
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

    def load_files(self, files: list[Path]) -> None:
        self.page_sources = []
        self.current_index = 0
        self.page_adjustments = {}
        files = [normalize_input_path(file) for file in files]
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
        self.refresh_preview()

    def prev_page(self) -> None:
        if not self.page_sources:
            return
        self._save_current_page_adjustment()
        self.current_index = max(0, self.current_index - 1)
        self._load_page_adjustment()
        self.refresh_preview()

    def next_page(self) -> None:
        if not self.page_sources:
            return
        self._save_current_page_adjustment()
        self.current_index = min(len(self.page_sources) - 1, self.current_index + 1)
        self._load_page_adjustment()
        self.refresh_preview()

    def _current_fitted(self):
        if not self.page_sources:
            return None
        src = open_mono(self.page_sources[self.current_index])
        return fit_image(src, self.current_render_settings())

    def _fitted_for_index(self, index: int):
        src = open_mono(self.page_sources[index])
        return fit_image(src, self.render_settings_for_index(index))

    def schedule_preview(self) -> None:
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after_idle(self.refresh_preview)

    def refresh_preview(self) -> None:
        self.preview_job = None
        if not self.page_sources:
            self.page_info.configure(text="Página 0/0")
            self.preview_image_box = None
            self.preview_content_box = None
            self._draw_empty_preview("Arraste um PDF/imagem para cá ou use Abrir arquivos.")
            self.status_message.set("Abra um PDF ou imagem para começar")
            return

        src = open_mono(self.page_sources[self.current_index])
        result = fit_image_with_meta(src, self.current_render_settings())
        img = result.image
        self.preview_image = img

        available_w = max(240, self.preview_canvas.winfo_width() - 20)
        available_h = max(240, self.preview_canvas.winfo_height() - 20)
        ratio = min(available_w / img.width, available_h / img.height, 1.0)
        self.preview_scale = ratio
        show_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
        resampling = Image.Resampling.LANCZOS if ratio < 1 else Image.Resampling.NEAREST
        show = img.convert("L").resize(show_size, resampling)
        show = ImageOps.expand(show, border=2, fill=80)
        self.preview_tk = ImageTk.PhotoImage(show)
        canvas_w = self.preview_canvas.winfo_width()
        canvas_h = self.preview_canvas.winfo_height()
        x = max(0, (canvas_w - show.width) // 2)
        y = max(0, (canvas_h - show.height) // 2)
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
        self.preview_canvas.create_image(x, y, image=self.preview_tk, anchor="nw", tags=("preview_image",))
        self._draw_selection_overlay()
        self.page_info.configure(text=f"Página {self.current_index + 1}/{len(self.page_sources)}")

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

    def _payload_for_index(self, index: int) -> bytes:
        img = self._fitted_for_index(index)
        quality = get_quality(self.print_quality.get())
        return build_tspl(
            img,
            self.width_mm,
            self.height_mm,
            invert=not bool(self.invert.get()),
            speed=quality.speed,
            density=quality.density,
        )

    def _normal_document_for_index(self, index: int) -> bytes:
        img = self._fitted_for_index(index).convert("L")
        out = BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    def _enqueue_print_job(self, title: str, indexes: list[int]) -> None:
        if not self.page_sources:
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

    def print_current(self) -> None:
        if not self.page_sources:
            return
        self._enqueue_print_job(f"Página {self.current_index + 1}", [self.current_index])

    def print_all(self) -> None:
        if not self.page_sources:
            return
        self._enqueue_print_job("Todas as páginas", list(range(len(self.page_sources))))

    def _parse_page_range(self, expr: str) -> list[int]:
        expr = expr.strip()
        if not expr:
            return []

        pages = set()
        max_page = len(self.page_sources)
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
        if not self.page_sources:
            return
        try:
            indexes = self._parse_page_range(self.page_range.get())
            if not indexes:
                messagebox.showwarning("Impressão térmica", "Informe páginas válidas (ex: 1,3-5).")
                return
            self._enqueue_print_job(f"Faixa {self.page_range.get().strip()}", indexes)
        except Exception as exc:
            messagebox.showerror("Erro", str(exc))
