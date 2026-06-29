"""
test_data_generators.py — Generate test documents for all formats.

Every generator returns bytes (file content). Used by both unit tests
and the E2E diagnostic runner so data is identical in both contexts.
"""

import csv
import io
import json

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from PIL import Image, ImageDraw


def xlsx_bytes(headers, rows, sheet_name="Sheet1"):
    """Generate a simple .xlsx file in memory. Returns bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(headers, rows, delimiter=","):
    """Generate a CSV file in memory. Returns bytes."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def pdf_bytes(title, headers, rows):
    """Generate a text-based PDF with a table. Returns bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph(title, styles["Title"]))
    table_data = [headers] + rows
    table = Table(table_data)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ])
    table.setStyle(style)
    elements.append(table)
    doc.build(elements)
    return buf.getvalue()


def image_bytes(draw_items, fmt="PNG", width=400, height=200):
    """Generate an image with text drawn on it. Returns bytes."""
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    y = 20
    for text in draw_items:
        draw.text((20, y), text, fill="black")
        y += 30
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def json_bytes(data):
    """Generate a JSON file. Returns bytes."""
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


# ── Standard test datasets ──

STD_HEADERS = ["Nombre", "Precio", "Cantidad", "Fecha", "Activo"]
STD_ROWS = [
    ["Producto A", "15000", "10", "2026-01-15", "Si"],
    ["Producto B", "25000", "5", "2026-02-20", "No"],
    ["Producto C", "35000", "8", "2026-03-10", "Si"],
]

# Edge case datasets
EDGE_EMPTY_COL_HEADERS = ["Nombre", "", "Precio", "Cantidad"]
EDGE_EMPTY_COL_ROWS = [
    ["Prod A", "x", "10000", "5"],
]

EDGE_DUPLICATE_COL_HEADERS = ["Nombre", "Precio", "Precio", "Cantidad"]
EDGE_DUPLICATE_COL_ROWS = [
    ["Prod A", "10000", "20000", "5"],
]

EDGE_SPECIAL_CHARS_HEADERS = ["Nombre", "Descripción", "Precio (€)"]
EDGE_SPECIAL_CHARS_ROWS = [
    ["Café & té", "Café con ñoñerías 100%", "15.99"],
    ["Münchner Bier", "Weißbier mit Ümlaut", "4.50"],
    ["русский товар", "Тестовый продукт", "1200"],
    ["中文商品", "测试产品", "99"],
]

EDGE_TYPES_HEADERS = ["Entero", "Decimal", "Moneda", "Booleano", "Fecha"]
EDGE_TYPES_ROWS = [
    ["42", "3.14", "15000.50", "Si", "2026-01-15"],
    ["0", "0.99", "0", "No", "2025-12-31"],
    ["-5", "-1.5", "-500", "True", "2024-06-01"],
    ["100", "100.0", "999999.99", "false", "2023-01-01"],
]

EDGE_EMPTY_ROWS_HEADERS = ["Nombre", "Valor"]
EDGE_EMPTY_ROWS_DATA = [
    ["Fila 1", "OK"],
    ["", ""],
    ["Fila 3", "OK"],
    ["", "partial"],
    ["", ""],
]

EDGE_UTF8_HEADERS = ["Código", "Nombre", "Valor"]
EDGE_UTF8_ROWS = [
    ["EUR", "€uro sign", "1"],
    ["JPY", "¥en sign", "2"],
    ["COPY", "© Copyright", "3"],
    ["REG", "® Registered", "4"],
    ["DELTA", "∆ Delta", "5"],
]


def make_std_xlsx():
    return xlsx_bytes(STD_HEADERS, STD_ROWS)


def make_std_csv():
    return csv_bytes(STD_HEADERS, STD_ROWS)


def make_std_pdf():
    return pdf_bytes("Productos Test", STD_HEADERS, STD_ROWS)


def make_std_image():
    return image_bytes([
        "Product Name: Test Product",
        "Price: $25,000",
        "Stock: 100",
    ])


def make_std_json():
    data = [dict(zip(STD_HEADERS, row)) for row in STD_ROWS]
    return json_bytes(data)
