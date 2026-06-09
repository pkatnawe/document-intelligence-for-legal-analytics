from app.documents.loader import load_pdf, png_to_data_uri


def test_digital_pdf_uses_text_layer(text_pdf):
    doc = load_pdf(text_pdf)
    assert doc.has_text is True
    assert "INV-1" in doc.text
    assert doc.page_images_png == []      # no rendering needed


def test_scan_without_text_routes_to_images(scan_like_pdf):
    doc = load_pdf(scan_like_pdf)
    assert doc.has_text is False          # no usable text layer (case b)
    assert len(doc.page_images_png) >= 1  # rendered for the vision model


def test_png_to_data_uri_roundtrip(scan_like_pdf):
    doc = load_pdf(scan_like_pdf)
    uri = png_to_data_uri(doc.page_images_png[0])
    assert uri.startswith("data:image/png;base64,")
