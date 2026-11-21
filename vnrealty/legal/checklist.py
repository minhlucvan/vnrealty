"""Due-diligence checklist for a Vietnamese property purchase, status tracking, and itemised transaction costs.

**Not legal advice.** Each item says what to verify, why it matters and where to verify it; the answer comes from
the land registration office, the ward, the notary or a lawyer — never from a listing or a seller's word.

Status is tracked per subject ('listing:<id>', 'lot:<name>', 'unit:<id>') as rows in the ``journal`` table with
``kind='legal'`` and a JSON body ``{"item", "status", "note"}``; the latest row per item wins, so the history of a
check is kept. Statuses: ``todo``, ``ok``, ``issue``, ``na`` (not applicable).

:func:`transaction_costs` itemises taxes and fees from ``reference/vn_tax_fees.json`` (every rate cited there).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from vnrealty.store.db import dumps, rows
from vnrealty.types import Insufficient

__all__ = ["ITEMS", "STATUSES", "checklist", "set_status", "status", "transaction_costs", "notary_fee", "tax_reference"]

_REF = Path(__file__).resolve().parents[2] / "reference" / "vn_tax_fees.json"
STATUSES = {"todo", "ok", "issue", "na"}
_ALL = ("land", "house", "apartment", "shophouse", "villa", "chdv", "room", "other")
_BUILT = ("house", "shophouse", "villa", "chdv")

ITEMS: list[dict] = [
    {"id": "title_type", "vi": "Loại giấy chứng nhận: sổ hồng / sổ đỏ (không phải giấy tay, HĐMB)",
     "en": "Title type: pink book / red book (not a handwritten paper or a sale contract only)",
     "why": "Only a certificate of land use rights (and house ownership) can be transferred and mortgaged; a giấy tay or HĐMB carries the seller's risk to you.",
     "where": "Original certificate; confirm at the Land Registration Office (Văn phòng đăng ký đất đai) of the city", "applies": _ALL},
    {"id": "owners_match", "vi": "Chủ sở hữu trên sổ khớp với người bán; đủ chữ ký đồng sở hữu và vợ/chồng",
     "en": "Owners on the certificate match the seller(s); all co-owners and the spouse consent and sign",
     "why": "Property acquired during marriage is joint property; a sale without the spouse or a co-owner can be voided.",
     "where": "Certificate page 1–2, ID cards, marriage certificate or single-status confirmation; the notary checks at signing", "applies": _ALL},
    {"id": "encumbrance", "vi": "Kiểm tra thế chấp, kê biên, ngăn chặn giao dịch",
     "en": "Mortgage / seizure / transaction-block check",
     "why": "A certificate held by a bank or under a court or enforcement block cannot be transferred until released.",
     "where": "Written request to the Land Registration Office; the notary's 'ngăn chặn' database", "applies": _ALL},
    {"id": "zoning", "vi": "Thông tin quy hoạch thửa đất (quy hoạch 1/500, 1/2000), có nằm trong diện giải tỏa không",
     "en": "Planning information sheet for the plot (1/500, 1/2000 plans); any clearance or road widening",
     "why": "A plot inside a planned road, park or public works can be acquired at compensation prices and may not get a building permit.",
     "where": "Ward People's Committee (UBND phường) / Department of Construction planning portal; record findings as 'zoning:<code>' in unit notes", "applies": _ALL},
    {"id": "road_boundary", "vi": "Lộ giới, chỉ giới xây dựng, khoảng lùi",
     "en": "Road boundary (lộ giới), building line and setbacks",
     "why": "Setbacks cut the buildable area and the land inside the road boundary is not compensated as residential land.",
     "where": "Planning sheet; certificate's diagram; ward construction officer", "applies": _ALL},
    {"id": "area_match", "vi": "Diện tích, kích thước thực tế khớp với sổ",
     "en": "Actual area and dimensions match the certificate",
     "why": "A shortfall is paid for and never received; an excess outside the certificate cannot be sold or mortgaged.",
     "where": "Licensed surveyor's measurement against the certificate diagram (trích đo địa chính)", "applies": _ALL},
    {"id": "disputes", "vi": "Tranh chấp, lấn chiếm, ranh giới với hàng xóm",
     "en": "Disputes, encroachment, boundary with neighbours",
     "why": "A plot under dispute cannot be transferred; encroachment surfaces at the survey or the building permit.",
     "where": "Ward People's Committee and neighbours; ask the ward land officer (cán bộ địa chính)", "applies": _ALL},
    {"id": "permit_as_built", "vi": "Giấy phép xây dựng và hoàn công; nhà đã được ghi vào sổ",
     "en": "Construction permit and as-built completion; the house is recorded on the certificate",
     "why": "An unrecorded or over-height building is not part of the legal asset: it can be fined, not mortgaged, or ordered demolished.",
     "where": "Permit and completion papers from the seller; Department of Construction / ward", "applies": _BUILT},
    {"id": "land_use_purpose", "vi": "Mục đích sử dụng đất (đất ở ODT/ONT, thời hạn lâu dài)",
     "en": "Land use purpose (residential ODT/ONT, long-term) and term",
     "why": "Agricultural or limited-term land cannot be built on as a home without conversion fees; conversion is not guaranteed.",
     "where": "Certificate, section on land use purpose and term", "applies": ("land", "house", "shophouse", "villa", "chdv", "other")},
    {"id": "tax_debts", "vi": "Nghĩa vụ tài chính còn nợ (tiền sử dụng đất, thuế đất)",
     "en": "Outstanding land-use fees or land taxes",
     "why": "Unpaid 'ghi nợ' land-use fees must be settled before transfer and are often noted on the certificate.",
     "where": "Certificate notes; local tax office (Thuế cơ sở)", "applies": _ALL},
    {"id": "condo_pink_book", "vi": "Căn hộ: tình trạng cấp sổ hồng của dự án; dự án đã nghiệm thu, đủ điều kiện",
     "en": "Apartment: the project's pink-book status; project completed and accepted",
     "why": "Many projects have units without certificates years after handover; resale is then a contract assignment with the developer's risk.",
     "where": "Developer, Department of Construction list of projects eligible for certificates; the building's management board", "applies": ("apartment",)},
    {"id": "foreign_buyer", "vi": "Người nước ngoài: hạn mức sở hữu (≤30% căn hộ mỗi tòa, ≤250 nhà mỗi phường), thời hạn 50 năm, ngoài khu vực quốc phòng",
     "en": "Foreign buyer: ownership limits (≤30% of units per condo building, ≤250 houses per ward-level area), 50-year term, outside defence areas",
     "why": "A foreigner cannot hold land use rights; ownership of a home is capped and term-limited under the Housing Law.",
     "where": "Luật Nhà ở 2023 (27/2023/QH15), Articles 17–20; Department of Construction's published list of eligible projects and remaining quota", "applies": _ALL, "foreign_only": True},
]


def checklist(ptype: str, foreign: bool = False) -> list[dict]:
    """The items that apply to a property type (``ptype`` as in the listing table), foreign-buyer item included only
    when ``foreign``."""
    return [i for i in ITEMS if ptype in i["applies"] and (foreign or not i.get("foreign_only"))]


def set_status(con, subject: str, item: str, status: str, note: str | None = None, at: str | None = None) -> int:
    """Record the status of checklist ``item`` for ``subject`` (journal kind 'legal'). Returns the journal id."""
    if item not in {i["id"] for i in ITEMS}:
        raise ValueError(f"unknown checklist item {item!r}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; known: {sorted(STATUSES)}")
    at = at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = con.execute("INSERT INTO journal(at, kind, subject, body) VALUES (?, 'legal', ?, ?)",
                      (at, subject, dumps({"item": item, "status": status, "note": note})))
    con.commit()
    return cur.lastrowid


def status(con, subject: str, ptype: str, foreign: bool = False) -> dict:
    """Latest status per applicable item for ``subject``, and an overall: ``issue`` if any item is an issue,
    ``clear`` if every item is ok or na, else ``open``."""
    latest: dict[str, dict] = {}
    for r in rows(con, "SELECT at, body FROM journal WHERE kind='legal' AND subject=? ORDER BY at, id", (subject,)):
        b = json.loads(r["body"])
        latest[b["item"]] = {"status": b["status"], "note": b.get("note"), "at": r["at"]}
    items = []
    for i in checklist(ptype, foreign):
        s = latest.get(i["id"], {"status": "todo", "note": None, "at": None})
        items.append({"id": i["id"], "vi": i["vi"], "en": i["en"], **s})
    issues = [i["id"] for i in items if i["status"] == "issue"]
    open_ = [i["id"] for i in items if i["status"] == "todo"]
    overall = "issue" if issues else ("open" if open_ else "clear")
    return {"subject": subject, "items": items, "issues": issues, "open": open_, "overall": overall}


def tax_reference() -> dict:
    """The cited tax and fee table, ``reference/vn_tax_fees.json``."""
    return json.loads(_REF.read_text(encoding="utf-8"))


def notary_fee(value: float, ref: dict | None = None) -> float:
    """Notary fee (VND) for a transfer contract of ``value`` VND, from the tier table (Thông tư 257/2016/TT-BTC)."""
    nf = (ref or tax_reference())["notary_fee"]
    for t in nf["tiers"]:
        if t["upto"] is None or value <= t["upto"]:
            fee = t["fixed"] + t["rate"] * (value - t["over"])
            return min(fee, nf["cap"])
    raise AssertionError("tier table has no open top tier")


def transaction_costs(price: float, official_value: float | None = None, role: str = "buyer", new_build: bool = False,
                      broker_rate: float | None = None, land_use_fee: float | None = None) -> dict:
    """Itemised taxes and fees (VND) on a transfer at ``price`` for the ``role`` ('buyer' | 'seller').

    The registration fee and seller PIT use max(price, ``official_value``) when the provincial table value is known.
    ``new_build`` adds the developer VAT line (informational: normally inside the quoted price; needs
    ``land_use_fee`` to compute, else the line is Insufficient). ``broker_rate`` (a fraction of price) is added for
    the seller when given — there is no legal default. Each item carries its rate, base and legal basis; ``total``
    sums the computed items payable by ``role`` (VAT excluded as already in the price).
    """
    if role not in ("buyer", "seller"):
        raise ValueError("role must be 'buyer' or 'seller'")
    ref = tax_reference()
    base = max(price, official_value) if official_value is not None else price
    items: list[dict] = []
    if role == "buyer":
        rf = ref["registration_fee"]
        items.append({"item": "registration_fee", "vi": rf["vi"], "rate": rf["rate"], "base": base,
                      "amount": rf["rate"] * base, "legal_basis": rf["legal_basis"]})
        nf = ref["notary_fee"]
        items.append({"item": "notary_fee", "vi": nf["vi"], "rate": None, "base": price, "amount": notary_fee(price, ref),
                      "legal_basis": nf["legal_basis"], "note": nf["payer_note"]})
        if new_build:
            v = ref["developer_vat"]
            if land_use_fee is None:
                items.append({"item": "developer_vat", "vi": v["vi"], "rate": v["rate"], "base": None,
                              "amount": Insufficient("developer_vat", "land_use_fee not given: VAT base is price before VAT minus land use fee"),
                              "legal_basis": v["legal_basis"], "included_in_price": True})
            else:
                ex_vat = (price - land_use_fee) / (1 + v["rate"]) + land_use_fee   # price assumed VAT-inclusive
                vat = v["rate"] * (ex_vat - land_use_fee)
                items.append({"item": "developer_vat", "vi": v["vi"], "rate": v["rate"], "base": ex_vat - land_use_fee,
                              "amount": vat, "legal_basis": v["legal_basis"], "included_in_price": True})
    else:
        pit = ref["seller_pit"]
        items.append({"item": "seller_pit", "vi": pit["vi"], "rate": pit["rate"], "base": base,
                      "amount": pit["rate"] * base, "legal_basis": pit["legal_basis"]})
        if broker_rate is not None:
            items.append({"item": "broker_fee", "vi": ref["broker_fee"]["vi"], "rate": broker_rate, "base": price,
                          "amount": broker_rate * price, "legal_basis": "negotiated (no legal rate)"})
    total = sum(i["amount"] for i in items if isinstance(i["amount"], float | int) and not i.get("included_in_price"))
    return {"role": role, "price": price, "official_value": official_value, "items": items, "total": total,
            "share_of_price": total / price if price else None, "not_included": ref["not_included"],
            "verified_at": ref["verified_at"]}
