"""Compact, email-safe PNG charts for the weekly report."""

from __future__ import annotations

from io import BytesIO
import math
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont


SALES_CHART_CID = "rcj-weekly-sales"
ACQUISITION_CHART_CID = "rcj-acquisition-mix"
COUNTRIES_STOCK_CHART_CID = "rcj-countries-stock"

CHART_FILENAMES = {
    SALES_CHART_CID: "weekly-sales.png",
    ACQUISITION_CHART_CID: "acquisition-mix.png",
    COUNTRIES_STOCK_CHART_CID: "countries-stock.png",
}

WIDTH = 640
HEIGHT = 270

BACKGROUND = "#F4F1EA"
SURFACE = "#FFFFFF"
INK = "#17231C"
MUTED = "#68756D"
GRID = "#E4E7E2"
GREEN = "#247454"
GREEN_LIGHT = "#CFE5D8"
GOLD = "#D6A33C"
RED = "#B64B4B"
BLUE = "#527AA3"
PURPLE = "#7967A8"
PALETTE = (GREEN, GOLD, BLUE, PURPLE, "#9B6B4D", "#66958D")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _font(size: int, *, bold: bool = False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(filename, size=size)
    except OSError:
        return ImageFont.load_default()


TITLE_FONT = _font(20, bold=True)
SUBTITLE_FONT = _font(11)
LABEL_FONT = _font(10)
LABEL_BOLD_FONT = _font(10, bold=True)
METRIC_FONT = _font(18, bold=True)


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (5, 5, WIDTH - 6, HEIGHT - 6),
        radius=14,
        fill=SURFACE,
        outline=GRID,
        width=1,
    )
    return image, draw


def _png(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=True)
    return stream.getvalue()


def _short_money(value: float, currency: str = "") -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        result = f"{value / 1_000_000:.1f}m"
    elif absolute >= 1_000:
        result = f"{value / 1_000:.1f}k"
    else:
        result = f"{value:,.0f}"
    return f"{currency} {result}".strip()


def _short_date(value: Any) -> str:
    text = str(value or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return f"{text[5:7]}/{text[8:10]}"
    return text[:8] or "—"


def _fit_label(value: Any, maximum: int = 23) -> str:
    text = " ".join(str(value or "Unknown").split())
    if len(text) <= maximum:
        return text
    return text[: max(maximum - 1, 1)].rstrip() + "…"


def _empty_state(draw: ImageDraw.ImageDraw, message: str) -> None:
    draw.rounded_rectangle((24, 80, WIDTH - 24, HEIGHT - 28), 10, fill=BACKGROUND)
    draw.text((WIDTH / 2, 158), message, font=SUBTITLE_FONT, fill=MUTED, anchor="mm")


def render_sales_chart(snapshot: Mapping[str, Any] | None) -> bytes:
    """Render the eight-week net-collected-revenue trend."""

    source = _mapping(snapshot)
    raw_trend = source.get("trend")
    trend = list(raw_trend[-8:]) if isinstance(raw_trend, (list, tuple)) else []
    values = [max(_number(_mapping(row).get("net_sales")), 0.0) for row in trend]
    currency = str(source.get("currency") or "USD")

    image, draw = _canvas()
    draw.text((24, 20), "Eight-week net collected", font=TITLE_FONT, fill=INK)
    draw.text(
        (24, 49),
        f"Completed Friday–Thursday windows · {currency}",
        font=SUBTITLE_FONT,
        fill=MUTED,
    )
    if not trend:
        _empty_state(draw, "No weekly sales history available")
        return _png(image)

    left, top, right, bottom = 58, 78, WIDTH - 24, HEIGHT - 38
    maximum = max(values) if values else 0.0
    scale_max = maximum * 1.12 if maximum > 0 else 1.0

    for index in range(4):
        y = top + (bottom - top) * index / 3
        grid_value = scale_max * (1 - index / 3)
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text(
            (left - 7, y),
            _short_money(grid_value),
            font=LABEL_FONT,
            fill=MUTED,
            anchor="rm",
        )

    count = max(len(values), 1)
    slot = (right - left) / count
    bar_width = max(min(slot * 0.48, 30), 8)
    points = []
    for index, value in enumerate(values):
        x = left + slot * (index + 0.5)
        y = bottom - (value / scale_max) * (bottom - top)
        bar_color = GOLD if index == len(values) - 1 else GREEN_LIGHT
        draw.rounded_rectangle(
            (x - bar_width / 2, y, x + bar_width / 2, bottom),
            radius=3,
            fill=bar_color,
        )
        points.append((x, y))
        row = _mapping(trend[index])
        draw.text(
            (x, bottom + 9),
            _short_date(row.get("start") or row.get("end")),
            font=LABEL_FONT,
            fill=MUTED,
            anchor="ma",
        )

    if len(points) > 1:
        draw.line(points, fill=GREEN, width=3, joint="curve")
    for x, y in points:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=SURFACE, outline=GREEN, width=2)
    if values:
        draw.text(
            (points[-1][0], max(points[-1][1] - 10, top + 2)),
            _short_money(values[-1], currency),
            font=LABEL_BOLD_FONT,
            fill=INK,
            anchor="mb",
        )
    return _png(image)


def render_acquisition_chart(snapshot: Mapping[str, Any] | None) -> bytes:
    """Render the attributed online-store acquisition mix."""

    acquisition = _mapping(_mapping(snapshot).get("acquisition"))
    raw_items = acquisition.get("items")
    items = list(raw_items) if isinstance(raw_items, (list, tuple)) else []
    items = items[:5]
    total_sales = sum(max(_number(_mapping(row).get("net_sales")), 0) for row in items)
    total_orders = sum(max(_number(_mapping(row).get("orders")), 0) for row in items)
    use_sales = total_sales > 0
    denominator = total_sales if use_sales else total_orders
    coverage = _number(acquisition.get("order_coverage"), -1)
    confidence = str(acquisition.get("confidence") or "unknown").title()

    image, draw = _canvas()
    draw.text((24, 20), "Acquisition mix", font=TITLE_FONT, fill=INK)
    coverage_text = f"{coverage:.0%} order coverage" if coverage >= 0 else "coverage unavailable"
    draw.text(
        (24, 49),
        f"Online-store first touch · {coverage_text} · {confidence} confidence",
        font=SUBTITLE_FONT,
        fill=MUTED,
    )
    if not items or denominator <= 0:
        _empty_state(draw, "No attributed acquisition mix available")
        return _png(image)

    label_x, bar_left, bar_right = 24, 190, WIDTH - 68
    top = 78
    row_height = 34
    for index, raw_row in enumerate(items):
        row = _mapping(raw_row)
        value = max(
            _number(row.get("net_sales" if use_sales else "orders")),
            0,
        )
        share = value / denominator if denominator else 0
        y = top + index * row_height
        draw.text(
            (label_x, y + 8),
            _fit_label(row.get("label")),
            font=LABEL_BOLD_FONT,
            fill=INK,
            anchor="lm",
        )
        draw.rounded_rectangle(
            (bar_left, y, bar_right, y + 16),
            radius=8,
            fill=BACKGROUND,
        )
        filled_right = bar_left + max((bar_right - bar_left) * share, 2)
        draw.rounded_rectangle(
            (bar_left, y, filled_right, y + 16),
            radius=8,
            fill=PALETTE[index % len(PALETTE)],
        )
        draw.text(
            (WIDTH - 24, y + 8),
            f"{share:.0%}",
            font=LABEL_BOLD_FONT,
            fill=INK,
            anchor="rm",
        )
    return _png(image)


def render_countries_stock_chart(snapshot: Mapping[str, Any] | None) -> bytes:
    """Render leading countries beside the inventory health summary."""

    source = _mapping(snapshot)
    countries = _mapping(source.get("countries")).get("items")
    country_rows = list(countries[:5]) if isinstance(countries, (list, tuple)) else []
    country_total = sum(
        max(_number(_mapping(row).get("net_sales")), 0) for row in country_rows
    )
    if country_total <= 0:
        country_total = sum(
            max(_number(_mapping(row).get("orders")), 0) for row in country_rows
        )
        country_value_key = "orders"
    else:
        country_value_key = "net_sales"
    stock = _mapping(source.get("stock"))
    action_items = stock.get("action_items") or []

    image, draw = _canvas()
    draw.text((24, 20), "Markets & inventory", font=TITLE_FONT, fill=INK)
    draw.text(
        (24, 49),
        "Current-week destination mix and active catalog health",
        font=SUBTITLE_FONT,
        fill=MUTED,
    )
    draw.line((318, 74, 318, HEIGHT - 24), fill=GRID, width=1)

    draw.text((24, 76), "Leading countries", font=LABEL_BOLD_FONT, fill=INK)
    if country_rows and country_total > 0:
        top = 102
        for index, raw_row in enumerate(country_rows):
            row = _mapping(raw_row)
            value = max(_number(row.get(country_value_key)), 0)
            share = value / country_total if country_total else 0
            y = top + index * 29
            draw.text(
                (24, y + 7),
                _fit_label(row.get("label"), maximum=12),
                font=LABEL_BOLD_FONT,
                fill=INK,
                anchor="lm",
            )
            draw.rounded_rectangle((91, y, 259, y + 14), 7, fill=BACKGROUND)
            draw.rounded_rectangle(
                (91, y, 91 + max(168 * share, 2), y + 14),
                7,
                fill=PALETTE[index % len(PALETTE)],
            )
            draw.text(
                (294, y + 7),
                f"{share:.0%}",
                font=LABEL_FONT,
                fill=MUTED,
                anchor="rm",
            )
    else:
        draw.text(
            (24, 111),
            "No country mix available",
            font=SUBTITLE_FONT,
            fill=MUTED,
        )

    draw.text((342, 76), "Inventory snapshot", font=LABEL_BOLD_FONT, fill=INK)
    metrics = (
        ("Sellable", int(_number(stock.get("sellable_units"))), GREEN),
        ("Active SKUs", int(_number(stock.get("active_skus"))), BLUE),
        ("Out of stock", int(_number(stock.get("out_of_stock_skus"))), RED),
        ("Actions", len(action_items), GOLD),
    )
    for index, (label, value, color) in enumerate(metrics):
        column = index % 2
        row = index // 2
        x = 342 + column * 137
        y = 101 + row * 72
        draw.rounded_rectangle((x, y, x + 121, y + 57), 9, fill=BACKGROUND)
        draw.rectangle((x, y, x + 4, y + 57), fill=color)
        draw.text((x + 13, y + 9), label, font=LABEL_FONT, fill=MUTED)
        draw.text(
            (x + 13, y + 27),
            f"{value:,}",
            font=METRIC_FONT,
            fill=INK,
        )

    negative = int(_number(stock.get("negative_inventory_skus")))
    if negative:
        draw.text(
            (342, 246),
            f"{negative:,} SKU{'s' if negative != 1 else ''} with negative inventory",
            font=LABEL_FONT,
            fill=RED,
            anchor="ls",
        )
    return _png(image)


def render_weekly_charts(
    snapshot: Mapping[str, Any] | None,
) -> dict[str, bytes]:
    """Return the three inline images keyed by their stable content IDs."""

    return {
        SALES_CHART_CID: render_sales_chart(snapshot),
        ACQUISITION_CHART_CID: render_acquisition_chart(snapshot),
        COUNTRIES_STOCK_CHART_CID: render_countries_stock_chart(snapshot),
    }


render_sales_trend_chart = render_sales_chart
render_charts = render_weekly_charts


__all__ = [
    "ACQUISITION_CHART_CID",
    "CHART_FILENAMES",
    "COUNTRIES_STOCK_CHART_CID",
    "SALES_CHART_CID",
    "render_acquisition_chart",
    "render_charts",
    "render_countries_stock_chart",
    "render_sales_chart",
    "render_sales_trend_chart",
    "render_weekly_charts",
]
