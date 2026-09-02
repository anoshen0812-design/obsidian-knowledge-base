"""Resolve annual Journal Impact Factor metadata without estimating it."""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple


IMPACT_FACTOR_KEYS = {
    "if",
    "jif",
    "jcr if",
    "jcrif",
    "impact factor",
    "impactfactor",
    "journal impact factor",
    "影响因子",
}
IMPACT_FACTOR_YEAR_KEYS = {
    "if year",
    "jif year",
    "impact factor year",
    "impactfactor year",
    "影响因子年份",
    "影响因子年度",
}
IMPACT_FACTOR_SOURCE_KEYS = {
    "if source",
    "jif source",
    "impact factor source",
    "impactfactor source",
    "影响因子来源",
}
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
NUMBER_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])")


def normalize_label(value: Any) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"[_\-–—]+", " ", text)
    return re.sub(r"\s+", " ", text)


def normalize_issn(value: Any) -> str:
    normalized = re.sub(r"[^0-9xX]", "", str(value or "")).casefold()
    return normalized if len(normalized) == 8 else ""


def parse_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = NUMBER_RE.search(str(value or ""))
        if not match:
            return None
        number = float(match.group(1))
    if number < 0 or number > 1000:
        return None
    return number


def parse_year(value: Any) -> str:
    match = YEAR_RE.search(str(value or ""))
    return match.group(0) if match else ""


def split_extra(extra: Any) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for line in str(extra or "").splitlines():
        match = re.match(r"^\s*([^:=]+?)\s*[:=]\s*(.*?)\s*$", line)
        if match:
            fields[normalize_label(match.group(1))] = match.group(2).strip()
    return fields


def impact_factor_from_extra(extra: Any) -> Optional[Dict[str, Any]]:
    fields = split_extra(extra)
    factor: Optional[float] = None
    year = ""
    source = ""

    for raw_key, raw_value in fields.items():
        # A five-year IF is a distinct metric, not the standard two-year JIF.
        if "5 year" in raw_key or "five year" in raw_key or "五年" in raw_key:
            continue
        key_year = parse_year(raw_key)
        key = normalize_label(YEAR_RE.sub("", raw_key))
        if key in IMPACT_FACTOR_KEYS:
            candidate = parse_number(raw_value)
            if candidate is not None:
                factor = candidate
                year = year or key_year or parse_year(raw_value)
        elif key in IMPACT_FACTOR_YEAR_KEYS:
            year = parse_year(raw_value) or year
        elif key in IMPACT_FACTOR_SOURCE_KEYS:
            source = raw_value.strip()

    if factor is None:
        return None
    return {
        "impact_factor": factor,
        "impact_factor_year": year,
        "impact_factor_source": source or "Zotero Extra",
        "impact_factor_retrieved_at": "",
    }


def catalog_record(
    parent_data: Mapping[str, Any], catalog: Any
) -> Optional[Tuple[str, Any]]:
    if not isinstance(catalog, Mapping):
        return None
    candidates = [
        str(parent_data.get("publicationTitle") or ""),
        str(parent_data.get("journalAbbreviation") or ""),
        str(parent_data.get("ISSN") or ""),
    ]
    normalized = {normalize_label(value) for value in candidates if value.strip()}
    normalized_issns = {
        normalize_issn(match)
        for match in re.findall(r"\b\d{4}-?\d{3}[\dXx]\b", str(parent_data.get("ISSN") or ""))
        if normalize_issn(match)
    }
    for key, value in catalog.items():
        if normalize_label(key) in normalized or normalize_issn(key) in normalized_issns:
            return str(key), value
    return None


def impact_factor_from_catalog(
    parent_data: Mapping[str, Any], catalog: Any
) -> Optional[Dict[str, Any]]:
    match = catalog_record(parent_data, catalog)
    if not match:
        return None
    _, raw_record = match
    record = raw_record if isinstance(raw_record, Mapping) else {"impact_factor": raw_record}
    factor = parse_number(record.get("impact_factor", record.get("value")))
    if factor is None:
        return None
    return {
        "impact_factor": factor,
        "impact_factor_year": parse_year(record.get("impact_factor_year", record.get("year"))),
        "impact_factor_source": str(record.get("impact_factor_source", record.get("source", ""))).strip()
        or "Local impact-factor catalog",
        "impact_factor_retrieved_at": str(
            record.get("impact_factor_retrieved_at", record.get("retrieved_at", ""))
        ).strip(),
    }


def resolve_journal_metrics(parent_data: Mapping[str, Any], catalog: Any = None) -> Dict[str, Any]:
    metric = impact_factor_from_extra(parent_data.get("extra"))
    if metric is None:
        metric = impact_factor_from_catalog(parent_data, catalog)
    metric = metric or {
        "impact_factor": None,
        "impact_factor_year": "",
        "impact_factor_source": "",
        "impact_factor_retrieved_at": "",
    }
    return {
        "journal": str(parent_data.get("publicationTitle") or "").strip(),
        "issn": str(parent_data.get("ISSN") or "").strip(),
        **metric,
    }
