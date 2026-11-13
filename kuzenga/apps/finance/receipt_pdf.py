"""Branded printable receipts using the project's existing Pillow dependency."""

from io import BytesIO
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


def generate_receipt(tenant, receipt, void=False):
    s = receipt.snapshot
    lines = [
        tenant.name,
        "PAYMENT RECEIPT — DUPLICATE COPY",
        receipt.number,
        "VOID — PAYMENT REVERSED" if void else "CONFIRMED PAYMENT",
        "",
        f"Student: {s['student']}",
        f"Admission number: {s['admission']}",
        f"Account: {s['account']}",
        f"Payment date: {s['date']}",
        f"Issued: {receipt.created_at.isoformat()}",
        f"Amount: {s['currency']} {s['amount']}",
        f"Method: {s['method']}",
        f"Payment reference: {s['payment']}",
        f"External reference: {s['external'] or 'Not applicable'}",
        f"Cashier: {s['cashier']}",
        f"Confirmed by: {s['confirmed_by']}",
        "",
        "Allocations at issue:",
    ]
    lines.extend(f"{item['invoice']}: {s['currency']} {item['amount']}" for item in s["allocations"])
    if not s["allocations"]:
        lines.append("Unallocated student credit")
    lines += [
        "",
        f"Net student balance at issue: {s['currency']} {s['balance']}",
        "Negative balances indicate available student credit.",
        "This copy retains the original receipt number. No money is moved by printing.",
    ]
    return generate_document(tenant, receipt.number, lines)


def document_chunks(lines):
    """Keep a labelled financial record together when it fits on a printed page."""
    groups, group = [], []
    for line in map(str, lines):
        if line.startswith("Record ") and line[7:].isdigit() and group:
            groups.append(group)
            group = []
        group.extend(wrap(line, width=82) or [""])
    if group:
        groups.append(group)
    chunks, chunk = [], []
    for group in groups:
        if chunk and len(chunk) + len(group) > 35:
            chunks.append(chunk)
            chunk = []
        while len(group) > 35:
            chunks.append(group[:35])
            group = group[35:]
        chunk.extend(group)
    if chunk:
        chunks.append(chunk)
    return chunks or [[""]]


def document_pages(tenant, reference, lines):
    """Shared branded page renderer for receipts, statements and finance reports."""
    chunks = document_chunks(lines)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 23)
    except OSError:
        try:
            font = ImageFont.truetype("arial.ttf", 23)
        except OSError:
            font = ImageFont.load_default(size=23)
    pages = []
    for chunk in chunks:
        page = Image.new("RGB", (1400, 1900), "white")
        draw = ImageDraw.Draw(page)
        draw.rectangle((0, 0, 1400, 170), fill="#14224a")
        draw.rectangle((0, 170, 1400, 185), fill="#bf9c45")
        draw.text((70, 55), "KUZENGA | SCHOOL FINANCE", font=font, fill="white")
        if tenant.logo:
            try:
                with tenant.logo.open("rb") as source:
                    logo = Image.open(source).convert("RGBA")
                    logo.thumbnail((120, 120))
                    page.paste(logo, (1200, 25), logo)
            except (FileNotFoundError, OSError):
                pass
        for line_number, line in enumerate(chunk):
            draw.text((70, 230 + line_number * 42), line, font=font, fill="#14224a")
        draw.text((70, 1810), f"{reference} | Page {len(pages) + 1}", font=font, fill="#526079")
        pages.append(page)
    return pages


def generate_document(tenant, reference, lines):
    pages = document_pages(tenant, reference, lines)
    result = BytesIO()
    pages[0].save(result, format="PDF", save_all=True, append_images=pages[1:], resolution=150)
    return result.getvalue()
