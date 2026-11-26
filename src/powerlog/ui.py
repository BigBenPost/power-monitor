from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from powerlog import __version__
from powerlog.brand import CONTACT_EMAIL
from powerlog.controller import Controller
from powerlog.storage import Settings, day_bounds
from powerlog.widgets import ACCENT, MUTED, DailyBars, PowerChart, icon

STYLE = """
QWidget { color: #1D1B18; font-size: 13px; }
QMainWindow, QWidget#surface { background: #F9F8F5; }
QWidget#topbar { background: #F9F8F5; border-bottom: 1px solid #EDEAE5; }
QLabel { background: transparent; border: none; }
QLabel#muted { color: #9B958D; font-size: 12px; }
QLabel#tertiary { color: #C5BFB7; font-size: 11px; }
QLabel#eyebrow { color: #C5BFB7; font-size: 10px; letter-spacing: 2px; }
QLabel#title { font-size: 20px; font-weight: 500; }
QLabel#section { font-size: 14px; font-weight: 500; }
QLabel#hero { font-size: 68px; }
QLabel#unit { font-size: 18px; color: #C5BFB7; }
QLabel#metric { font-size: 30px; }
QFrame#card { background: #FFFFFF; border: 1px solid #EDEAE5; border-radius: 16px; }
QFrame#notice { background: #F5EFE8; border: none; border-radius: 10px; }
QPushButton {
  background: #FFFFFF; border: 1px solid #EDEAE5; border-radius: 8px;
  padding: 8px 16px; min-height: 18px;
}
QPushButton:hover { background: #F5F3EF; border-color: #D8D2CA; }
QPushButton:pressed { background: #EDEAE5; }
QPushButton:focus, QDateEdit:focus, QDoubleSpinBox:focus { border: 1px solid #C2805A; }
QPushButton:disabled { color: #C5BFB7; }
QPushButton#primary { background: #C2805A; color: #FFFFFF; border-color: #C2805A; }
QPushButton#primary:hover { background: #B0734F; }
QPushButton#link { color: #C2805A; background: transparent; border: none; padding: 3px; }
QPushButton#nav {
  text-align: center; background: transparent; border: none;
  padding: 6px 0; font-size: 13px; color: #9B958D;
}
QPushButton#nav:hover { color: #1D1B18; }
QPushButton#nav:checked { color: #C2805A; }
QPushButton#segment {
  background: transparent; border: none; border-radius: 6px;
  padding: 4px 12px; min-height: 14px; font-size: 11px;
}
QPushButton#segment:checked { background: #C2805A; color: white; }
QFrame#segment-group {
  background: transparent; border: 1px solid #EDEAE5; border-radius: 8px;
}
QProgressBar { background: #F4F2EE; border: none; border-radius: 2px; max-height: 3px; }
QProgressBar::chunk { background: #C2805A; border-radius: 2px; }
QTableWidget {
  background: #FFFFFF; alternate-background-color: #FCFBF9;
  border: none; gridline-color: #F0EDEA; selection-background-color: #F5EFE8;
  selection-color: #1D1B18; outline: none;
}
QTableWidget::item { padding: 8px; border: none; }
QHeaderView::section {
  background: #FAFAF8; color: #9B958D; border: none;
  border-bottom: 1px solid #EDEAE5; padding: 10px 8px; text-align: left;
}
QDoubleSpinBox, QDateEdit {
  background: #FFFFFF; border: 1px solid #EDEAE5; border-radius: 8px;
  padding: 8px; min-height: 18px;
}
QCheckBox { spacing: 9px; padding: 6px 0; }
QCheckBox::indicator { width: 16px; height: 16px; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: #F9F8F5; }
QScrollBar:vertical { background: transparent; width: 6px; margin: 3px 0; }
QScrollBar::handle:vertical { background: #DED8CF; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { color: #1D1B18; background: #FFFFFF; border: 1px solid #EDEAE5; padding: 7px; }
QMenu { background: #FFFFFF; border: 1px solid #EDEAE5; padding: 5px; border-radius: 8px; }
QMenu::item { padding: 7px 24px; }
QMenu::item:selected { background: #F5EFE8; }
"""


def label(text="", role="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(role)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, role=""):
    widget = QPushButton(text)
    widget.setObjectName(role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(14)
    return widget, layout


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(43)
    widget.setShowGrid(False)
    widget.setAlternatingRowColors(True)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    widget.setMinimumWidth(0)
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


def duration(seconds):
    minutes = int(seconds // 60)
    return f"{minutes // 60} 小时 {minutes % 60:02} 分钟"


def _light_font(size, spacing=0):
    f = QFont(QApplication.font())
    f.setPixelSize(size)
    f.setWeight(QFont.Weight.Light)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


class SettingsPage(QWidget):
    def __init__(self, controller: Controller, on_save):
        super().__init__()
        self.ctrl, self.on_save = controller, on_save
        self.dirty = False
        self.ids = []
        self.missing = set()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        sensor_card, layout = card()
        heading = QHBoxLayout()
        heading.addWidget(label("功率传感器", "section"))
        heading.addStretch()
        heading.addWidget(button("刷新传感器", self.ctrl.poll, "link"))
        layout.addLayout(heading)
        layout.addWidget(
            label(
                "选择互不重叠的功率项目，例如 CPU Package + GPU Power。"
                "选择总功率后，请勿再叠加其子项。",
                "muted",
                True,
            )
        )
        self.sensors_table = table(["计入", "传感器 / ID", "当前功率"])
        self.sensors_table.setAccessibleName("选择计入耗电统计的 AIDA64 功率传感器")
        self.sensors_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.sensors_table.setColumnWidth(0, 60)
        self.sensors_table.setMinimumHeight(200)
        self.sensors_table.itemChanged.connect(self.mark_dirty)
        layout.addWidget(self.sensors_table)
        layout.addWidget(
            label(
                "没有出现传感器？在 AIDA64 → 文件 → 设置 → 硬件监控 → 外部程序中，"
                "启用共享内存，并勾选需要导出的功率项目。",
                "muted",
                True,
            )
        )
        root.addWidget(sensor_card, 3)
        options, layout = card()
        layout.addWidget(label("估算与后台运行", "section"))
        row = QHBoxLayout()
        row.addWidget(label("电价"))
        self.tariff = QDoubleSpinBox()
        self.tariff.setAccessibleName("每千瓦时电价，单位元")
        self.tariff.setRange(0, 100)
        self.tariff.setDecimals(4)
        self.tariff.setSingleStep(0.01)
        self.tariff.setSuffix(" 元 / kWh")
        self.tariff.valueChanged.connect(self.mark_dirty)
        row.addWidget(self.tariff)
        row.addSpacing(25)
        row.addWidget(label("额外功率"))
        self.overhead = QDoubleSpinBox()
        self.overhead.setAccessibleName("额外固定功率，单位瓦")
        self.overhead.setRange(0, 10000)
        self.overhead.setDecimals(1)
        self.overhead.setSuffix(" W")
        self.overhead.valueChanged.connect(self.mark_dirty)
        row.addWidget(self.overhead)
        layout.addLayout(row)
        layout.addWidget(
            label(
                "额外功率用于粗略补偿未被传感器覆盖的设备，默认为 0。"
                "修改电价会按新单价显示所有历史电费，不影响耗电量。",
                "muted",
                True,
            )
        )
        self.tray_check = QCheckBox("关闭窗口时收起到托盘，继续每分钟记录")
        self.tray_check.stateChanged.connect(self.mark_dirty)
        layout.addWidget(self.tray_check)
        root.addWidget(options)
        data_row = QHBoxLayout()
        path_label = label(f"数据保存在本机：{self.ctrl.store.path}", "muted", True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setMinimumWidth(0)
        path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        data_row.addWidget(path_label, 1)
        data_row.addWidget(button("打开文件夹 →", self.open_folder, "link"))
        root.addLayout(data_row)
        self.author_label = label(
            f"Powerlog v{__version__} · Have a problem? Contact "
            f'<a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>',
            "muted",
            True,
        )
        self.author_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.author_label.setOpenExternalLinks(True)
        root.addWidget(self.author_label)
        bottom = QHBoxLayout()
        self.feedback = label("修改传感器或额外功率后，将从新的有效采样重新累计。", "muted", True)
        bottom.addWidget(self.feedback, 1)
        bottom.addWidget(button("还原修改", self.reload))
        self.save_button = button("保存设置", self.save, "primary")
        bottom.addWidget(self.save_button)
        root.addLayout(bottom)
        self.reload()

    def mark_dirty(self, *args):
        self.dirty = True
        self.feedback.setText("有未保存的修改")

    def checked_ids(self):
        return tuple(
            sensor_id
            for i, sensor_id in enumerate(self.ids)
            if self.sensors_table.item(i, 0).checkState() == Qt.CheckState.Checked
        )

    def reload(self):
        settings = self.ctrl.store.load_settings()
        self.tariff.setValue(settings.tariff)
        self.overhead.setValue(settings.overhead_watts)
        self.tray_check.setChecked(settings.close_to_tray)
        self.dirty = False
        self.refresh_sensors(force=True)
        self.feedback.setText("修改传感器或额外功率后，将从新的有效采样重新累计。")

    def refresh_sensors(self, force=False):
        sensor_key = (tuple(self.ctrl.sensors), self.ctrl.connected)
        if not force and sensor_key == getattr(self, "_sensor_key", None):
            return
        checked = (
            self.checked_ids()
            if self.dirty and not force
            else self.ctrl.store.load_settings().sensor_ids
        )
        sensors = {sensor.id: sensor for sensor in self.ctrl.sensors}
        ids = list(sensors) + sorted(set(checked) - sensors.keys())
        self.sensors_table.blockSignals(True)
        self.sensors_table.setRowCount(len(ids))
        self.ids = ids
        self.missing = set(checked) - sensors.keys()
        for i, sensor_id in enumerate(ids):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(
                Qt.CheckState.Checked if sensor_id in checked else Qt.CheckState.Unchecked
            )
            self.sensors_table.setItem(i, 0, check)
            sensor = sensors.get(sensor_id)
            text = f"{sensor.label}  ·  {sensor_id}" if sensor else sensor_id
            self.sensors_table.setItem(i, 1, QTableWidgetItem(text))
            value = f"{sensor.watts:g} W" if sensor and self.ctrl.connected else "暂不可用"
            self.sensors_table.setItem(i, 2, QTableWidgetItem(value))
        self.sensors_table.blockSignals(False)
        self._sensor_key = sensor_key

    def save(self):
        try:
            old = self.ctrl.store.load_settings()
            new = Settings(
                self.checked_ids(),
                self.tariff.value(),
                self.overhead.value(),
                self.tray_check.isChecked(),
            )
            self.ctrl.store.save_settings(new)
            self.dirty = False
            if old.signature != new.signature:
                self.ctrl.reset_sampling()
            self.feedback.setText("已保存")
            self.on_save()
            self.ctrl.poll()
        except (ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "无法保存设置", str(exc))

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctrl.store.path.parent)))


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller, demo=False):
        super().__init__()
        self.ctrl, self.demo = controller, demo
        self.history_day = controller.clock().date()
        self.period = 7
        self.quitting = False
        self.tray_notified = False
        self._overview_key = self._history_key = self._history_table_key = None
        self._sensor_rows_key = None
        self.export_dialog = None
        self.setWindowTitle("电量 · Powerlog" + (" · 演示模式" if demo else ""))
        self.setWindowIcon(icon("power", ACCENT, 32))
        self.resize(1120, 880)
        self.setMinimumSize(880, 700)
        self.setStyleSheet(STYLE)
        surface = QWidget()
        surface.setObjectName("surface")
        self.setCentralWidget(surface)
        outer = QVBoxLayout(surface)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Top bar ──
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(28, 14, 28, 14)
        logo = QLabel()
        logo.setPixmap(icon("power", ACCENT, 20).pixmap(20, 20))
        topbar_layout.addWidget(logo)
        topbar_layout.addSpacing(8)
        name = label("Powerlog")
        name.setStyleSheet("font-size: 15px; font-weight: 500;")
        topbar_layout.addWidget(name)
        topbar_layout.addStretch()
        self.nav_buttons = []
        for index, text in enumerate(("概览", "历史", "设置")):
            item = button(text, lambda checked=False, i=index: self.show_page(i), "nav")
            item.setCheckable(True)
            topbar_layout.addWidget(item)
            if index < 2:
                topbar_layout.addSpacing(20)
            self.nav_buttons.append(item)
        topbar_layout.addStretch()
        self.status_label = label("● 正在连接…", "muted")
        topbar_layout.addWidget(self.status_label)
        outer.addWidget(topbar)

        # ── Main content ──
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(36, 24, 36, 14)
        main_layout.setSpacing(14)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(6)
        self.date_label = label("", "tertiary")
        self.page_title = label("", "title")
        titles.addWidget(self.date_label)
        titles.addWidget(self.page_title)
        header.addLayout(titles)
        header.addStretch()
        self.today_button = button(
            "今天 →", lambda: self.open_history(self.ctrl.clock().date()), "link"
        )
        header.addWidget(self.today_button)
        main_layout.addLayout(header)

        self.notice = QFrame()
        self.notice.setObjectName("notice")
        notice_row = QHBoxLayout(self.notice)
        notice_row.setContentsMargins(14, 8, 14, 8)
        self.notice_label = label("", wrap=True)
        notice_row.addWidget(self.notice_label, 1)
        notice_row.addWidget(button("查看设置 →", lambda: self.show_page(2), "link"))
        main_layout.addWidget(self.notice)

        self.pages = QStackedWidget()
        self.overview = self.build_overview()
        self.history = self.build_history()
        self.settings_page = SettingsPage(self.ctrl, self.refresh)
        for page in (self.overview, self.history, self.settings_page):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.pages.addWidget(scroll)
        main_layout.addWidget(self.pages, 1)

        footer = QHBoxLayout()
        footer.addWidget(label("所选硬件功耗估算 · 数据缺口不累计", "tertiary"))
        footer.addStretch()
        self.updated_label = label("", "tertiary")
        footer.addWidget(self.updated_label)
        main_layout.addLayout(footer)

        outer.addWidget(main, 1)
        self.setup_tray()
        self.ctrl.updated.connect(self.refresh)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(15000)
        self.clock_timer.timeout.connect(self.refresh)
        self.clock_timer.start()
        self.show_page(0)

    def build_overview(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(24)

        # ── Hero section ──
        hero = QHBoxLayout()
        hero.setSpacing(24)
        hero_left = QVBoxLayout()
        hero_left.setSpacing(4)
        hero_left.addWidget(label("今日累计耗电", "muted"))
        hero_left.addSpacing(4)
        number = QHBoxLayout()
        number.setSpacing(8)
        self.energy_label = label("—", "hero")
        self.energy_label.setFont(_light_font(68, -3))
        number.addWidget(self.energy_label, 0, Qt.AlignmentFlag.AlignBaseline)
        number.addWidget(label("kWh", "unit"), 0, Qt.AlignmentFlag.AlignBaseline)
        number.addStretch()
        hero_left.addLayout(number)
        self.recorded_label = label("尚未开始记录", "tertiary")
        hero_left.addWidget(self.recorded_label)
        hero_left.addStretch()
        hero.addLayout(hero_left, 1)

        metrics_frame = QFrame()
        metrics_frame.setObjectName("card")
        metrics_inner = QHBoxLayout(metrics_frame)
        metrics_inner.setContentsMargins(0, 0, 0, 0)
        metrics_inner.setSpacing(0)
        mfont = _light_font(30, -1)

        power_cell = QWidget()
        power_cell.setMinimumWidth(140)
        pl = QVBoxLayout(power_cell)
        pl.setContentsMargins(24, 20, 24, 20)
        pl.setSpacing(0)
        pl.addWidget(label("当前功率", "muted"))
        pl.addSpacing(14)
        self.power_label = label("— W", "metric")
        self.power_label.setFont(mfont)
        pl.addWidget(self.power_label)
        pl.addStretch()
        metrics_inner.addWidget(power_cell)

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet("background: #EDEAE5;")
        metrics_inner.addWidget(divider)

        cost_cell = QWidget()
        cost_cell.setMinimumWidth(130)
        cl = QVBoxLayout(cost_cell)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(0)
        cl.addWidget(label("今日电费", "muted"))
        cl.addSpacing(14)
        self.cost_label = label("¥ —", "metric")
        self.cost_label.setFont(mfont)
        cl.addWidget(self.cost_label)
        cl.addStretch()
        metrics_inner.addWidget(cost_cell)

        hero.addWidget(metrics_frame)
        root.addLayout(hero)

        # ── Chart card ──
        chart_card, chart_layout = card()
        chart_header = QHBoxLayout()
        chart_header.addWidget(label("功率变化", "section"))
        chart_header.addWidget(label("今日", "tertiary"))
        chart_header.addStretch()
        chart_header.addWidget(label("所选传感器合计", "tertiary"))
        chart_layout.addLayout(chart_header)
        self.chart = PowerChart()
        chart_layout.addWidget(self.chart, 1)
        root.addWidget(chart_card, 3)

        # ── Bottom row ──
        bottom = QHBoxLayout()
        bottom.setSpacing(16)

        weekly, wl = card()
        heading = QHBoxLayout()
        heading.addWidget(label("每日耗电", "section"))
        heading.addWidget(label("kWh", "tertiary"))
        heading.addStretch()
        segment_group = QFrame()
        segment_group.setObjectName("segment-group")
        seg_layout = QHBoxLayout(segment_group)
        seg_layout.setContentsMargins(0, 0, 0, 0)
        seg_layout.setSpacing(0)
        self.period_buttons = []
        for days in (7, 30):
            item = button(f"{days}天", lambda checked=False, d=days: self.set_period(d), "segment")
            item.setCheckable(True)
            item.setChecked(days == self.period)
            seg_layout.addWidget(item)
            self.period_buttons.append(item)
        heading.addWidget(segment_group)
        wl.addLayout(heading)
        self.bars = DailyBars()
        self.bars.day_clicked.connect(self.open_history)
        wl.addWidget(self.bars, 1)
        bottom.addWidget(weekly, 5)

        sensors, sl = card()
        s_heading = QHBoxLayout()
        s_heading.addWidget(label("传感器", "section"))
        s_heading.addStretch()
        s_heading.addWidget(button("配置 →", lambda: self.show_page(2), "link"))
        sl.addLayout(s_heading)
        self.sensor_rows = QVBoxLayout()
        self.sensor_rows.setSpacing(10)
        sl.addLayout(self.sensor_rows, 1)
        sl.addWidget(label("色条表示占比", "tertiary"))
        bottom.addWidget(sensors, 3)

        root.addLayout(bottom, 2)
        return page

    def build_history(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(15)
        controls = QHBoxLayout()
        self.history_date = QDateEdit()
        self.history_date.setCalendarPopup(True)
        self.history_date.setDisplayFormat("yyyy年MM月dd日")
        self.history_date.setDate(QDate(self.history_day))
        self.history_date.setMaximumDate(QDate(self.history_day))
        self.history_date.setAccessibleName("查看历史用电日期")
        self.history_date.dateChanged.connect(self.change_history_date)
        controls.addWidget(self.history_date)
        self.history_summary = label("", "muted")
        self.history_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self.history_summary, 1)
        controls.addWidget(button("导出近 30 天 CSV", self.export_csv))
        root.addLayout(controls)
        panel, layout = card()
        layout.addWidget(label("当日功率", "section"))
        self.history_chart = PowerChart()
        self.history_chart.setMinimumHeight(180)
        layout.addWidget(self.history_chart)
        root.addWidget(panel, 2)
        panel, layout = card()
        layout.addWidget(label("近 30 天记录", "section"))
        self.history_table = table(["日期", "耗电 / kWh", "估算电费 / 元", "已记录", "峰值 / W"])
        self.history_table.setMinimumHeight(220)
        self.history_table.itemSelectionChanged.connect(self.select_history_row)
        layout.addWidget(self.history_table)
        layout.addWidget(
            label("— 表示尚无有效累计区间；有数据的日期也可能包含未记录时段。", "muted")
        )
        root.addWidget(panel, 3)
        return page

    def setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction("显示 Powerlog", self.reveal)
        menu.addAction("立即采样", self.ctrl.poll)
        menu.addSeparator()
        menu.addAction("退出并停止记录", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.reveal()
                if reason
                in (
                    QSystemTrayIcon.ActivationReason.Trigger,
                    QSystemTrayIcon.ActivationReason.DoubleClick,
                )
                else None
            )
        )
        self.tray.setToolTip("电量 · Powerlog")
        self.tray.show()

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        if self.settings_page.dirty:
            self.reveal()
            answer = QMessageBox.question(
                self,
                "有未保存的设置",
                "放弃未保存的修改并退出？",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        self.quitting = True
        QApplication.quit()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
            return
        if self.tray and self.ctrl.store.load_settings().close_to_tray and not self.quitting:
            self.hide()
            event.ignore()
            if not self.tray_notified:
                self.tray.showMessage("Powerlog 正在后台记录", "从托盘菜单退出可停止采样。")
                self.tray_notified = True
        else:
            event.ignore()
            self.quit_app()

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        self.page_title.setText(("", "历史记录", "偏好设置")[index])
        self.page_title.setVisible(index != 0)
        self.today_button.setVisible(index == 0)
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == index)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def set_period(self, days):
        self.period = days
        for item, value in zip(self.period_buttons, (7, 30), strict=True):
            item.setChecked(value == days)
        self.refresh()

    def open_history(self, day):
        self.history_date.setMaximumDate(QDate(self.ctrl.clock().date()))
        self.history_date.setDate(QDate(day))
        self.change_history_date(self.history_date.date())
        self.show_page(1)

    def change_history_date(self, value):
        self.history_day = value.toPython()
        self.refresh()

    def select_history_row(self):
        row = self.history_table.currentRow()
        if row >= 0:
            item = self.history_table.item(row, 0)
            if item:
                self.history_date.setDate(QDate.fromString(item.text(), "yyyy-MM-dd"))

    def refresh_history_chart(self):
        key = (self.history_day, day_bounds(self.history_day), self.ctrl.store.revision)
        if key == self._history_key:
            return
        total = self.ctrl.store.daily(self.history_day)
        self.history_chart.set_data(
            self.history_day,
            self.ctrl.store.points(self.history_day),
            self.ctrl.store.intervals(self.history_day),
        )
        if total.recorded_seconds:
            self.history_summary.setText(
                f"  {total.kwh:.3f} kWh · 已记录 {duration(total.recorded_seconds)}"
            )
        else:
            self.history_summary.setText("  暂无有效累计区间")
        self._history_key = key

    def refresh(self):
        try:
            self._refresh()
        except (sqlite3.Error, ValueError) as exc:
            self.notice.setVisible(True)
            self.notice_label.setText(f"无法读取本机记录：{exc}")
            self.status_label.setText("● 数据读取失败")

    def _refresh(self):
        now = self.ctrl.clock()
        today = now.date()
        settings = self.ctrl.store.load_settings()
        total = self.ctrl.store.daily(today)
        self.date_label.setText(
            f"{now.year}年{now.month}月{now.day}日 · 星期{'一二三四五六日'[now.weekday()]}"
        )
        fresh = self.ctrl.is_fresh(now)
        self.notice.setVisible(bool(self.ctrl.error) or not fresh)
        self.notice_label.setText(self.ctrl.error or "等待新的有效采样；空档时间不会计入耗电量。")
        if self.ctrl.connected and fresh:
            status, color = "● 已连接", "#668451"
        elif self.ctrl.connected and not settings.sensor_ids:
            status, color = "● 已连接 · 待配置", ACCENT
        elif self.ctrl.connected:
            status, color = "● 采样暂停", ACCENT
        else:
            status, color = "● 未连接", MUTED
        if self.demo:
            status = "● 演示模式"
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.status_label.setToolTip(self.ctrl.error)
        self.updated_label.setText(
            "更新于 " + now.fromtimestamp(self.ctrl.reading.timestamp).strftime("%H:%M")
            if self.ctrl.reading
            else "尚无有效采样"
        )
        if self.tray:
            self.tray.setToolTip(f"Powerlog · 今日 {total.kwh:.3f} kWh\n{status}")
        if not self.isVisible():
            return
        page = self.pages.currentIndex()
        if page == 0:
            self.refresh_overview(today, total, settings, fresh)
        elif page == 1:
            self.history_date.setMaximumDate(QDate(today))
            self.refresh_history_chart()
            self.refresh_history_table(today, settings)
        else:
            self.settings_page.refresh_sensors()

    def refresh_overview(self, today, total, settings, fresh):
        self.power_label.setText(f"{self.ctrl.reading.watts:g} W" if fresh else "— W")
        key = (today, day_bounds(today), self.ctrl.store.revision, self.period)
        if key != self._overview_key:
            points = self.ctrl.store.points(today)
            self.energy_label.setText(f"{total.kwh:.2f}" if points else "—")
            self.cost_label.setText(f"¥{total.kwh * settings.tariff:.2f}" if points else "¥ —")
            self.recorded_label.setText(
                "已记录 " + duration(total.recorded_seconds) if points else "尚未开始记录"
            )
            self.chart.set_data(today, points, self.ctrl.store.intervals(today))
            self.bars.set_data(self.ctrl.store.days(today, self.period), today)
            self._overview_key = key
        self.refresh_sensor_rows(settings, fresh)

    def refresh_history_table(self, today, settings):
        key = (
            today,
            day_bounds(today),
            self.ctrl.store.revision,
            settings.tariff,
            self.history_day,
        )
        if key == self._history_table_key:
            return
        self.history_table.blockSignals(True)
        days = list(reversed(self.ctrl.store.days(today, 30)))
        self.history_table.setRowCount(len(days))
        selected = -1
        for i, day in enumerate(days):
            active = day.recorded_seconds > 0
            values = [
                day.day.isoformat(),
                f"{day.kwh:.3f}" if active else "—",
                f"{day.kwh * settings.tariff:.2f}" if active else "—",
                duration(day.recorded_seconds),
                f"{day.peak_watts:g}" if active else "—",
            ]
            for j, value in enumerate(values):
                self.history_table.setItem(i, j, QTableWidgetItem(value))
            if day.day == self.history_day:
                selected = i
        if selected >= 0:
            self.history_table.setCurrentCell(selected, 0)
        self.history_table.blockSignals(False)
        self._history_table_key = key

    def refresh_sensor_rows(self, settings, fresh):
        key = (settings.signature, tuple(self.ctrl.sensors), self.ctrl.reading, fresh)
        if key == self._sensor_rows_key:
            return
        self._sensor_rows_key = key
        while self.sensor_rows.count():
            item = self.sensor_rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        sensors = {sensor.id: sensor for sensor in self.ctrl.sensors}
        keys = list(settings.sensor_ids)
        if settings.overhead_watts:
            keys.append("__overhead__")
        if not keys:
            self.sensor_rows.addWidget(label("选择功率传感器后开始记录", "muted", True))
            return
        for key in keys[:3]:
            sensor = sensors.get(key)
            text = "额外固定功率" if key == "__overhead__" else sensor.label if sensor else key
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)
            title = QHBoxLayout()
            name = label(text)
            name.setMinimumWidth(0)
            name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            name.setToolTip(text)
            title.addWidget(name, 1)
            watts = self.ctrl.reading.components.get(key, 0) if fresh else None
            title.addWidget(label(f"{watts:g} W" if watts is not None else "— W"))
            layout.addLayout(title)
            meter = QProgressBar()
            meter.setRange(0, 1000)
            meter.setTextVisible(False)
            meter.setAccessibleName(f"{text} 占当前功率的比例")
            meter.setValue(
                round(watts / self.ctrl.reading.watts * 1000)
                if fresh and self.ctrl.reading.watts > 0
                else 0
            )
            layout.addWidget(meter)
            self.sensor_rows.addWidget(row)
        if len(keys) > 3:
            self.sensor_rows.addWidget(label(f"另有 {len(keys) - 3} 项，见偏好设置", "muted"))
        self.sensor_rows.addStretch()

    def export_csv(self):
        if self.export_dialog is not None:
            self.export_dialog.raise_()
            self.export_dialog.activateWindow()
            return
        dialog = QFileDialog(self, "导出近 30 天记录")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilter("CSV 文件 (*.csv)")
        dialog.setDefaultSuffix("csv")
        dialog.selectFile(str(Path.home() / f"Powerlog-{self.ctrl.clock():%Y%m%d}.csv"))
        dialog.fileSelected.connect(self.export_selected)
        dialog.finished.connect(self.close_export_dialog)
        self.export_dialog = dialog
        # Native Windows save dialogs block QTimers, including the sampling timer.
        dialog.open()

    def close_export_dialog(self, result):
        self.export_dialog.deleteLater()
        self.export_dialog = None

    def export_selected(self, path):
        try:
            self.write_csv(Path(path))
        except (OSError, sqlite3.Error, ValueError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
        else:
            QMessageBox.information(self, "已导出", "已保存近 30 天的估算数据。")

    def write_csv(self, path: Path):
        settings = self.ctrl.store.load_settings()
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                ["日期", "耗电量_kWh", "估算电费_元", "已记录_分钟", "峰值_W", "电价_元每kWh"]
            )
            for day in self.ctrl.store.days(self.ctrl.clock().date(), 30):
                active = day.recorded_seconds > 0
                writer.writerow(
                    [
                        day.day.isoformat(),
                        f"{day.kwh:.6f}" if active else "",
                        f"{day.kwh * settings.tariff:.4f}" if active else "",
                        f"{day.recorded_seconds / 60:.2f}",
                        f"{day.peak_watts:g}" if active else "",
                        settings.tariff,
                    ]
                )
