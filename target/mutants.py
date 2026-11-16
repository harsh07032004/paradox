"""Catalogue of injectable business-logic defects ("mutants") for the Waypoint B2B sandbox.

The Paradox agent never imports this module. Only the target app and the benchmark
(which needs ground truth to score recall) read it.
"""

# id -> (description, class, endpoint template the defect lives on)
CATALOG = {
    "M01": ("Booking read skips agency ownership check", "access_control", "GET /api/v3/bookings/{id}"),
    "M02": ("Cancel skips agency ownership check", "access_control", "POST /api/v3/bookings/{id}/cancel"),
    "M03": ("Booking create trusts client-supplied amount", "business_logic", "POST /api/v3/bookings"),
    "M04": ("Cancelled booking can be cancelled again (double refund)", "business_logic", "POST /api/v3/bookings/{id}/cancel"),
    "M05": ("Unpaid (HELD) booking refunds full amount on cancel", "business_logic", "POST /api/v3/bookings/{id}/cancel"),
    "M06": ("Single-use coupon can be redeemed repeatedly", "business_logic", "POST /api/v3/quotes"),
    "M07": ("Negative room count accepted (negative price)", "business_logic", "POST /api/v3/quotes"),
    "M08": ("Booking status mass-assignable (confirmed without payment)", "business_logic", "POST /api/v3/bookings"),
    "M09": ("Profile update mass-assigns role (sub-agent -> admin)", "access_control", "PATCH /api/v3/me"),
    "M10": ("Sub-agent can change agency markup (missing role check)", "access_control", "PUT /api/v3/agency/markup"),
    "M11": ("Booking list returns full passport numbers", "data_exposure", "GET /api/v3/bookings"),
    "M12": ("Invoice read skips agency ownership check", "access_control", "GET /api/v3/invoices/{id}"),
    "M13": ("Refund computed on pre-discount gross (refund > paid)", "business_logic", "POST /api/v3/bookings/{id}/cancel"),
    "M14": ("Voucher endpoint served without authentication", "api_hygiene", "GET /api/v3/bookings/{id}/voucher"),
    "M15": ("Hotel search city filter concatenated into SQL", "injection", "GET /api/v3/hotels/search"),
    "M16": ("Unhandled errors return stack trace with secrets", "data_exposure", "POST /api/v3/quotes"),
}

# Releases model what a CI/CD deploy ships.
RELEASES = {
    # Production baseline: a few live defects plus legacy/debug routes that always exist.
    "v3.0": {"mutants": {"M04", "M11", "M14"}, "amend": False, "amend_bug": False},
    # New feature: booking amendment. Ships with a price-trust bug.
    "v3.1": {"mutants": {"M04", "M11", "M14"}, "amend": True, "amend_bug": True},
    # Hotfix: amendment repriced server-side, double refund fixed.
    "v3.1.1": {"mutants": {"M11", "M14"}, "amend": True, "amend_bug": False},
}

# Defects that exist in every release (legacy surface), used as ground truth too.
STATIC_DEFECTS = {
    "Z01": ("Legacy v1 booking read: no ownership check, full PII", "zombie_api", "GET /api/v1/bookings/{id}"),
    "Z02": ("Debug vars route left in production, unauthenticated, leaks secrets", "zombie_api", "GET /internal/debug/vars"),
}
AMEND_DEFECT = ("Amendment trusts client-supplied new_total", "business_logic", "POST /api/v3/bookings/{id}/amend")

# Ground truth for scoring (benchmark only). A finding matches a defect when its endpoint and kind
# match and, where given, its object pre-state / field match.
GROUND_TRUTH = {
    "M01": {"endpoint": "GET /api/v3/bookings/{id}", "kinds": {"cross_tenant_read"}},
    "M02": {"endpoint": "POST /api/v3/bookings/{id}/cancel", "kinds": {"cross_tenant_write"}},
    "M03": {"endpoint": "POST /api/v3/bookings", "kinds": {"underpayment", "money_created"}, "field": "amount"},
    "M04": {"endpoint": "POST /api/v3/bookings/{id}/cancel", "kinds": {"money_created"}, "pre_state": "CANCELLED"},
    "M05": {"endpoint": "POST /api/v3/bookings/{id}/cancel", "kinds": {"money_created"}, "pre_state": "HELD"},
    "M06": {"endpoint": "POST /api/v3/quotes", "kinds": {"one_time_reuse"}},
    "M07": {"endpoint": "POST /api/v3/quotes", "kinds": {"money_created", "invalid_quantity", "underpayment"}, "field": "rooms"},
    "M08": {"endpoint": "POST /api/v3/bookings", "kinds": {"underpayment", "money_created", "mass_assignment"}, "field": "status"},
    "M09": {"endpoint": "PATCH /api/v3/me", "kinds": {"mass_assignment", "privilege_escalation"}},
    "M10": {"endpoint": "PUT /api/v3/agency/markup", "kinds": {"privilege_escalation"}},
    "M11": {"endpoint": "GET /api/v3/bookings", "kinds": {"pii_exposure"}},
    "M12": {"endpoint": "GET /api/v3/invoices/{id}", "kinds": {"cross_tenant_read"}},
    "M13": {"endpoint": "POST /api/v3/bookings/{id}/cancel", "kinds": {"money_created"}, "pre_state": "CONFIRMED"},
    "M14": {"endpoint": "GET /api/v3/bookings/{id}/voucher", "kinds": {"unauthenticated_access", "cross_tenant_read"}},
    "M15": {"endpoint": "GET /api/v3/hotels/search", "kinds": {"sql_injection"}},
    "M16": {"endpoint": "*", "kinds": {"secret_exposure"}, "group": "error-handler"},
    "Z01": {"endpoint": "GET /api/v1/bookings/{id}", "kinds": {"cross_tenant_read", "pii_exposure"}},
    "Z02": {"endpoint": "GET /internal/debug/vars", "kinds": {"secret_exposure"}},
    "AMEND": {"endpoint": "POST /api/v3/bookings/{id}/amend", "kinds": {"underpayment", "money_created"}},
}


def matches(defect: str, finding: dict) -> bool:
    gt = GROUND_TRUTH[defect]
    if finding["kind"] not in gt["kinds"]:
        return False
    if gt["endpoint"] != "*" and finding["endpoint"] != gt["endpoint"]:
        return False
    for k in ("pre_state", "field", "group"):
        if k in gt and finding.get(k) != gt[k]:
            return False
    return True
