import fitz

from app.documents.splitter import split_pdf


def _pages(pdf: bytes) -> int:
    doc = fitz.open(stream=pdf, filetype="pdf")
    n = doc.page_count
    doc.close()
    return n


def test_splits_multi_invoice_into_single_pages(three_page_pdf):
    parts = split_pdf(three_page_pdf)
    assert len(parts) == 3
    assert [p.index for p in parts] == [0, 1, 2]
    # each part is a standalone single-page PDF
    for p in parts:
        assert _pages(p.pdf) == 1


def test_single_invoice_round_trips_to_one_doc(text_pdf):
    parts = split_pdf(text_pdf)
    assert len(parts) == 1
    assert _pages(parts[0].pdf) == 1


def test_blank_pages_are_dropped(pdf_with_blank):
    parts = split_pdf(pdf_with_blank)
    assert len(parts) == 1          # the blank page is not turned into a job
    assert parts[0].index == 0
