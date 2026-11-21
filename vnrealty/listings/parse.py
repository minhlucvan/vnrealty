"""The ONE parser for Vietnamese listing strings — prices, areas, dimensions, alley width, legal status, property type.

Every site extractor (Python text parsers and the injected browser scripts alike) hands raw strings here, so there is
exactly one place where "3 tỷ 250" becomes 3_250_000_000.0 VND. Units: money in VND (floats), lengths in metres,
areas in m². A string that cannot be read yields ``None`` — never a guessed default.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = ["fold", "parse_number", "parse_price", "parse_area", "parse_dims", "parse_alley", "parse_access",
           "detect_legal", "detect_ptype", "detect_corner", "detect_direction", "detect_deal", "phone_hash",
           "find_phone_hashes", "redact_phones", "parse_label_table", "parse_int", "parse_post", "parse_posted",
           "card_fields", "LABELS"]


def fold(s: str | None) -> str:
    """NFC-normalise, lowercase, strip diacritics (đ→d), collapse whitespace. ``None`` → ``''``."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", str(s)).lower().replace("đ", "d").replace("Đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = s.replace("²", "2").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- numbers

def parse_number(tok: str, unit: str | None = None) -> float | None:
    """Read a Vietnamese-formatted number token ("3,25", "3.25", "2.500.000.000", "1.200").

    Several identical separators are thousands groups. A single separator followed by exactly three digits is a
    thousands group for triệu/raw VND ("1.200 triệu" = 1,200 triệu) but a decimal for tỷ ("3.250 tỷ" = 3.25 tỷ).
    Otherwise a single ',' or '.' is the decimal mark.
    """
    tok = tok.strip()
    if not tok or not re.fullmatch(r"\d+(?:[.,]\d+)*", tok):
        return None
    seps = re.findall(r"[.,]", tok)
    if not seps:
        return float(tok)
    if len(seps) > 1:
        if len(set(seps)) == 1:
            return float(tok.replace(seps[0], ""))
        # mixed: last one is the decimal mark ("1.234,5")
        last = max(tok.rfind(","), tok.rfind("."))
        return float(re.sub(r"[.,]", "", tok[:last]) + "." + tok[last + 1:])
    head, tail = re.split(r"[.,]", tok)
    if len(tail) == 3 and unit != "ty":
        return float(head + tail)
    return float(head + "." + tail)


def parse_int(s: str | None) -> float | None:
    """First integer-ish number in a string ("3 tầng" → 3.0, "2 PN" → 2.0). ``None`` when absent."""
    m = re.search(r"\d+(?:[.,]\d+)?", fold(s))
    return parse_number(m.group(0)) if m else None


_NEG = re.compile(r"thoa thuan|lien he|thuong luong|\bdeal\b|\bib\b|inbox")
_UNIT = {"ty": 1e9, "trieu": 1e6, "tr": 1e6, "nghin": 1e3, "ngan": 1e3, "k": 1e3}
_NUM = r"\d+(?:[.,]\d+)*"


def _per(f: str) -> str:
    if re.search(r"/\s*m\s*2|/\s*m\b|tren\s*m2|/\s*met", f):
        return "m2"
    if re.search(r"/\s*(thang|th\b)|moi thang|1 thang", f):
        return "month"
    if re.search(r"/\s*nam\b", f):
        return "year"
    return "total"


def parse_price(s: str | None, deal: str | None = None) -> dict:
    """See ``_parse_price``; values are rounded to whole VND (``4,1 tỷ`` is 4_100_000_000.0, not 4_099_999_999.99…)."""
    out = _parse_price(s, deal)
    for k in ("value", "lo", "hi"):
        if out[k] is not None:
            out[k] = float(round(out[k]))
    return out


def _parse_price(s: str | None, deal: str | None = None) -> dict:
    """Parse a price string to ``{value, per, negotiable, lo, hi}``.

    ``value`` is VND (``None`` when not stated, negotiable or a range); ``per`` is ``total`` | ``m2`` | ``month`` |
    ``year``. With ``deal='rent'`` a bare amount is read as per month. Ranges ("3-3,5 tỷ") give ``lo``/``hi`` and
    ``value=None`` — a range is not a price.
    """
    out = {"value": None, "per": "total", "negotiable": False, "lo": None, "hi": None}
    f = fold(s)
    if not f:
        return out
    if _NEG.search(f):
        out["negotiable"] = True
    out["per"] = _per(f)
    if deal == "rent" and out["per"] == "total":
        out["per"] = "month"
    body = re.split(r"/", f, maxsplit=1)[0] if out["per"] != "total" else f
    # ranges: "3 - 3,5 ty", "3 den 3,5 ty"
    rm = re.search(rf"({_NUM})\s*(?:ty|trieu|tr)?\s*(?:-|–|den|toi)\s*({_NUM})\s*(ty|trieu|tr)\b", body)
    if rm:
        u = rm.group(3)
        a, b = parse_number(rm.group(1), "ty" if u == "ty" else None), parse_number(rm.group(2), "ty" if u == "ty" else None)
        if a is not None and b is not None:
            out["lo"], out["hi"] = a * _UNIT[u], b * _UNIT[u]
            return out
    # "3 ty 250 (trieu)" — tỷ followed by a bare or triệu amount
    m = re.search(rf"({_NUM})\s*ty\s*(?:,\s*)?(?:(\d{{1,3}})(?!\d|[.,]\d|\s*(?:m\b|m2|x|ha\b)))?\s*(trieu|tr)?\b", body)
    if m:
        v = parse_number(m.group(1), "ty")
        if v is None:
            return out
        v *= 1e9
        if m.group(2):
            if m.group(3):                       # "3 tỷ 250 triệu" / "3 tỷ 5 triệu"
                v += float(m.group(2)) * 1e6
            elif not re.search(r"[.,]", m.group(1)):  # "3 tỷ 250" / "3 tỷ 25" / "3 tỷ 2" — digits are the fraction
                v += float("0." + m.group(2)) * 1e9
        out["value"] = v
        return out
    m = re.search(rf"({_NUM})\s*(trieu|tr|nghin|ngan|k)\b", body)
    if m:
        v = parse_number(m.group(1), None)
        if v is not None:
            out["value"] = v * _UNIT[m.group(2)]
        return out
    m = re.search(rf"({_NUM})\s*(?:d|vnd|dong)?\b", body)
    if m:
        v = parse_number(m.group(1), None)
        # a bare number is only trusted when it is already in VND (≥ 100,000); "3,5" alone is ambiguous
        if v is not None and v >= 1e5:
            out["value"] = v
    return out


# ---------------------------------------------------------------- area & dimensions

_DIMS = re.compile(rf"({_NUM})\s*m?\s*[x×*]\s*({_NUM})\s*m?\b")


def parse_dims(s: str | None) -> tuple[float, float] | None:
    """Frontage × depth in metres from "5x20", "5 x 20m", "5m x 20m", "ngang 5m dài 20m". ``None`` when absent."""
    f = fold(s)
    m = _DIMS.search(f)
    if m:
        a, b = parse_number(m.group(1), "ty"), parse_number(m.group(2), "ty")
        if a and b:
            return a, b
    n = re.search(rf"(?:ngang|chieu ngang|mat tien|mt)\s*:?\s*({_NUM})\s*m", f)
    d = re.search(rf"(?:dai|chieu dai|sau)\s*:?\s*({_NUM})\s*m", f)
    if n and d:
        a, b = parse_number(n.group(1), "ty"), parse_number(d.group(1), "ty")
        if a and b:
            return a, b
    return None


def parse_area(s: str | None) -> float | None:
    """Area in m² from "103 m²", "103,5m2", "1.200 m2", "5x20" (→100). ``None`` when absent."""
    f = fold(s)
    if not f:
        return None
    m = re.search(rf"({_NUM})\s*(m2|m 2|met vuong)\b", f)
    if m:
        return parse_number(m.group(1), None)
    m = re.search(rf"({_NUM})\s*ha\b", f)
    if m:
        v = parse_number(m.group(1), "ty")
        return v * 10_000 if v is not None else None
    d = parse_dims(f)
    if d:
        return round(d[0] * d[1], 2)
    m = re.fullmatch(rf"({_NUM})\s*m?", f)
    return parse_number(m.group(1), None) if m else None


def parse_access(s: str | None) -> dict:
    """Street access read from free text: ``{alley_m, frontage_street, car_access, kind}``.

    ``alley_m`` is the width in metres of the lane in front ("kiệt 4m", "hẻm 3m", "đường vào 5m", "đường trước nhà
    6m"); 0.0 for a street-front property ("nhà mặt tiền", "mặt đường"); ``None`` when not stated. ``car_access`` is
    True for "kiệt ô tô"/"hẻm xe hơi" — that says a car fits, not how wide the lane is, so it never sets a width.
    """
    f = fold(s)
    out = {"alley_m": None, "frontage_street": False, "car_access": None, "kind": None}
    if not f:
        return out
    m = re.search(rf"(kiet|hem|ngo|duong vao|duong truoc nha|duong truoc|loi vao|duong)\s*(?:rong|:)?\s*({_NUM})\s*m\b", f)
    if m:
        w = parse_number(m.group(2), "ty")
        if w is not None and w <= 60:
            out["alley_m"], out["kind"] = w, m.group(1)
    if re.search(r"(kiet|hem|ngo)\s*(o\s*to|oto|xe hoi|xe tai)", f):
        out["car_access"], out["kind"] = True, out["kind"] or "alley"
    if out["alley_m"] is None and not re.search(r"\b(kiet|hem|ngo)\b", f):
        # "mặt tiền 5m" is a frontage WIDTH, not proof the lot faces a street
        if re.search(r"(nha|dat|lo|ban)\s+mat\s+(tien|pho|duong)|mat duong|mat tien duong|mat pho", f):
            out["alley_m"], out["frontage_street"], out["kind"] = 0.0, True, "street"
    return out


def parse_alley(s: str | None) -> float | None:
    """Width (m) of the lane in front; 0.0 for street frontage; ``None`` when unknown (incl. "kiệt ô tô")."""
    return parse_access(s)["alley_m"]


# ---------------------------------------------------------------- categorical detection

def detect_legal(s: str | None) -> str:
    """so_hong | so_do | hdmb | giay_tay | unknown. A combined "Sổ đỏ/Sổ hồng" (one certificate type since 2009)
    is so_hong. A bare "có sổ" names no type and is unknown."""
    f = fold(s)
    if not f:
        return "unknown"
    if re.search(r"giay tay|vi bang|so chung|so tay", f):
        return "giay_tay"
    if re.search(r"\bhdmb\b|hop dong mua ban", f):
        return "hdmb"
    hong = bool(re.search(r"so hong|shr\b|so rieng hong", f))
    do = bool(re.search(r"so do\b|so do\/|\bsdcc|so do chinh chu", f))
    if hong:
        return "so_hong"
    if do:
        return "so_do"
    return "unknown"


_PTYPES: list[tuple[str, str]] = [
    ("chdv", r"can ho dich vu|\bchdv\b|toa can ho|nha nghi|khach san|homestay"),
    ("room", r"phong tro|nha tro|cho thue phong|day tro|\bphong\b.*\bkhep kin"),
    ("apartment", r"can ho|chung cu|condotel|penthouse|officetel"),
    ("villa", r"biet thu|villa"),
    ("shophouse", r"shophouse|shop house|nha pho thuong mai"),
]
_HOUSE = r"\bnha\b(?! nghi| tro)|nha pho|nha rieng|nha mat tien|nha kiet|nha hem|nha cap 4|nha c4"
_LAND = r"\bdat\b|lo dat|dat nen|dat tho cu|\bdat o\b"


def detect_ptype(s: str | None) -> str:
    """land | house | apartment | shophouse | villa | chdv | room | other, from a title or category string.
    Specific categories win; between house and land the earlier mention wins ("bán đất tặng nhà cấp 4" → land)."""
    f = fold(s)
    if not f:
        return "other"
    for code, pat in _PTYPES:
        if re.search(pat, f):
            return code
    h, l = re.search(_HOUSE, f), re.search(_LAND, f)
    if h and l:
        return "house" if h.start() < l.start() else "land"
    if h:
        return "house"
    if l:
        return "land"
    return "other"


def detect_corner(s: str | None) -> bool | None:
    """True for a corner lot ("lô góc", "2 mặt tiền", "căn góc"); ``None`` otherwise — silence is not 'not a corner'."""
    f = fold(s)
    return True if re.search(r"lo goc|nha goc|can goc|\bgoc 2|\b(?:2|hai) mat (?:tien|kiet|duong|thoang)|\b2mt\b", f) else None


_DIR = {"dong bac": "NE", "dong nam": "SE", "tay bac": "NW", "tay nam": "SW",
        "dong": "E", "tay": "W", "nam": "S", "bac": "N"}


def detect_direction(s: str | None) -> str | None:
    """Facing as a compass code (N, NE, E, SE, S, SW, W, NW) from "Hướng nhà: Đông Nam" or a bare "Đông - Nam"."""
    f = re.sub(r"\s*-\s*", " ", fold(s))
    if not f:
        return None
    m = re.search(r"huong(?:\s+(?:nha|cua chinh|cua|ban cong|dat))?\s*:?\s*(dong bac|dong nam|tay bac|tay nam|dong|tay|nam|bac)\b", f)
    if m:
        return _DIR[m.group(1)]
    m = re.fullmatch(r"(dong bac|dong nam|tay bac|tay nam|dong|tay|nam|bac)", f)
    return _DIR[m.group(1)] if m else None


def detect_deal(s: str | None) -> str | None:
    """'rent' for "cho thuê", 'sale' for "bán"/"mua bán", else ``None``."""
    f = fold(s)
    if re.search(r"cho thue|cho-thue|/thue|can thue|thue nha|thue phong|thue can ho|thue mat bang", f):
        return "rent"
    if re.search(r"\bban\b|mua ban|mua-ban|nha-dat-ban|ban-", f):
        return "sale"
    return None


# ---------------------------------------------------------------- privacy

_PHONE = re.compile(r"(?:\+?84|0)(?:[\s.\-]?\d){8,10}")


def _norm_phone(raw: str) -> str | None:
    d = re.sub(r"\D", "", raw)
    if d.startswith("84") and len(d) in (11, 12):
        d = "0" + d[2:]
    return d if 9 <= len(d) <= 11 and d.startswith("0") else None


def phone_hash(raw: str | None) -> str | None:
    """sha1 hex of the normalised digits (+84 → 0). The number itself is never stored. Same as core.js phoneHash."""
    d = _norm_phone(raw or "")
    return hashlib.sha1(d.encode()).hexdigest() if d else None


def find_phone_hashes(text: str | None) -> list[str]:
    """Hashes of every phone-like number in a text, in order, de-duplicated."""
    out: list[str] = []
    for m in _PHONE.finditer(text or ""):
        h = phone_hash(m.group(0))
        if h and h not in out:
            out.append(h)
    return out


def redact_phones(text: str | None) -> str:
    """Replace phone numbers with ``[phone:<first 8 of hash>]`` so saved page text holds no numbers."""
    def rep(m: re.Match) -> str:
        h = phone_hash(m.group(0))
        return f"[phone:{h[:8]}]" if h else m.group(0)
    return _PHONE.sub(rep, text or "")


# ---------------------------------------------------------------- spec tables

# canonical field → folded label spellings seen on VN listing sites
LABELS: dict[str, list[str]] = {
    "price": ["muc gia", "gia ban", "gia", "gia thue", "gia cho thue"],
    "area": ["dien tich", "dien tich dat", "dien tich su dung", "dt"],
    "floor_area": ["dien tich san", "dien tich xay dung", "tong dien tich san"],
    "frontage": ["mat tien", "chieu ngang", "ngang"],
    "depth": ["chieu dai", "chieu sau", "dai"],
    "alley": ["duong vao", "duong truoc nha", "duong truoc", "lo gioi", "do rong duong"],
    "legal": ["phap ly", "giay to phap ly", "giay to"],
    "direction": ["huong nha", "huong cua chinh", "huong", "huong dat"],
    "floors": ["so tang", "tong so tang", "so lau", "so tang lau"],
    "bedrooms": ["so phong ngu", "phong ngu", "so phong"],
    "address": ["dia chi", "vi tri", "khu vuc"],
    "posted": ["ngay dang", "ngay cap nhat", "dang ngay"],
    "site_id": ["ma tin", "ma tin dang", "ma bds"],
    "ptype": ["loai bds", "loai hinh", "loai tin", "loai nha dat", "loai hinh nha o", "loai hinh dat"],
    "title": ["tieu de"],
}
_LABEL_INDEX = {lab: key for key, labs in LABELS.items() for lab in labs}


def parse_label_table(lines: list[str], labels: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Read a spec table out of page-text lines → ``{canonical_field: raw value}``.

    A label is a line (or the part before ':') whose folded text equals a known label; the value is the rest of the
    line after ':' or, if empty, the next non-empty line. First occurrence wins. Values stay raw text.
    """
    index = dict(_LABEL_INDEX)
    for key, labs in (labels or {}).items():
        for lab in labs:
            index[fold(lab)] = key
    out: dict[str, str] = {}
    ls = [l.strip() for l in lines]
    for i, line in enumerate(ls):
        if not line:
            continue
        head, sep, rest = line.partition(":")
        key = index.get(fold(head).rstrip(" .")) if len(head) <= 40 else None
        if key is None:
            continue
        val = rest.strip() if sep else ""
        if not val:
            for nxt in ls[i + 1:i + 3]:
                if nxt:
                    if index.get(fold(nxt.partition(":")[0])) is None:
                        val = nxt
                    break
        if val and key not in out:
            out[key] = val
    return out


# ---------------------------------------------------------------- free-text posts

def parse_post(text: str | None, deal: str | None = None) -> dict:
    """Parse a free-text social post into ListingObs-like fields plus ``confidence`` (0–1).

    Confidence counts what the text actually states: a price (0.35), an area (0.25), a property type (0.2), a place
    that maps to a ward (0.2). Below ~0.5 the post is probably not a listing. Phones become ``phone_hash`` only.
    """
    from vnrealty.geo.wards import match_ward  # local import: wards imports fold from here

    raw = text or ""
    f = fold(raw)
    deal = deal or detect_deal(raw) or "sale"
    # price: first money-looking phrase ("giá 3,2 tỷ", "chỉ 850tr", "12tr/tháng")
    price = {"value": None, "per": "total", "negotiable": False, "lo": None, "hi": None}
    pm = re.search(rf"{_NUM}\s*(?:ty|trieu|tr)\b(?:\s*\d{{1,3}}(?!\d|[.,]\d|\s*(?:m\b|m2|x|ha\b))(?:\s*(?:trieu|tr)\b)?)?(?:\s*(?:/|tren)\s*(?:m2|m|thang|nam))?", f)
    if pm:
        price = parse_price(pm.group(0), deal=deal)
    elif _NEG.search(f):
        price["negotiable"] = True
    am = re.search(rf"{_NUM}\s*(?:m2|m 2|met vuong)\b|{_NUM}\s*m?\s*[x×*]\s*{_NUM}\s*m?\b", f)
    area = parse_area(am.group(0)) if am else None
    dims = parse_dims(f)
    ptype = detect_ptype(raw)
    ward = match_ward(raw)
    acc = parse_access(raw)
    conf = 0.0
    conf += 0.35 if price["value"] is not None or price["lo"] is not None else 0.0
    conf += 0.25 if area else 0.0
    conf += 0.2 if ptype != "other" else 0.0
    conf += 0.2 if ward else 0.0
    value = price["value"]
    price_m2 = None
    if value is not None and price["per"] == "m2":
        price_m2, value = value, (value * area if area else None)
    return {
        "kind": "rent" if deal == "rent" else "asking", "deal": deal, "ptype": ptype,
        "price": value, "price_m2": price_m2, "price_per": price["per"], "negotiable": price["negotiable"],
        "price_lo": price["lo"], "price_hi": price["hi"],
        "area_m2": area, "frontage_m": dims[0] if dims else None, "depth_m": dims[1] if dims else None,
        "alley_m": acc["alley_m"], "car_access": acc["car_access"], "corner": detect_corner(raw),
        "direction": detect_direction(raw), "legal": detect_legal(raw), "ward_code": ward,
        "phone_hash": (find_phone_hashes(raw) or [None])[0], "confidence": round(conf, 2),
        "title": redact_phones(raw.strip().splitlines()[0][:160]) if raw.strip() else None,
    }


# ---------------------------------------------------------------- dates & cards

def parse_posted(s: str | None, seen_at: str | None = None) -> str | None:
    """Posting date as ISO ``YYYY-MM-DD`` from "12/11/2026", "2026-11-12…", "Hôm nay", "Hôm qua", "3 ngày trước",
    "5 giờ trước", "2 tuần trước". Relative forms need ``seen_at``. "N tháng trước" is too coarse → ``None``."""
    import datetime as _dt

    f = fold(s)
    if not f:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", f)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b", f)
    if m:
        try:
            return _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    if not seen_at:
        return None
    try:
        base = _dt.date.fromisoformat(seen_at[:10])
    except ValueError:
        return None
    if "hom nay" in f or re.search(r"\d+\s*(phut|giay)\s*truoc", f):
        return base.isoformat()
    if "hom qua" in f:
        return (base - _dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\s*(gio|ngay|tuan)\s*truoc", f)
    if m:
        n = int(m.group(1))
        days = {"gio": n / 24, "ngay": n, "tuan": 7 * n}[m.group(2)]
        return (base - _dt.timedelta(days=int(days))).isoformat()
    return None


def card_fields(text: str | None) -> dict:
    """Raw price/area/per-m²/dims/bedrooms/floors/posted tokens from one result card's text (mirrors core.js
    extractCardFields). Values stay raw strings for the other parsers."""
    s = text or ""
    out: dict[str, str] = {}
    num = r"\d+(?:[.,]\d+)*"
    m = re.search(rf"({num}[ \t]*(?:tỷ|tỉ|ty)(?:[ \t]*\d{{1,3}}(?!\d|[.,]\d|\s*m))?(?:[ \t]*(?:triệu|tr))?|{num}[ \t]*(?:triệu|tr)\b(?:[ \t]*/[ \t]*(?:m²|m2|tháng|th))?|Thỏa thuận|Thoả thuận|Liên hệ)", s, re.I)
    if m:
        out["price_text"] = m.group(1).strip()
    m = re.search(rf"({num}\s*(?:triệu|tr|tỷ)\s*/\s*m(?:²|2))", s, re.I)
    if m:
        out["ppm2_text"] = m.group(1)
    m = re.search(rf"({num}\s*(?:m²|m2))(?!\s*/)", s, re.I)
    if m:
        out["area_text"] = m.group(1)
    m = re.search(rf"({num}\s*m?\s*[x×]\s*{num}\s*m?)", s, re.I)
    if m:
        out["dims_text"] = m.group(1)
    m = re.search(r"(\d+)\s*(?:PN|phòng ngủ)", s, re.I)
    if m:
        out["bedrooms_text"] = m.group(1)
    m = re.search(r"(\d+)\s*(?:tầng|lầu)", s, re.I)
    if m:
        out["floors_text"] = m.group(1)
    m = re.search(r"(Hôm nay|Hôm qua|\d+\s*(?:phút|giờ|ngày|tuần|tháng)\s*trước|\d{1,2}/\d{1,2}/\d{4})", s, re.I)
    if m:
        out["posted_text"] = m.group(1)
    return out
