from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageQt
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sgm.config import Resolution
from sgm.resources import resource_path


ROTATE_STEP_DEG = 0.1
SCALE_STEP = 0.001  # 0.1% per click
AUTO_REPEAT_DELAY_MS = 250
AUTO_REPEAT_INTERVAL_MS = 30


def pil_image_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    qimg = ImageQt.ImageQt(img)
    return QPixmap.fromImage(QImage(qimg))


class _ClickToClosePreview(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event):
        self.window().close()
        event.accept()


class _CutPreviewDialog(QDialog):
    def __init__(self, pil_rgba: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cut Preview")
        self._img = pil_rgba.convert("RGBA")

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Background"))

        self.combo_bg = QComboBox()
        self.combo_bg.addItems(["White", "Gray", "Black", "Blue"])
        self.combo_bg.setCurrentText("Blue")
        self.combo_bg.currentIndexChanged.connect(self._render)
        top.addWidget(self.combo_bg)
        top.addStretch(1)
        root.addLayout(top)

        self.preview = _ClickToClosePreview()
        self.preview.setToolTip("Click image to close")
        self.preview.setStyleSheet("background-color: transparent;")
        root.addWidget(self.preview)

        self.resize(self._img.size[0] + 80, self._img.size[1] + 120)
        self._render()

    def _bg_rgb(self):
        name = self.combo_bg.currentText()
        if name == "Black":
            return (0, 0, 0)
        if name == "Blue":
            return (40, 80, 200)
        if name == "Gray":
            return (160, 160, 160)
        return (255, 255, 255)

    def _render(self):
        rgb = self._bg_rgb()
        self.setStyleSheet(f"QDialog {{ background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); }}")
        pix = pil_image_to_qpixmap(self._img)
        self.preview.setPixmap(pix)


class OverlayImageCleanerDialog(QDialog):
    """Modal dialog for cleaning an existing Overlay Big image.

    Loads the given image path automatically (no load button) and lets the user
    transform it relative to the cutter mask. On accept, `result_image` will be
    a PIL RGBA image (already cropped to the target resolution).
    """

    def __init__(
        self,
        *,
        parent: QWidget,
        image_path: Path,
        target_resolution: Resolution,
        cutter_template: str | Path | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Overlay Image Cleaner")
        self.setModal(True)

        self._target_size = (int(target_resolution.width), int(target_resolution.height))

        cutter_path = resource_path("CutterImage.png")
        override_raw = str(cutter_template).strip() if cutter_template is not None else ""
        if override_raw:
            try:
                override_path = Path(override_raw).expanduser()
                if override_path.exists() and override_path.is_file():
                    cutter_path = override_path
            except Exception:
                cutter_path = cutter_path
        self.cutter: Image.Image | None = None
        if cutter_path.exists():
            try:
                self.cutter = Image.open(cutter_path).convert("RGBA")
            except Exception:
                self.cutter = None

        self.selected: Image.Image | None = None
        self.selected_size = self._target_size
        self.offset = [0, 0]  # x, y offset of selected relative to cutter
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.rotation_deg = 0.0
        self.live_cut_preview = False

        self.result_image: Image.Image | None = None

        self._cut_preview_window: QDialog | None = None

        self._build_ui()

        if not image_path.exists():
            QMessageBox.warning(self, "Overlay Image Cleaner", f"Missing image: {image_path}")
            return

        try:
            self.selected = Image.open(image_path).convert("RGBA")
        except Exception as e:
            QMessageBox.warning(self, "Overlay Image Cleaner", f"Failed to load image: {e}")
            self.selected = None
            return

        self.btn_reset.setEnabled(True)
        self.reset_transform()

    def _build_ui(self):
        root = QHBoxLayout(self)

        self.preview_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setFixedSize(420, 580)
        root.addWidget(self.preview_label)

        ctrl = QVBoxLayout()

        chk_live = QCheckBox("Live Cut Preview")
        chk_live.setChecked(False)
        chk_live.toggled.connect(self.set_live_cut_preview)
        ctrl.addWidget(chk_live)
        self.chk_live = chk_live

        grp_move = QGroupBox("Move")
        move_layout = QVBoxLayout(grp_move)

        grid = QGridLayout()
        btn_up = QPushButton("Up")
        btn_up.clicked.connect(lambda: self.move(0, -1))
        btn_down = QPushButton("Down")
        btn_down.clicked.connect(lambda: self.move(0, 1))
        btn_left = QPushButton("Left")
        btn_left.clicked.connect(lambda: self.move(-1, 0))
        btn_right = QPushButton("Right")
        btn_right.clicked.connect(lambda: self.move(1, 0))

        for b in (btn_up, btn_down, btn_left, btn_right):
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(AUTO_REPEAT_DELAY_MS)
            b.setAutoRepeatInterval(AUTO_REPEAT_INTERVAL_MS)

        grid.addWidget(btn_up, 0, 1)
        grid.addWidget(btn_left, 1, 0)
        grid.addWidget(btn_right, 1, 2)
        grid.addWidget(btn_down, 2, 1)
        move_layout.addLayout(grid)

        sp_x = QSpinBox()
        sp_x.setRange(-2000, 2000)
        sp_x.setValue(0)
        sp_y = QSpinBox()
        sp_y.setRange(-2000, 2000)
        sp_y.setValue(0)
        sp_x.setMaximumWidth(90)
        sp_y.setMaximumWidth(90)
        sp_x.valueChanged.connect(lambda v: self.set_offset(v, None))
        sp_y.valueChanged.connect(lambda v: self.set_offset(None, v))

        offsets_row = QHBoxLayout()
        offsets_row.addWidget(QLabel("X"))
        offsets_row.addWidget(sp_x)
        offsets_row.addSpacing(8)
        offsets_row.addWidget(QLabel("Y"))
        offsets_row.addWidget(sp_y)
        offsets_row.addStretch(1)
        move_layout.addLayout(offsets_row)
        self.spin_x = sp_x
        self.spin_y = sp_y

        ctrl.addWidget(grp_move)

        grp_scale = QGroupBox("Scale")
        scale_layout = QVBoxLayout(grp_scale)

        def _scale_row(label_text: str, minus_cb, plus_cb):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            btn_minus = QPushButton("-")
            btn_plus = QPushButton("+")
            btn_minus.clicked.connect(minus_cb)
            btn_plus.clicked.connect(plus_cb)
            btn_minus.setMaximumWidth(40)
            btn_plus.setMaximumWidth(40)
            for b in (btn_minus, btn_plus):
                b.setAutoRepeat(True)
                b.setAutoRepeatDelay(AUTO_REPEAT_DELAY_MS)
                b.setAutoRepeatInterval(AUTO_REPEAT_INTERVAL_MS)
            row.addWidget(lbl)
            row.addStretch(1)
            row.addWidget(btn_minus)
            row.addWidget(btn_plus)
            return row

        scale_layout.addLayout(
            _scale_row(
                "Uniform",
                lambda: self.rescale_uniform(1.0 - SCALE_STEP),
                lambda: self.rescale_uniform(1.0 + SCALE_STEP),
            )
        )
        scale_layout.addLayout(
            _scale_row(
                "Widen (X)",
                lambda: self.rescale_x(1.0 - SCALE_STEP),
                lambda: self.rescale_x(1.0 + SCALE_STEP),
            )
        )
        scale_layout.addLayout(
            _scale_row(
                "Lengthen (Y)",
                lambda: self.rescale_y(1.0 - SCALE_STEP),
                lambda: self.rescale_y(1.0 + SCALE_STEP),
            )
        )

        ctrl.addWidget(grp_scale)

        grp_rotate = QGroupBox("Rotate")
        rotate_layout = QVBoxLayout(grp_rotate)

        hrot = QHBoxLayout()
        btn_rot_ccw = QPushButton("CCW")
        btn_rot_ccw.clicked.connect(lambda: self.rotate(ROTATE_STEP_DEG))
        btn_rot_cw = QPushButton("CW")
        btn_rot_cw.clicked.connect(lambda: self.rotate(-ROTATE_STEP_DEG))
        btn_rot_ccw.setMaximumWidth(55)
        btn_rot_cw.setMaximumWidth(55)
        for b in (btn_rot_ccw, btn_rot_cw):
            b.setAutoRepeat(True)
            b.setAutoRepeatDelay(AUTO_REPEAT_DELAY_MS)
            b.setAutoRepeatInterval(AUTO_REPEAT_INTERVAL_MS)

        hrot.addWidget(btn_rot_ccw)
        hrot.addWidget(btn_rot_cw)
        hrot.addSpacing(10)
        hrot.addWidget(QLabel("Deg"))

        sp_rot = QDoubleSpinBox()
        sp_rot.setRange(-180.0, 180.0)
        sp_rot.setSingleStep(ROTATE_STEP_DEG)
        sp_rot.setDecimals(2)
        sp_rot.setValue(0.0)
        sp_rot.setKeyboardTracking(True)
        sp_rot.valueChanged.connect(self.set_rotation)
        sp_rot.editingFinished.connect(lambda: self.set_rotation(sp_rot.value()))
        sp_rot.setMaximumWidth(110)
        hrot.addWidget(sp_rot)
        hrot.addStretch(1)
        rotate_layout.addLayout(hrot)
        self.spin_rot = sp_rot

        ctrl.addWidget(grp_rotate)

        btn_reset = QPushButton("Reset")
        btn_reset.setEnabled(False)
        btn_reset.clicked.connect(self.reset_transform)
        ctrl.addWidget(btn_reset)
        self.btn_reset = btn_reset

        btn_preview = QPushButton("Preview")
        btn_preview.clicked.connect(self.preview_cut)
        ctrl.addWidget(btn_preview)

        ctrl.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)

        btn_use = QPushButton("Use Adjusted Image")
        btn_use.clicked.connect(self._use_adjusted)
        bottom.addWidget(btn_use)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_cancel)

        ctrl.addLayout(bottom)
        root.addLayout(ctrl)

    def reset_transform(self):
        if self.selected is None:
            return
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.rotation_deg = 0.0
        self.selected_size = self._target_size

        if self.cutter is not None:
            cw, ch = self.cutter.size
            sw, sh = self.selected_size
            self.offset = [(cw - sw) // 2, (ch - sh) // 2]
        else:
            self.offset = [0, 0]

        self.spin_x.setValue(self.offset[0])
        self.spin_y.setValue(self.offset[1])
        self.spin_rot.setValue(0.0)
        self._update_preview()

    def rotate(self, delta_degrees: float):
        self.set_rotation(self.rotation_deg + delta_degrees)

    def set_rotation(self, degrees: float):
        deg = float(degrees)
        while deg > 180.0:
            deg -= 360.0
        while deg < -180.0:
            deg += 360.0
        self.rotation_deg = deg

        if abs(self.spin_rot.value() - deg) > 1e-6:
            self.spin_rot.blockSignals(True)
            self.spin_rot.setValue(deg)
            self.spin_rot.blockSignals(False)

        self._update_preview()

    def set_live_cut_preview(self, enabled: bool):
        self.live_cut_preview = bool(enabled)
        self._update_preview()

    def _get_transformed_selected(self):
        if self.selected is None:
            return None, None

        target_w = max(1, int(self.selected_size[0] * self.scale_x))
        target_h = max(1, int(self.selected_size[1] * self.scale_y))
        img = self.selected.resize((target_w, target_h), Image.LANCZOS)

        center_x = self.offset[0] + target_w / 2.0
        center_y = self.offset[1] + target_h / 2.0

        rot = float(self.rotation_deg)
        if abs(rot) > 1e-6:
            img = img.rotate(
                rot,
                resample=Image.BICUBIC,
                expand=True,
                fillcolor=(0, 0, 0, 0),
            )

        rw, rh = img.size
        pos = (int(round(center_x - rw / 2.0)), int(round(center_y - rh / 2.0)))
        return img, pos

    def set_offset(self, x, y):
        if x is not None:
            self.offset[0] = x
        if y is not None:
            self.offset[1] = y
        self._update_preview()

    def move(self, dx, dy):
        self.offset[0] += dx
        self.offset[1] += dy
        self.spin_x.setValue(self.offset[0])
        self.spin_y.setValue(self.offset[1])
        self._update_preview()

    def rescale_uniform(self, factor: float):
        self.scale_x *= factor
        self.scale_y *= factor
        self._update_preview()

    def rescale_x(self, factor: float):
        self.scale_x *= factor
        self._update_preview()

    def rescale_y(self, factor: float):
        self.scale_y *= factor
        self._update_preview()

    def _compose_preview_image(self) -> Image.Image:
        if self.cutter is None:
            if self.selected is None:
                return Image.new("RGBA", (420, 580), (200, 200, 200, 255))
            return self.selected

        cw, ch = self.cutter.size
        canvas = Image.new("RGBA", (cw, ch), (255, 255, 255, 255))

        img, pos = self._get_transformed_selected()
        if img is not None and pos is not None:
            canvas.paste(img, pos, img)

        overlay = self.cutter.copy()
        a = overlay.split()[3].point(lambda p: int(p * 0.7))
        overlay.putalpha(a)
        canvas.alpha_composite(overlay)
        return canvas

    def _update_preview(self):
        if self.live_cut_preview:
            img = self._compute_cut() or self._compose_preview_image()
        else:
            img = self._compose_preview_image()

        pix = pil_image_to_qpixmap(img)
        pix = pix.scaled(self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview_label.setPixmap(pix)

    def preview_cut(self):
        res = self._compute_cut()
        if res is None:
            QMessageBox.information(self, "No result", "Nothing to cut yet.")
            return
        dlg = _CutPreviewDialog(res, parent=self)
        dlg.setModal(True)
        self._cut_preview_window = dlg
        dlg.exec()

    def _compute_cut(self) -> Image.Image | None:
        if self.cutter is None or self.selected is None:
            return None

        cw, ch = self.cutter.size
        base = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))

        img, pos = self._get_transformed_selected()
        if img is not None and pos is not None:
            base.paste(img, pos, img)

        cutter_alpha = self.cutter.split()[3]
        inv = ImageChops.invert(cutter_alpha)
        ba = base.split()[3]
        new_alpha = ImageChops.multiply(ba, inv)
        base.putalpha(new_alpha)

        out_w, out_h = self._target_size
        left = (cw - out_w) // 2
        top = (ch - out_h) // 2
        return base.crop((left, top, left + out_w, top + out_h))

    def _use_adjusted(self) -> None:
        res = self._compute_cut()
        if res is None:
            QMessageBox.information(self, "Overlay Image Cleaner", "Nothing to use yet.")
            return
        self.result_image = res
        self.accept()
