"""The e-invoice QR code on printed documents (ADR-049 item 6): the signed QR string exactly as
the portal returned it, drawn as an SVG (``segno``) for the PDF.
TODO(verify): the minimum printed size and error-correction level (PROGRESS pre-production
item 16)."""

import segno


def qr_data_uri(signed_qr: str) -> str:
    if not signed_qr:
        return ""
    return str(segno.make(signed_qr, error="m", micro=False).svg_data_uri(scale=4, border=2))
