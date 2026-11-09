#!/usr/bin/env python3
"""
Mini Mergado: Google Shopping XML feed -> OpenAI (ChatGPT Ads) product feed CSV.

Uses only the Python standard library.
Settings live in config.json (next to this script).

Usage:
    python convert.py                  # downloads feed_url from config.json
    python convert.py --input feed.xml # converts a local file (for testing)
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# Column order of the output CSV.
COLUMNS = [
    "item_id", "title", "description", "url", "brand", "seller_name",
    "image_url", "availability", "price",
    "sale_price", "additional_image_urls",
    "group_id", "listing_has_variations", "variant_dict",
    "gtin", "mpn", "condition", "product_category",
    "color", "size", "material", "gender", "age_group",
    "shipping_price", "seller_url", "return_policy",
    "is_eligible_search", "is_ads_eligible", "ads_metadata",
    "target_countries", "store_country",
]

AVAILABILITY_MAP = {
    "in stock": "in_stock", "in_stock": "in_stock", "instock": "in_stock",
    "available": "in_stock", "skladom": "in_stock", "na sklade": "in_stock",
    "out of stock": "out_of_stock", "out_of_stock": "out_of_stock",
    "outofstock": "out_of_stock", "sold out": "out_of_stock",
    "preorder": "pre_order", "pre order": "pre_order", "pre_order": "pre_order",
    "backorder": "backorder", "back order": "backorder",
}
CONDITIONS = {"new", "refurbished", "used"}
GENDER_MAP = {"male": "male", "female": "female", "unisex": "unisex",
              "men": "male", "women": "female", "muž": "male", "žena": "female"}
AGE_GROUPS = {"newborn", "infant", "toddler", "kids", "adult"}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


# ---------- helpers ----------

def local(tag):
    """'{namespace}price' -> 'price'"""
    return tag.rsplit("}", 1)[-1].lower()


def clean_text(value):
    if not value:
        return ""
    value = html.unescape(value)
    value = TAG_RE.sub(" ", value)
    value = html.unescape(value)  # double-escaped feeds
    return WS_RE.sub(" ", value).strip()


def truncate(value, limit):
    if len(value) <= limit:
        return value
    cut = value[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;-")
    return cut + "…"


PRICE_RE = re.compile(r"([A-Za-z]{3})?\s*([\d\s.,]+)\s*([A-Za-z]{3}|€)?")


def parse_money(raw, default_currency):
    """'12,90 EUR' / 'EUR 12.90' / '1 299,00 €' -> (12.9, 'EUR') or None."""
    if not raw:
        return None
    raw = raw.strip()
    m = PRICE_RE.search(raw)
    if not m:
        return None
    cur = (m.group(1) or m.group(3) or default_currency or "").upper()
    if cur == "€":
        cur = "EUR"
    num = m.group(2).replace(" ", "").replace(" ", "")
    if "," in num and "." in num:
        # the later separator is the decimal one
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    try:
        amount = float(num)
    except ValueError:
        return None
    if not re.fullmatch(r"[A-Z]{3}", cur):
        return None
    return amount, cur


def fmt_money(amount, cur):
    return f"{amount:.2f} {cur}"


def valid_gtin(code):
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(d) for d in code]
    check = digits.pop()
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10 == check


def https_url(u):
    u = (u or "").strip()
    return u if u.startswith(("http://", "https://")) else ""


# ---------- parsing ----------

STATS = {"root": None, "tags": Counter()}


def iter_items(source):
    """Yields dict(tag -> list of values) for every <item> / <entry>."""
    for event, elem in ET.iterparse(source, events=("start", "end")):
        name = local(elem.tag)
        if event == "start":
            STATS["tags"][name] += 1
            if STATS["root"] is None:
                STATS["root"] = name
            continue
        if name not in ("item", "entry"):
            continue
        data = {}
        for child in elem:
            cname = local(child.tag)
            if cname == "shipping":
                sub = {local(c.tag): (c.text or "").strip() for c in child}
                data.setdefault("shipping", []).append(sub)
                continue
            if cname == "link" and child.get("href"):  # Atom
                data.setdefault("link", []).append(child.get("href"))
                continue
            data.setdefault(cname, []).append((child.text or "").strip())
        yield data
        elem.clear()


def first(d, *keys):
    for k in keys:
        for v in d.get(k, []):
            if v:
                return v
    return ""


# ---------- conversion ----------

def apply_rules(row, raw, cfg):
    """Simple Mergado-like rules from config: exclude + title prefix/suffix."""
    for rule in cfg.get("exclude", []):
        field, contains = rule.get("field"), str(rule.get("contains", "")).lower()
        value = row.get(field) or first(raw, field)
        if contains and contains in str(value).lower():
            return False
    if cfg.get("exclude_out_of_stock") and row["availability"] == "out_of_stock":
        return False
    return True


def convert_item(raw, cfg, problems):
    default_cur = cfg.get("default_currency", "EUR")
    item_id = first(raw, "id")
    pid = item_id or "(bez id)"

    def problem(level, msg):
        problems.append({"item_id": pid, "level": level, "msg": msg})

    row = {c: "" for c in COLUMNS}
    row["item_id"] = item_id
    row["title"] = truncate(clean_text(first(raw, "title")), 150)
    desc = clean_text(first(raw, "description"))
    row["description"] = truncate(desc or row["title"], 5000)
    if not desc and row["title"]:
        problem("warning", "chýba popis, použitý titulok")
    row["url"] = https_url(first(raw, "link", "url"))
    row["brand"] = clean_text(first(raw, "brand")) or cfg.get("default_brand", "")
    if not first(raw, "brand") and row["brand"]:
        problem("warning", "chýba značka, použitá predvolená")
    row["seller_name"] = cfg["seller_name"]
    row["image_url"] = https_url(first(raw, "image_link", "image_url"))

    av_raw = first(raw, "availability").lower().strip()
    av = AVAILABILITY_MAP.get(av_raw)
    if not av:
        av = "unknown"
        problem("warning", f"neznáma dostupnosť '{av_raw}', nastavené 'unknown'")
    row["availability"] = av

    price = parse_money(first(raw, "price"), default_cur)
    if price and price[0] > 0:
        row["price"] = fmt_money(*price)
        sale = parse_money(first(raw, "sale_price"), default_cur)
        if sale and 0 < sale[0] < price[0] and sale[1] == price[1]:
            row["sale_price"] = fmt_money(*sale)
        ship = None
        for s in raw.get("shipping", []):
            ship = parse_money(s.get("price", ""), price[1])
            if ship:
                break
        if ship and ship[0] >= 0 and ship[1] == price[1]:
            row["shipping_price"] = fmt_money(*ship)

    extra = [https_url(u) for u in raw.get("additional_image_link", [])]
    extra = [u.replace(",", "%2C") for u in extra if u][:10]
    row["additional_image_urls"] = ",".join(extra)

    color = clean_text(first(raw, "color"))
    size = clean_text(first(raw, "size"))
    row["color"], row["size"] = color, size
    row["material"] = clean_text(first(raw, "material"))

    group = first(raw, "item_group_id")
    if group and group != item_id:
        row["group_id"] = group
        variants = {}
        if color:
            variants["color"] = color
        if size:
            variants["size"] = size
        if variants:
            row["listing_has_variations"] = "true"
            row["variant_dict"] = json.dumps(variants, ensure_ascii=False)

    gtin = re.sub(r"[\s-]", "", first(raw, "gtin", "ean"))
    if gtin:
        if valid_gtin(gtin):
            row["gtin"] = gtin
        else:
            problem("warning", f"neplatný GTIN '{gtin}', vynechaný")
    row["mpn"] = first(raw, "mpn")

    cond = first(raw, "condition").lower()
    row["condition"] = cond if cond in CONDITIONS else ""

    cat = first(raw, "product_type") or first(raw, "google_product_category")
    if cat and not cat.isdigit():
        row["product_category"] = re.sub(r"\s*[>|/]\s*", " > ", clean_text(cat))

    row["gender"] = GENDER_MAP.get(first(raw, "gender").lower(), "")
    age = first(raw, "age_group").lower()
    row["age_group"] = age if age in AGE_GROUPS else ""

    row["seller_url"] = cfg.get("seller_url", "")
    row["return_policy"] = cfg.get("return_policy_url", "")
    row["is_eligible_search"] = "true"
    row["is_ads_eligible"] = "true" if cfg.get("ads_eligible", True) else "false"

    if cfg.get("custom_labels_to_ads_metadata"):
        meta = {}
        for i in range(5):
            v = first(raw, f"custom_label_{i}")
            if v:
                meta[f"custom_label_{i}"] = v
        if meta:
            row["ads_metadata"] = json.dumps(meta, ensure_ascii=False)

    if cfg.get("target_countries"):
        row["target_countries"] = json.dumps(cfg["target_countries"])
    if cfg.get("store_country"):
        row["store_country"] = cfg["store_country"]

    # required-field check: a row with an error would be rejected by OpenAI
    missing = [f for f in ("item_id", "title", "description", "url", "brand",
                           "seller_name", "image_url", "availability", "price")
               if not row[f]]
    if missing:
        problem("error", "chýba povinné pole: " + ", ".join(missing) + " → produkt vynechaný")
        return None
    return row


def load_source(cfg, input_path):
    if input_path:
        return open(input_path, "rb")
    req = urllib.request.Request(cfg["feed_url"], headers={
        "User-Agent": "Mozilla/5.0 (compatible; MiniMergado/1.0)"})
    return urllib.request.urlopen(req, timeout=120)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="local XML file instead of feed_url")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "docs"))
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, cfg.get("output_file", "openai_feed.csv"))

    problems, rows, seen, total, excluded = [], [], set(), 0, 0
    try:
        src = load_source(cfg, args.input)
    except Exception as e:  # network / HTTP error
        sys.exit(f"CHYBA: feed sa nepodarilo stiahnuť ({e}). Feed sa neprepisuje.")
    try:
        with src:
            items = list(iter_items(src))
    except ET.ParseError as e:
        sys.exit(f"CHYBA: zdrojový feed nie je platné XML ({e}). Feed sa neprepisuje.")
    for raw in items:
        total += 1
        row = convert_item(raw, cfg, problems)
        if row is None:
            continue
        if row["item_id"] in seen:
            problems.append({"item_id": row["item_id"], "level": "error",
                             "msg": "duplicitné ID → druhý výskyt vynechaný"})
            continue
        if not apply_rules(row, raw, cfg):
            excluded += 1
            continue
        seen.add(row["item_id"])
        rows.append(row)

    root_tag, tag_counts = STATS["root"], STATS["tags"]
    # Diagnostics first, so the log always explains what happened.
    print(f"Zdroj: {total} produktov | platné: {len(rows)} | vylúčené pravidlami: {excluded}")
    if total == 0:
        print(f"  V XML sa nenašli žiadne <item>/<entry>. Koreňový element: <{root_tag}>, "
              f"najčastejšie elementy: {', '.join(f'{t} ({n}x)' for t, n in tag_counts.most_common(8))}")
    if items:
        print("  Polia prvého produktu: " + ", ".join(
            f"{k}={(v[0] if v and isinstance(v[0], str) else v)!s:.40}" for k, v in items[0].items()))
    reasons = Counter(re.sub(r"'.*?'", "'…'", p["msg"]) for p in problems)
    for msg, n in reasons.most_common(10):
        print(f"  {n}x {msg}")

    # Safety: never replace a good feed with an empty / broken one.
    min_items = cfg.get("min_items", 1)
    if len(rows) < min_items:
        sys.exit(f"CHYBA: iba {len(rows)} platných produktov (minimum {min_items}). "
                 "Feed sa neprepisuje.")
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as f:
            previous = max(sum(1 for _ in f) - 1, 0)
        max_drop = cfg.get("max_drop_ratio", 0.5)
        if previous and len(rows) < previous * (1 - max_drop):
            sys.exit(f"CHYBA: počet produktov klesol z {previous} na {len(rows)} "
                     f"(viac ako {int(max_drop*100)} %). Feed sa neprepisuje – skontrolujte zdroj.")

    tmp = csv_path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, csv_path)

    errors = [p for p in problems if p["level"] == "error"]
    warnings = [p for p in problems if p["level"] == "warning"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_items": total,
        "exported": len(rows),
        "excluded_by_rules": excluded,
        "rejected": len(errors),
        "warnings": len(warnings),
        "problems": problems[:2000],
    }
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Hotovo: exportované {len(rows)} | odmietnuté {len(errors)} | varovania {len(warnings)}")


if __name__ == "__main__":
    main()
