from pathlib import Path

from thermal_label_app.domain.layer import Layer
from thermal_label_app.domain.models import CanvasSpec, PrintConfig
from thermal_label_app.domain.project import YnixProject
from thermal_label_app.storage.project_serializer import load_project, save_project


def test_project_roundtrip(tmp_path: Path) -> None:
    image = tmp_path / "logo.png"
    image.write_bytes(b"fake")
    project = YnixProject(
        canvas=CanvasSpec(100, 150, 203),
        source_files=[image],
        layers_by_page={
            0: [
                Layer(
                    id="layer-1",
                    type="text",
                    name="Titulo",
                    x=10,
                    y=20,
                    w=200,
                    h=40,
                    rotation=12,
                    text="YNIX",
                    font_family="DejaVu Sans",
                    font_size=32,
                    bold=True,
                    align="center",
                )
            ]
        },
        page_adjustments={0: {"fit_mode": "contain", "margin_px": 16}},
        print_config=PrintConfig("Tomate_MDK_007", "Térmica TSPL", "Normal", False),
    )
    path = tmp_path / "job.ynix"
    save_project(project, path)

    restored = load_project(path)

    assert restored.canvas.width_mm == 100
    assert restored.canvas.dpi == 203
    assert restored.source_files == [image]
    assert restored.layers_by_page[0][0].text == "YNIX"
    assert restored.layers_by_page[0][0].rotation == 12
    assert restored.print_config is not None
    assert restored.print_config.printer_name == "Tomate_MDK_007"
