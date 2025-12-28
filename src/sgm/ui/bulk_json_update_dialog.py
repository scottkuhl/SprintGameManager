from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


_LANGS = ["en", "fr", "es", "de", "it"]

_MAX_PREVIEW_CHARS = 50


class _SortItem(QTableWidgetItem):
    def __init__(self, display_text: str = "", *, sort_key: object | None = None):
        super().__init__(display_text)
        self._sort_key = display_text if sort_key is None else sort_key

    def set_sort_key(self, sort_key: object) -> None:
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        if isinstance(other, _SortItem):
            a = self._sort_key
            b = other._sort_key
            try:
                return float(a) < float(b)
            except Exception:
                return str(a) < str(b)
        return super().__lt__(other)


def _elide_text(s: str, *, max_chars: int = _MAX_PREVIEW_CHARS) -> str:
    s = str(s or "")
    if len(s) <= max_chars:
        return s
    if max_chars <= 3:
        return s[:max_chars]
    return s[: max_chars - 3] + "..."


def _elide_text_to_width(text: str, *, font_metrics: QFontMetrics, width_px: int) -> str:
    width_px = int(width_px or 0)
    if width_px <= 0:
        return _elide_text(text)
    # QLineEdit has some internal padding; be conservative.
    width_px = max(10, width_px - 6)
    return str(font_metrics.elidedText(str(text or ""), Qt.TextElideMode.ElideRight, width_px))


class _TextPopupDialog(QDialog):
    def __init__(self, *, parent: QWidget, title: str, text: str, editable: bool):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._editable = bool(editable)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._edit = QPlainTextEdit()
        self._edit.setPlainText(str(text or ""))
        self._edit.setReadOnly(not self._editable)
        layout.addWidget(self._edit, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        if self._editable:
            ok = QPushButton("OK")
            ok.clicked.connect(self.accept)
            btns.addWidget(ok)
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            btns.addWidget(cancel)
        else:
            close = QPushButton("Close")
            close.clicked.connect(self.accept)
            btns.addWidget(close)
        layout.addLayout(btns)

        self.resize(760, 460)

    def text_value(self) -> str:
        return self._edit.toPlainText()


@dataclass
class _FieldSpec:
    label: str
    key_path: str
    field_type: str  # "text" | "number" | "bool" | "other"


_STANDARD_FIELDS: list[_FieldSpec] = [
    _FieldSpec("Players", "nb_players", "text"),
    _FieldSpec("Editor", "editor", "text"),
    _FieldSpec("Year", "year", "number"),
    _FieldSpec("Description (en)", "description/en", "text"),
    _FieldSpec("Description (fr)", "description/fr", "text"),
    _FieldSpec("Description (es)", "description/es", "text"),
    _FieldSpec("Description (de)", "description/de", "text"),
    _FieldSpec("Description (it)", "description/it", "text"),
    _FieldSpec("Other", "", "other"),
]


@dataclass
class _Row:
    game_id: str
    basename: str
    folder: Path

    json_path: Path

    has_file: bool
    had_key: bool

    current_value_raw: object
    current_value_display: str

    new_value_display: str

    include_enabled: bool
    include_checked: bool

    new_value_editable: bool

    base_action: str
    action: str


def _load_json_dict(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_dict(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _split_key_path(key_path: str) -> list[str]:
    parts = [p for p in str(key_path or "").split("/") if p.strip() != ""]
    return [str(p) for p in parts]


def _get_at_path(data: dict, parts: list[str]) -> tuple[bool, object]:
    if not parts:
        return (False, None)
    cur: object = data
    for i, p in enumerate(parts):
        if not isinstance(cur, dict):
            return (False, None)
        if p not in cur:
            return (False, None)
        cur = cur[p]
        if i == len(parts) - 1:
            return (True, cur)
    return (False, None)


def _ensure_dict_path(data: dict, parts: list[str]) -> dict:
    cur: dict = data
    for p in parts:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    return cur


def _set_at_path(data: dict, parts: list[str], value: object) -> None:
    if not parts:
        return
    if len(parts) == 1:
        data[parts[0]] = value
        return
    parent = _ensure_dict_path(data, parts[:-1])
    parent[parts[-1]] = value


def _del_at_path(data: dict, parts: list[str]) -> bool:
    if not parts:
        return False
    if len(parts) == 1:
        return data.pop(parts[0], None) is not None
    cur: object = data
    for p in parts[:-1]:
        if not isinstance(cur, dict):
            return False
        cur = cur.get(p)
    if not isinstance(cur, dict):
        return False
    return cur.pop(parts[-1], None) is not None


def _desc_for_json(value: str) -> str:
    return " " if (value or "").strip() == "" else str(value)


def _display_value(value: object, *, field_type: str, key_path: str) -> str:
    if value is None:
        return ""
    if field_type == "bool":
        return "true" if bool(value) else "false"
    if field_type == "number":
        try:
            return str(int(value))
        except Exception:
            return str(value)

    # text / other
    s = str(value)
    if key_path.startswith("description/"):
        return "" if s.strip() == "" else s
    return "" if s.strip() == "" else s


def _normalize_for_compare(value: object, *, field_type: str) -> object:
    if field_type == "bool":
        return bool(value)
    if field_type == "number":
        try:
            return int(value)
        except Exception:
            return None
    # text
    if value is None:
        return ""
    return str(value)


class BulkJsonUpdateDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget,
        games: list[tuple[str, Path, str]],
        all_games: list[tuple[str, Path, str]] | None = None,
        json_keys: list[str] | None = None,
    ):
        """games: list of (game_id, folder, basename)."""
        super().__init__(parent)
        self.setWindowTitle("Bulk JSON Update")

        self._selected_games = list(games)
        self._all_games = list(all_games or games)
        self._json_keys = [str(k).strip() for k in (json_keys or []) if str(k).strip()]

        self._field_spec: _FieldSpec = _STANDARD_FIELDS[0]
        self._key_path: str = ""
        self._field_type: str = "text"
        self._remove_mode: bool = False
        self._regex_mode: bool = False
        self._rows: list[_Row] = []
        self._has_previewed: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        grp = QGroupBox("Field Selection")
        form = QFormLayout(grp)
        form.setContentsMargins(10, 10, 10, 10)
        form.setSpacing(8)

        self._cmb_field = QComboBox()
        for spec in _STANDARD_FIELDS:
            self._cmb_field.addItem(spec.label, spec)
        self._cmb_field.currentIndexChanged.connect(self._field_changed)
        form.addRow("Field to Update", self._cmb_field)

        self._cmb_key = QComboBox()
        self._cmb_key.setEditable(True)
        self._cmb_key.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Fill from ini suggestions.
        for k in self._json_keys:
            self._cmb_key.addItem(k)
        try:
            le = self._cmb_key.lineEdit()
            if le is not None:
                le.setPlaceholderText("e.g. some_key or description/en")
                le.textChanged.connect(self._field_inputs_changed)
        except Exception:
            pass
        self._cmb_key.currentIndexChanged.connect(self._field_inputs_changed)
        form.addRow("Key Name", self._cmb_key)

        self._cmb_type = QComboBox()
        self._cmb_type.addItem("Text", "text")
        self._cmb_type.addItem("Number", "number")
        self._cmb_type.addItem("True/False", "bool")
        self._cmb_type.currentIndexChanged.connect(self._field_inputs_changed)
        form.addRow("Field Type", self._cmb_type)

        self._chk_remove = QCheckBox("Remove Entry Mode")
        self._chk_remove.setToolTip("Delete this key from each included JSON file")
        self._chk_remove.toggled.connect(self._remove_toggled)
        form.addRow("", self._chk_remove)

        self._chk_regex = QCheckBox("Regex-based value transformation")
        self._chk_regex.toggled.connect(self._regex_toggled)
        form.addRow("", self._chk_regex)

        self._txt_regex = QLineEdit()
        self._txt_regex.setPlaceholderText("Regex pattern")
        self._txt_regex.textChanged.connect(self._field_inputs_changed)
        form.addRow("Regex Pattern", self._txt_regex)

        # Value controls
        self._value_text = QLineEdit()
        self._value_text.textChanged.connect(self._field_inputs_changed)

        self._value_num = QSpinBox()
        self._value_num.setRange(-2147483648, 2147483647)
        self._value_num.setValue(0)
        self._value_num.valueChanged.connect(self._field_inputs_changed)

        self._value_bool = QCheckBox("true")
        self._value_bool.setChecked(True)
        self._value_bool.toggled.connect(self._field_inputs_changed)

        self._value_row = QWidget()
        self._value_row_l = QHBoxLayout(self._value_row)
        self._value_row_l.setContentsMargins(0, 0, 0, 0)
        self._value_row_l.setSpacing(6)
        self._value_row_l.addWidget(self._value_text)
        self._value_row_l.addWidget(self._value_num)
        self._value_row_l.addWidget(self._value_bool)
        form.addRow("Value", self._value_row)

        layout.addWidget(grp)

        top_btns = QHBoxLayout()
        self._lbl_counts = QLabel("Rows: 0 | Included: 0")
        self._lbl_counts.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_counts.setMinimumWidth(220)
        top_btns.addWidget(self._lbl_counts)

        self._btn_include_all = QPushButton("Include All")
        self._btn_include_all.clicked.connect(lambda: self._bulk_set_include(True))
        self._btn_include_all.setVisible(False)
        top_btns.addWidget(self._btn_include_all)

        self._btn_include_none = QPushButton("Include None")
        self._btn_include_none.clicked.connect(lambda: self._bulk_set_include(False))
        self._btn_include_none.setVisible(False)
        top_btns.addWidget(self._btn_include_none)

        top_btns.addStretch(1)
        self._btn_preview = QPushButton("Preview Updates")
        self._btn_preview.clicked.connect(self._preview_clicked)
        top_btns.addWidget(self._btn_preview)
        layout.addLayout(top_btns)

        self._tbl = QTableWidget(0, 5)
        self._tbl.setHorizontalHeaderLabels(["Include", "Game", "Current Value", "New Value", "Action"])
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._tbl.setWordWrap(True)
        # Make selection highlight subtle so it doesn't overpower our per-row background colors.
        self._tbl.setStyleSheet(
            "QTableWidget::item:selected { background-color: rgba(0, 0, 0, 20); }"
            "QTableWidget::item:selected:active { background-color: rgba(0, 0, 0, 20); }"
        )
        # Allow editing with a single click on editable items.
        self._tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
            | QAbstractItemView.EditTrigger.DoubleClicked
        )
        self._tbl.setSortingEnabled(True)
        self._tbl.itemChanged.connect(self._item_changed)
        self._tbl.cellClicked.connect(self._cell_clicked)
        try:
            self._tbl.horizontalHeader().sectionResized.connect(self._on_table_section_resized)
        except Exception:
            pass

        layout.addWidget(self._tbl, 1)

        bottom_btns = QHBoxLayout()
        self._rb_selected = QRadioButton("Selected Games")
        self._rb_all = QRadioButton("All Games")
        self._rb_selected.setChecked(True)
        self._rb_selected.toggled.connect(self._scope_changed)
        self._rb_all.toggled.connect(self._scope_changed)
        bottom_btns.addWidget(self._rb_selected)
        bottom_btns.addWidget(self._rb_all)
        bottom_btns.addStretch(1)
        self._btn_apply = QPushButton("Perform Updates")
        self._btn_apply.clicked.connect(self._perform_updates)
        self._btn_apply.setEnabled(False)
        bottom_btns.addWidget(self._btn_apply)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_btns.addWidget(btn_close)
        layout.addLayout(bottom_btns)

        self._field_changed()
        self._update_counts_label()
        self.resize(900, 560)

    def _update_apply_enabled(self) -> None:
        self._btn_apply.setEnabled(
            any(r.has_file and r.include_enabled and r.include_checked for r in (self._rows or []))
        )

    def _update_counts_label(self) -> None:
        total = len(self._rows or [])
        included = sum(1 for r in (self._rows or []) if r.has_file and r.include_enabled and r.include_checked)
        self._lbl_counts.setText(f"Rows: {total} | Included: {included}")

        show_bulk = any(r.has_file and r.include_enabled for r in (self._rows or []))
        self._btn_include_all.setVisible(bool(show_bulk))
        self._btn_include_none.setVisible(bool(show_bulk))

    def _scope_changed(self, checked: bool) -> None:
        # Only respond when a radio becomes checked (not when it becomes unchecked).
        if not bool(checked):
            return

        # If preview inputs aren't currently valid, don't keep showing a preview that
        # may no longer match the selected scope.
        if not self._btn_preview.isEnabled():
            self._rows = []
            self._tbl.blockSignals(True)
            try:
                self._tbl.clearContents()
                self._tbl.setRowCount(0)
            finally:
                self._tbl.blockSignals(False)
            self._update_apply_enabled()
            self._update_counts_label()
            return

        # Auto-refresh preview for the newly selected scope.
        self._preview_clicked()

    def _apply_row_foreground(self, row_idx: int) -> None:
        black = QBrush(QColor(0, 0, 0))

        for col in range(self._tbl.columnCount()):
            it = self._tbl.item(row_idx, col)
            if it is not None:
                it.setForeground(black)

            w = self._tbl.cellWidget(row_idx, col)
            if w is not None:
                # Don't blindly force widget foreground; it breaks some controls
                # (notably QSpinBox) in Windows dark mode.
                if isinstance(w, QSpinBox):
                    w.setStyleSheet("color: black; background-color: white;")
                elif isinstance(w, QCheckBox):
                    w.setStyleSheet("color: black;")
                else:
                    # Most of our long-text widgets style their children directly.
                    pass

    def _refresh_elided_cell(self, row_idx: int, col_idx: int) -> None:
        w = self._tbl.cellWidget(row_idx, col_idx)
        if w is None:
            return
        le = w.findChild(QLineEdit)
        if le is None:
            return
        full = le.property("fullText")
        if full is None:
            return

        # Only update display text; keep full text in the property.
        fm = QFontMetrics(le.font())
        le.setText(_elide_text_to_width(str(full), font_metrics=fm, width_px=le.width()))

    def _refresh_elided_cells_for_column(self, col_idx: int) -> None:
        if self._tbl.rowCount() <= 0:
            return
        for r in range(self._tbl.rowCount()):
            self._refresh_elided_cell(r, col_idx)

    def _refresh_all_elided_cells(self) -> None:
        # Columns that may contain an elided text widget.
        for c in (1, 2, 3):
            self._refresh_elided_cells_for_column(c)

    def _on_table_section_resized(self, logical_index: int, _old_size: int, _new_size: int) -> None:
        # Defer until layout settles so QLineEdit widths are updated.
        if int(logical_index) in (1, 2, 3):
            QTimer.singleShot(0, lambda idx=int(logical_index): self._refresh_elided_cells_for_column(idx))

    def _make_elided_text_widget(
        self,
        *,
        full_text: str,
        title: str,
        editable: bool,
        on_accepted: callable | None,
    ) -> QWidget:
        """Creates an elided display + '...' button widget.

        Stores the full text in a dynamic property 'fullText' on the QLineEdit.
        """
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(4)

        txt = QLineEdit()
        txt.setReadOnly(True)
        txt.setText(_elide_text(full_text))
        txt.setProperty("fullText", str(full_text or ""))
        txt.setStyleSheet("color: black; background: transparent;")
        l.addWidget(txt, 1)

        btn = QPushButton("...")
        btn.setFixedWidth(26)
        btn.setToolTip("View full value")
        btn.setStyleSheet("color: black; background: transparent;")

        def _clicked() -> None:
            cur_full = str(txt.property("fullText") or "")
            dlg = _TextPopupDialog(parent=self, title=title, text=cur_full, editable=bool(editable))
            if dlg.exec() == QDialog.DialogCode.Accepted:
                if editable:
                    updated = dlg.text_value()
                    txt.setProperty("fullText", str(updated or ""))
                    fm = QFontMetrics(txt.font())
                    txt.setText(_elide_text_to_width(str(updated or ""), font_metrics=fm, width_px=txt.width()))
                    if on_accepted is not None:
                        on_accepted(updated)

        btn.clicked.connect(_clicked)
        l.addWidget(btn, 0)

        # Ensure initial display matches the actual available width once laid out.
        QTimer.singleShot(0, lambda le=txt: le.setText(
            _elide_text_to_width(str(le.property("fullText") or ""), font_metrics=QFontMetrics(le.font()), width_px=le.width())
        ))

        return w

    def _get_full_text_from_cell_widget(self, row_idx: int, col_idx: int) -> str | None:
        w = self._tbl.cellWidget(row_idx, col_idx)
        if w is None:
            return None
        # Our elided widgets include a QLineEdit with 'fullText' property.
        le = w.findChild(QLineEdit)
        if le is None:
            return None
        v = le.property("fullText")
        if v is None:
            return None
        return str(v)

    def _game_id_for_view_row(self, view_row: int) -> str | None:
        if view_row < 0 or view_row >= self._tbl.rowCount():
            return None
        it = self._tbl.item(view_row, 0)
        if it is None:
            return None
        v = it.data(Qt.ItemDataRole.UserRole)
        if v is None:
            return None
        return str(v)

    def _model_row_index_for_game_id(self, game_id: str) -> int | None:
        for i, row in enumerate(self._rows or []):
            if row.game_id == game_id:
                return i
        return None

    def _view_row_for_game_id(self, game_id: str) -> int | None:
        for r in range(self._tbl.rowCount()):
            gid = self._game_id_for_view_row(r)
            if gid == game_id:
                return r
        return None

    def _bulk_set_include(self, checked: bool) -> None:
        if not self._rows:
            return

        was_sorting = self._tbl.isSortingEnabled()
        sort_col = -1
        sort_order = Qt.SortOrder.AscendingOrder
        try:
            hdr = self._tbl.horizontalHeader()
            sort_col = int(hdr.sortIndicatorSection())
            sort_order = hdr.sortIndicatorOrder()
        except Exception:
            pass

        # Disable sorting while we update many cells; otherwise the view can reshuffle
        # mid-loop and leave some widgets unmodified.
        self._tbl.setSortingEnabled(False)

        # Update model first.
        for row in self._rows:
            if not row.has_file:
                continue
            if not row.include_enabled:
                continue
            row.include_checked = bool(checked)
            row.action = row.base_action if row.include_checked else "Skipped"

        # Update visible table rows.
        self._tbl.blockSignals(True)
        try:
            for view_row in range(self._tbl.rowCount()):
                gid = self._game_id_for_view_row(view_row)
                if gid is None:
                    continue
                model_idx = self._model_row_index_for_game_id(gid)
                if model_idx is None:
                    continue
                row = self._rows[model_idx]
                if not row.has_file or not row.include_enabled:
                    continue

                w_inc = self._tbl.cellWidget(view_row, 0)
                if isinstance(w_inc, QCheckBox):
                    w_inc.blockSignals(True)
                    try:
                        w_inc.setChecked(bool(row.include_checked))
                    finally:
                        w_inc.blockSignals(False)

                it_inc = self._tbl.item(view_row, 0)
                if isinstance(it_inc, _SortItem):
                    it_inc.set_sort_key(1 if row.include_checked else 0)

                it_act = self._tbl.item(view_row, 4)
                if it_act is not None:
                    it_act.setText(row.action)
                    if isinstance(it_act, _SortItem):
                        it_act.set_sort_key(row.action)

                self._apply_row_background(view_row, row.action)
                self._apply_row_foreground(view_row)
        finally:
            self._tbl.blockSignals(False)

        # Restore sorting and re-apply the active sort.
        self._tbl.setSortingEnabled(bool(was_sorting))
        if was_sorting and sort_col >= 0:
            try:
                self._tbl.sortItems(sort_col, sort_order)
            except Exception:
                pass

        self._update_apply_enabled()
        self._update_counts_label()

    def _set_current_value_cell(self, r: int, row: _Row) -> None:
        # Clear existing widget
        if self._tbl.cellWidget(r, 2) is not None:
            self._tbl.removeCellWidget(r, 2)

        if not row.has_file:
            link = QLabel('<a style="color: black; text-decoration: underline;" href="create">Create JSON</a>')
            link.setTextFormat(Qt.TextFormat.RichText)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            link.setOpenExternalLinks(False)
            link.linkActivated.connect(lambda _href, gid=row.game_id: self._create_json_clicked(gid))
            self._tbl.setCellWidget(r, 2, link)
            it_cur = _SortItem("", sort_key="Create JSON")
            it_cur.setFlags(it_cur.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tbl.setItem(r, 2, it_cur)
            return

        cur_text = str(row.current_value_display or "")
        if len(cur_text) > _MAX_PREVIEW_CHARS:
            w_cur = self._make_elided_text_widget(
                full_text=cur_text,
                title="Current Value",
                editable=False,
                on_accepted=None,
            )
            self._tbl.setCellWidget(r, 2, w_cur)
            it_cur = _SortItem("", sort_key=cur_text)
        else:
            it_cur = _SortItem(cur_text, sort_key=cur_text)

        it_cur.setFlags(it_cur.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._tbl.setItem(r, 2, it_cur)

    # ---------- field selection state ----------

    def _field_changed(self) -> None:
        spec = self._cmb_field.currentData()
        if isinstance(spec, _FieldSpec):
            self._field_spec = spec
        else:
            self._field_spec = _STANDARD_FIELDS[-1]

        is_other = self._field_spec.field_type == "other"

        if not is_other:
            self._cmb_key.setCurrentText(self._field_spec.key_path)
            self._cmb_key.setEnabled(False)

            self._field_type = self._field_spec.field_type
            idx = self._cmb_type.findData(self._field_type)
            if idx >= 0:
                self._cmb_type.setCurrentIndex(idx)
            self._cmb_type.setEnabled(False)
        else:
            self._cmb_key.setEnabled(True)
            self._cmb_key.setCurrentText("")
            self._cmb_type.setEnabled(True)

        self._chk_remove.setVisible(bool(is_other))
        if not is_other:
            self._chk_remove.setChecked(False)

        self._field_inputs_changed()

    def _remove_toggled(self, checked: bool) -> None:
        self._remove_mode = bool(checked)
        self._field_inputs_changed()

    def _regex_toggled(self, checked: bool) -> None:
        self._regex_mode = bool(checked)
        self._field_inputs_changed()

    def _field_inputs_changed(self, *args) -> None:
        self._key_path = (self._cmb_key.currentText() or "").strip()
        self._field_type = str(self._cmb_type.currentData() or "text")

        # Remove Entry mode only for Other
        is_other = self._field_spec.field_type == "other"
        self._chk_remove.setEnabled(bool(is_other))
        if not is_other:
            self._remove_mode = False

        # Regex only supported for Text updates (non-remove).
        allow_regex = bool(self._field_type == "text" and not self._remove_mode)
        self._chk_regex.setVisible(True)
        self._chk_regex.setEnabled(allow_regex)
        if not allow_regex:
            self._chk_regex.setChecked(False)
            self._regex_mode = False

        self._txt_regex.setVisible(bool(self._regex_mode))

        # Value controls
        self._value_text.setVisible(self._field_type == "text")
        self._value_num.setVisible(self._field_type == "number")
        self._value_bool.setVisible(self._field_type == "bool")

        # Disable value input for Remove Entry mode.
        self._value_row.setEnabled(not self._remove_mode)

        # Standard year constraints
        if self._field_spec.key_path == "year" and self._field_type == "number":
            self._value_num.setRange(0, 9999)
        else:
            self._value_num.setRange(-2147483648, 2147483647)

        # Label text for bool widget
        if self._field_type == "bool":
            self._value_bool.setText("true")

        # Enable Preview if inputs are valid
        ok = bool(self._key_path)
        if self._remove_mode:
            ok = ok and is_other
        else:
            if self._field_type == "text":
                if self._regex_mode:
                    ok = ok and bool((self._txt_regex.text() or "").strip() != "")
                else:
                    ok = ok and True
            elif self._field_type == "number":
                ok = ok and True
            elif self._field_type == "bool":
                ok = ok and True

        self._btn_preview.setEnabled(bool(ok))

    def _selected_value_for_row(self, current_value_raw: object, *, key_present: bool) -> object:
        if self._remove_mode:
            return None

        if self._field_type == "text":
            if self._regex_mode:
                pattern = str(self._txt_regex.text() or "")
                repl = str(self._value_text.text() or "")
                # If the key is missing, treat current value as empty string and still apply regex.
                cur_s = "" if (not key_present or current_value_raw is None) else str(current_value_raw)
                try:
                    return re.sub(pattern, repl, cur_s)
                except Exception:
                    return repl
            return str(self._value_text.text() or "")

        if self._field_type == "number":
            return int(self._value_num.value())

        if self._field_type == "bool":
            return bool(self._value_bool.isChecked())

        return str(self._value_text.text() or "")

    # ---------- preview table ----------

    def _preview_clicked(self) -> None:
        try:
            parts = _split_key_path(self._key_path)
            if not parts:
                return

            rows: list[_Row] = []
            scope_games = self._all_games if self._rb_all.isChecked() else self._selected_games
            for game_id, folder, basename in scope_games:
                json_path = Path(folder) / f"{basename}.json"
                has_file = bool(json_path.exists())

                data = _load_json_dict(json_path) if has_file else {}
                had_key, cur_raw = _get_at_path(data, parts) if has_file else (False, None)

                cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path)

                new_raw = self._selected_value_for_row(cur_raw, key_present=had_key)
                if self._field_type == "text" and self._key_path.startswith("description/") and not self._remove_mode:
                    new_disp = "" if (str(new_raw or "").strip() == "") else str(new_raw)
                elif self._remove_mode:
                    new_disp = ""
                else:
                    new_disp = _display_value(new_raw, field_type=self._field_type, key_path=self._key_path)

                row = self._evaluate_row(
                    game_id=game_id,
                    folder=Path(folder),
                    basename=basename,
                    json_path=json_path,
                    has_file=has_file,
                    had_key=had_key,
                    cur_raw=cur_raw,
                    cur_disp=cur_disp,
                    new_raw=new_raw,
                    new_disp=new_disp,
                )
                rows.append(row)

            self._rows = rows
            self._rebuild_table()
            self._update_apply_enabled()
            self._update_counts_label()
            self._has_previewed = True
        except Exception as e:
            QMessageBox.warning(self, "Bulk JSON Update", str(e))

    def _evaluate_row(
        self,
        *,
        game_id: str,
        folder: Path,
        basename: str,
        json_path: Path,
        has_file: bool,
        had_key: bool,
        cur_raw: object,
        cur_disp: str,
        new_raw: object,
        new_disp: str,
    ) -> _Row:
        # Missing JSON file
        if not has_file:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=False,
                had_key=False,
                current_value_raw=None,
                current_value_display="Create JSON",
                new_value_display="",
                include_enabled=False,
                include_checked=False,
                new_value_editable=False,
                base_action="Missing File",
                action="Missing File",
            )

        parts = _split_key_path(self._key_path)

        # Remove mode special cases
        if self._remove_mode:
            if not parts or not had_key:
                return _Row(
                    game_id=game_id,
                    basename=basename,
                    folder=folder,
                    json_path=json_path,
                    has_file=True,
                    had_key=False,
                    current_value_raw=cur_raw,
                    current_value_display=cur_disp,
                    new_value_display="",
                    include_enabled=False,
                    include_checked=False,
                    new_value_editable=False,
                    base_action="Already Set",
                    action="Already Set",
                )
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=True,
                had_key=True,
                current_value_raw=cur_raw,
                current_value_display=cur_disp,
                new_value_display="",
                include_enabled=True,
                include_checked=True,
                new_value_editable=False,
                base_action="Remove Entry",
                action="Remove Entry",
            )

        # Compare values
        cur_norm = _normalize_for_compare(cur_raw, field_type=self._field_type)
        new_norm = _normalize_for_compare(new_raw, field_type=self._field_type)

        # Missing key
        if not had_key:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=True,
                had_key=False,
                current_value_raw=cur_raw,
                current_value_display="",
                new_value_display=new_disp,
                include_enabled=True,
                include_checked=True,
                new_value_editable=True,
                base_action="Add Setting",
                action="Add Setting",
            )

        # New value equals current
        if cur_norm is not None and new_norm is not None and cur_norm == new_norm:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=True,
                had_key=True,
                current_value_raw=cur_raw,
                current_value_display=cur_disp,
                new_value_display=new_disp,
                include_enabled=False,
                include_checked=False,
                new_value_editable=True,
                base_action="Already Set",
                action="Already Set",
            )

        # Current blank/null, new non-blank
        cur_blank = bool(cur_disp.strip() == "")
        new_blank = bool(new_disp.strip() == "")
        if cur_blank and not new_blank:
            return _Row(
                game_id=game_id,
                basename=basename,
                folder=folder,
                json_path=json_path,
                has_file=True,
                had_key=True,
                current_value_raw=cur_raw,
                current_value_display=cur_disp,
                new_value_display=new_disp,
                include_enabled=True,
                include_checked=True,
                new_value_editable=True,
                base_action="Set Value",
                action="Set Value",
            )

        # Current non-blank, new differs
        return _Row(
            game_id=game_id,
            basename=basename,
            folder=folder,
            json_path=json_path,
            has_file=True,
            had_key=True,
            current_value_raw=cur_raw,
            current_value_display=cur_disp,
            new_value_display=new_disp,
            include_enabled=True,
            include_checked=True,
            new_value_editable=True,
            base_action="Change Value",
            action="Change Value",
        )

    def _apply_row_background(self, row_idx: int, action: str) -> None:
        # Light backgrounds per spec.
        grey = QBrush(QColor(222, 222, 222))
        green = QBrush(QColor(198, 240, 198))
        orange = QBrush(QColor(245, 218, 176))

        if action in {"Missing File", "Already Set", "Skipped"}:
            brush = grey
        elif action in {"Add Setting", "Set Value"}:
            brush = green
        else:
            brush = orange

        for col in range(self._tbl.columnCount()):
            it = self._tbl.item(row_idx, col)
            if it is not None:
                it.setBackground(brush)

    def _rebuild_table(self) -> None:
        was_sorting = self._tbl.isSortingEnabled()
        self._tbl.setSortingEnabled(False)
        self._tbl.blockSignals(True)
        try:
            # Ensure stale widgets (like prior Current Value widgets) don't linger.
            for rr in range(self._tbl.rowCount()):
                for cc in range(self._tbl.columnCount()):
                    if self._tbl.cellWidget(rr, cc) is not None:
                        self._tbl.removeCellWidget(rr, cc)

            self._tbl.clearContents()
            self._tbl.setRowCount(0)
            self._tbl.setRowCount(len(self._rows))

            for r, row in enumerate(self._rows):
                # Clear any cell widgets for this row before repopulating.
                for cc in range(self._tbl.columnCount()):
                    if self._tbl.cellWidget(r, cc) is not None:
                        self._tbl.removeCellWidget(r, cc)

                # Include
                include_chk = QCheckBox()
                include_chk.setChecked(bool(row.include_checked))
                include_chk.setEnabled(bool(row.include_enabled))
                include_chk.toggled.connect(lambda checked, gid=row.game_id: self._include_toggled(gid, checked))
                self._tbl.setCellWidget(r, 0, include_chk)

                it_inc = _SortItem("", sort_key=1 if row.include_checked else 0)
                it_inc.setData(Qt.ItemDataRole.UserRole, row.game_id)
                it_inc.setFlags(it_inc.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tbl.setItem(r, 0, it_inc)

                # Game
                game_text = f"{row.basename}  —  {row.folder}"
                if len(game_text) > _MAX_PREVIEW_CHARS:
                    w_game = self._make_elided_text_widget(
                        full_text=game_text,
                        title="Game",
                        editable=False,
                        on_accepted=None,
                    )
                    self._tbl.setCellWidget(r, 1, w_game)
                    it_game = _SortItem("", sort_key=game_text)
                else:
                    it_game = _SortItem(game_text, sort_key=game_text)
                it_game.setFlags(it_game.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tbl.setItem(r, 1, it_game)

                # Current Value
                self._set_current_value_cell(r, row)

                # New Value
                self._set_new_value_cell(r, row)

                # Action
                it_act = _SortItem(row.action, sort_key=row.action)
                it_act.setFlags(it_act.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._tbl.setItem(r, 4, it_act)

                self._apply_row_background(r, row.action)
                self._apply_row_foreground(r)

            self._tbl.resizeColumnsToContents()
            self._tbl.setColumnWidth(1, max(self._tbl.columnWidth(1), 280))
            self._tbl.setColumnWidth(2, max(self._tbl.columnWidth(2), 170))
            self._tbl.setColumnWidth(3, max(self._tbl.columnWidth(3), 170))
        finally:
            self._tbl.blockSignals(False)

        self._tbl.setSortingEnabled(bool(was_sorting))

        # After layout/resizeColumnsToContents, re-elide any long text widgets.
        QTimer.singleShot(0, self._refresh_all_elided_cells)

        self._update_apply_enabled()
        self._update_counts_label()

    def _item_changed(self, item: QTableWidgetItem) -> None:
        # React to user edits of New Value (text mode only).
        try:
            if item is None:
                return
            if self._remove_mode:
                return
            if self._field_type != "text":
                return
            if item.column() != 3:
                return
            gid = self._game_id_for_view_row(int(item.row()))
            if gid is None:
                return
            self._new_value_changed(gid)
        except Exception:
            pass

    def _cell_clicked(self, row: int, col: int) -> None:
        # Single-click into editable New Value text cells.
        try:
            if self._remove_mode:
                return
            if col != 3:
                return
            gid = self._game_id_for_view_row(row)
            if gid is None:
                return
            model_idx = self._model_row_index_for_game_id(gid)
            if model_idx is None:
                return
            if not bool(self._rows[model_idx].new_value_editable):
                return
            if self._field_type != "text":
                return
            if self._tbl.cellWidget(row, col) is not None:
                # Long text uses a widget + popup editor; number/bool use widgets.
                return
            it = self._tbl.item(row, col)
            if it is None:
                return
            if not bool(it.flags() & Qt.ItemFlag.ItemIsEditable):
                return
            self._tbl.setCurrentCell(row, col)
            self._tbl.editItem(it)
        except Exception:
            pass

    def _set_new_value_cell(self, r: int, row: _Row) -> None:
        # Clear existing widget/item
        if self._tbl.cellWidget(r, 3) is not None:
            self._tbl.removeCellWidget(r, 3)

        if self._remove_mode:
            it_new = _SortItem("", sort_key="")
            it_new.setFlags(it_new.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tbl.setItem(r, 3, it_new)
            return

        if self._field_type == "number":
            sb = QSpinBox()
            # Ensure readable even in Windows dark mode.
            sb.setStyleSheet("color: black; background-color: white;")
            if self._field_spec.key_path == "year":
                sb.setRange(0, 9999)
            else:
                sb.setRange(-2147483648, 2147483647)

            try:
                sb.setValue(int(row.new_value_display.strip() or "0"))
            except Exception:
                sb.setValue(0)

            sb.setEnabled(bool(row.new_value_editable))
            sb.valueChanged.connect(lambda _v, gid=row.game_id: self._new_value_changed(gid))
            self._tbl.setCellWidget(r, 3, sb)
            it_placeholder = _SortItem("", sort_key=str(row.new_value_display or ""))
            it_placeholder.setFlags(it_placeholder.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tbl.setItem(r, 3, it_placeholder)
            return

        if self._field_type == "bool":
            cb = QCheckBox()
            cb.setStyleSheet("color: black;")
            cb.setChecked(str(row.new_value_display).strip().lower() in {"1", "true", "yes", "on"})
            cb.setEnabled(bool(row.new_value_editable))
            cb.toggled.connect(lambda _v, gid=row.game_id: self._new_value_changed(gid))
            self._tbl.setCellWidget(r, 3, cb)
            it_placeholder = _SortItem("", sort_key=str(row.new_value_display or ""))
            it_placeholder.setFlags(it_placeholder.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tbl.setItem(r, 3, it_placeholder)
            return

        new_text = str(row.new_value_display or "")
        if len(new_text) > _MAX_PREVIEW_CHARS:
            # For long text, keep inline display elided; edit via popup if editable.
            def _accepted(updated_text: str, gid: str = row.game_id) -> None:
                # Update the widget's stored full text (so _new_value_changed reads it), then recompute.
                view_row = self._view_row_for_game_id(gid)
                if view_row is not None:
                    w = self._tbl.cellWidget(view_row, 3)
                    if w is not None:
                        le = w.findChild(QLineEdit)
                        if le is not None:
                            le.setProperty("fullText", str(updated_text or ""))
                            fm = QFontMetrics(le.font())
                            le.setText(
                                _elide_text_to_width(
                                    str(updated_text or ""), font_metrics=fm, width_px=le.width()
                                )
                            )
                self._new_value_changed(gid)

            w_new = self._make_elided_text_widget(
                full_text=new_text,
                title="New Value",
                editable=bool(row.new_value_editable),
                on_accepted=_accepted if row.new_value_editable else None,
            )
            self._tbl.setCellWidget(r, 3, w_new)
            it_new = _SortItem("", sort_key=new_text)
            it_new.setFlags(it_new.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._tbl.setItem(r, 3, it_new)
            return

        it_new = _SortItem(new_text, sort_key=new_text)
        if row.new_value_editable:
            it_new.setFlags(it_new.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            it_new.setFlags(it_new.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._tbl.setItem(r, 3, it_new)

    def _include_toggled(self, game_id: str, checked: bool) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        view_row = self._view_row_for_game_id(game_id)
        if model_idx is None or view_row is None:
            return
        row = self._rows[model_idx]
        if not row.include_enabled:
            return

        row.include_checked = bool(checked)
        # Update action to Skipped or restore base action
        if not row.include_checked:
            row.action = "Skipped"
        else:
            row.action = row.base_action

        it_inc = self._tbl.item(view_row, 0)
        if isinstance(it_inc, _SortItem):
            it_inc.set_sort_key(1 if row.include_checked else 0)

        it_act = self._tbl.item(view_row, 4)
        if it_act is not None:
            it_act.setText(row.action)
            if isinstance(it_act, _SortItem):
                it_act.set_sort_key(row.action)
        self._apply_row_background(view_row, row.action)
        self._update_apply_enabled()
        self._update_counts_label()

    def _new_value_changed(self, game_id: str) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        view_row = self._view_row_for_game_id(game_id)
        if model_idx is None or view_row is None:
            return
        row = self._rows[model_idx]
        if not row.has_file:
            return

        self._tbl.blockSignals(True)
        try:

            # Read edited new value
            new_disp = ""
            if self._remove_mode:
                new_disp = ""
            elif self._field_type == "number":
                w = self._tbl.cellWidget(view_row, 3)
                if isinstance(w, QSpinBox):
                    new_disp = str(int(w.value()))
            elif self._field_type == "bool":
                w = self._tbl.cellWidget(view_row, 3)
                if isinstance(w, QCheckBox):
                    new_disp = "true" if w.isChecked() else "false"
            else:
                full = self._get_full_text_from_cell_widget(view_row, 3)
                if full is not None:
                    new_disp = str(full)
                else:
                    it = self._tbl.item(view_row, 3)
                    new_disp = str(it.text() if it is not None else "")

            row.new_value_display = new_disp

        # Recompute row state based on disk current + edited new value
            parts = _split_key_path(self._key_path)
            data = _load_json_dict(row.json_path)
            had_key, cur_raw = _get_at_path(data, parts)
            cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path)

            if self._remove_mode:
                new_raw = None
            else:
                if self._field_type == "number":
                    try:
                        new_raw = int(new_disp.strip() or "0")
                    except Exception:
                        new_raw = 0
                elif self._field_type == "bool":
                    new_raw = str(new_disp).strip().lower() in {"1", "true", "yes", "on"}
                else:
                    new_raw = str(new_disp)

            updated = self._evaluate_row(
                game_id=row.game_id,
                folder=row.folder,
                basename=row.basename,
                json_path=row.json_path,
                has_file=True,
                had_key=had_key,
                cur_raw=cur_raw,
                cur_disp=cur_disp,
                new_raw=new_raw,
                new_disp=new_disp,
            )

            # Preserve user include choice when it's still enabled.
            if updated.include_enabled:
                if row.include_enabled and not row.include_checked:
                    updated.include_checked = False
                    updated.action = "Skipped"
                else:
                    updated.include_checked = True
                    updated.action = updated.base_action

            self._rows[model_idx] = updated

            it_sort = self._tbl.item(view_row, 3)
            if isinstance(it_sort, _SortItem):
                it_sort.set_sort_key(updated.new_value_display)

            # Update UI pieces
            w_inc = self._tbl.cellWidget(view_row, 0)
            if isinstance(w_inc, QCheckBox):
                w_inc.blockSignals(True)
                try:
                    w_inc.setEnabled(bool(updated.include_enabled))
                    w_inc.setChecked(bool(updated.include_checked))
                finally:
                    w_inc.blockSignals(False)

            it_inc = self._tbl.item(view_row, 0)
            if isinstance(it_inc, _SortItem):
                it_inc.set_sort_key(1 if updated.include_checked else 0)

            # Current Value might be rendered via an elided widget; always re-render the cell.
            self._set_current_value_cell(view_row, updated)

            # Ensure New Value cell reflects the current full value and elide behavior.
            self._set_new_value_cell(view_row, updated)

            # Action label
            it_act = self._tbl.item(view_row, 4)
            if it_act is not None:
                it_act.setText(updated.action)
                if isinstance(it_act, _SortItem):
                    it_act.set_sort_key(updated.action)

            self._apply_row_background(view_row, updated.action)
            self._apply_row_foreground(view_row)
        finally:
            self._tbl.blockSignals(False)

        self._update_apply_enabled()
        self._update_counts_label()

    def _create_json_clicked(self, game_id: str) -> None:
        model_idx = self._model_row_index_for_game_id(game_id)
        if model_idx is None:
            return
        row = self._rows[model_idx]
        if row.has_file:
            return

        data = {
            "name": row.basename,
            "nb_players": "",
            "editor": "",
            "year": 0,
            "description": {lang: " " for lang in _LANGS},
        }
        try:
            _write_json_dict(row.json_path, data)
        except Exception as e:
            QMessageBox.warning(self, "Create JSON", str(e))
            return

        # Re-run preview for this row
        try:
            parts = _split_key_path(self._key_path)
            data2 = _load_json_dict(row.json_path)
            had_key, cur_raw = _get_at_path(data2, parts)
            cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path)
            new_raw = self._selected_value_for_row(cur_raw, key_present=had_key)
            new_disp = "" if self._remove_mode else _display_value(new_raw, field_type=self._field_type, key_path=self._key_path)
            updated = self._evaluate_row(
                game_id=row.game_id,
                folder=row.folder,
                basename=row.basename,
                json_path=row.json_path,
                has_file=True,
                had_key=had_key,
                cur_raw=cur_raw,
                cur_disp=cur_disp,
                new_raw=new_raw,
                new_disp=new_disp,
            )
            self._rows[model_idx] = updated
            self._rebuild_table()
        except Exception:
            self._rebuild_table()

        self._update_apply_enabled()

    def _perform_updates(self) -> None:
        parts = _split_key_path(self._key_path)
        if not parts:
            return

        applied: set[int] = set()

        # Apply updates
        for idx, row in enumerate(list(self._rows)):
            if not row.include_checked:
                continue
            if not row.has_file:
                continue
            applied.add(idx)

            data = _load_json_dict(row.json_path)

            if self._remove_mode:
                _del_at_path(data, parts)
                try:
                    _write_json_dict(row.json_path, data)
                except Exception as e:
                    QMessageBox.warning(self, "Bulk JSON Update", f"Failed updating {row.json_path}: {e}")
                    return
                continue

            # Read new value from our model (sorting-safe).
            new_raw: object
            if self._field_type == "number":
                try:
                    new_raw = int(str(row.new_value_display).strip() or "0")
                except Exception:
                    new_raw = 0
            elif self._field_type == "bool":
                new_raw = str(row.new_value_display).strip().lower() in {"1", "true", "yes", "on"}
            else:
                new_raw = str(row.new_value_display)

            if self._field_type == "text" and self._key_path.startswith("description/"):
                new_raw = _desc_for_json(str(new_raw))

            _set_at_path(data, parts, new_raw)

            try:
                _write_json_dict(row.json_path, data)
            except Exception as e:
                QMessageBox.warning(self, "Bulk JSON Update", f"Failed updating {row.json_path}: {e}")
                return

        self._refresh_after_apply(applied)

    def _refresh_after_apply(self, applied_rows: set[int]) -> None:
        parts = _split_key_path(self._key_path)
        if not parts:
            return

        refreshed: list[_Row] = []
        for idx, row in enumerate(list(self._rows)):
            has_file = bool(row.json_path.exists())
            data = _load_json_dict(row.json_path) if has_file else {}
            had_key, cur_raw = _get_at_path(data, parts) if has_file else (False, None)
            cur_disp = _display_value(cur_raw, field_type=self._field_type, key_path=self._key_path)

            if self._remove_mode:
                # New Value stays blank in remove mode.
                base = self._evaluate_row(
                    game_id=row.game_id,
                    folder=row.folder,
                    basename=row.basename,
                    json_path=row.json_path,
                    has_file=has_file,
                    had_key=had_key,
                    cur_raw=cur_raw,
                    cur_disp=cur_disp,
                    new_raw=None,
                    new_disp="",
                )
            else:
                # Keep the user's edited new value unless this row was applied.
                if idx in applied_rows:
                    new_disp = cur_disp
                else:
                    new_disp = row.new_value_display

                if self._field_type == "number":
                    try:
                        new_raw = int(str(new_disp).strip() or "0")
                    except Exception:
                        new_raw = 0
                elif self._field_type == "bool":
                    new_raw = str(new_disp).strip().lower() in {"1", "true", "yes", "on"}
                else:
                    new_raw = str(new_disp)

                base = self._evaluate_row(
                    game_id=row.game_id,
                    folder=row.folder,
                    basename=row.basename,
                    json_path=row.json_path,
                    has_file=has_file,
                    had_key=had_key,
                    cur_raw=cur_raw,
                    cur_disp=cur_disp,
                    new_raw=new_raw,
                    new_disp=str(new_disp),
                )

            if idx in applied_rows and base.has_file:
                # Force post-apply state per spec.
                base.current_value_display = cur_disp
                base.new_value_display = cur_disp if not self._remove_mode else ""
                base.include_enabled = False
                base.include_checked = False
                base.new_value_editable = True
                base.base_action = "Already Set"
                base.action = "Already Set"

            refreshed.append(base)

        self._rows = refreshed
        self._rebuild_table()

        self._update_apply_enabled()
