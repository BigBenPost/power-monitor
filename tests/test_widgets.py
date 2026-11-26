from PySide6.QtCore import QPointF

from powerlog.widgets import PowerChart


def test_chart_path_preserves_power_and_time_bounds(qapp):
    chart = PowerChart()
    for values in (
        [(0, 0), (60, 100), (120, 100), (180, 0)],
        [(0, 0), (60, 0), (120, 100)],
        [(0, 100), (1, 0), (90, 100)],
    ):
        path = chart._line_path([QPointF(x, y) for x, y in values])
        previous_x = -1
        for index in range(301):
            point = path.pointAtPercent(index / 300)
            assert -1e-9 <= point.y() <= 100 + 1e-9
            assert point.x() >= previous_x - 1e-9
            previous_x = point.x()
