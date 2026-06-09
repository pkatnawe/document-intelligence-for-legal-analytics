from app.validation.reconcile import reconcile
from app.validation.schema import Invoice, LineItem


def _inv(total, items):
    return Invoice(invoice_number="X", total=total,
                   line_items=[LineItem(description=d, amount=a) for d, a in items])


def test_consistent_invoice_has_no_warnings():
    inv = _inv(64.46, [("Base Fare", 3.17), ("Distance", 19.12), ("Time", 11.79),
                       ("Reservation", 1.00), ("Booking", 6.00), ("Surcharge", 4.49),
                       ("MTQ", 0.90), ("Tip", 11.03), ("TVQ", 4.64), ("TPS", 2.32)])
    assert reconcile(inv) == []


def test_inconsistent_invoice_is_flagged():
    # the real gemma misread: line items sum ~130 but total 53.43
    inv = _inv(53.43, [("a", 64.46), ("b", 19.12), ("c", 47.06)])
    warnings = reconcile(inv)
    assert warnings and "total" in warnings[0]


def test_no_line_items_means_nothing_to_reconcile():
    assert reconcile(Invoice(invoice_number="X", total=99.0)) == []


def test_small_rounding_is_tolerated():
    assert reconcile(_inv(100.00, [("a", 50.00), ("b", 49.99)])) == []  # 0.01 off, within tol
