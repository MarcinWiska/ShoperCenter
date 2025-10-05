"""CSV import helpers for SEO redirect rules."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Optional

from .shoper_redirects import _norm_path


class RedirectImportError(Exception):
    """Raised when CSV import cannot be processed."""


COLUMN_ALIASES: Dict[str, set[str]] = {
    'rule_type': {
        'rule_type', 'typ', 'type', 'redirect_type', 'rodzaj', 'kind', 'tryb',
    },
    'source_url': {
        'source_url', 'source', 'sourcepath', 'source_path', 'url_source', 'old_url',
        'from', 'from_url', 'origin', 'zrodlo', 'źródło', 'stary_url', 'path', 'stary',
    },
    'target_url': {
        'target_url', 'target', 'destination', 'to', 'to_url', 'new_url', 'cel',
        'docelowy_url', 'redirect_to', 'destination_url', 'nowy_url', 'cel_url',
    },
    'status_code': {
        'status_code', 'code', 'http_code', 'httpstatus', 'status', 'kod', 'kod_http',
    },
    'product_id': {
        'product_id', 'productid', 'prod_id', 'id_produktu', 'produkt_id', 'product',
    },
    'category_id': {
        'category_id', 'categoryid', 'cat_id', 'id_kategorii', 'kategoria_id', 'category',
    },
    'active': {
        'active', 'is_active', 'enabled', 'aktywny', 'aktywnosc', 'status', 'włączone',
    },
}


@dataclass
class ParsedImportRow:
    index: int
    rule_type: Optional[str]
    source_url: str = ''
    target_url: str = ''
    product_id: Optional[int] = None
    category_id: Optional[int] = None
    status_code: int = 301
    active: bool = True
    generated_target: bool = False
    raw: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_session_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data['is_valid'] = self.is_valid
        return data


@dataclass
class ImportParseResult:
    rows: List[ParsedImportRow]
    total_rows: int
    valid_rows: int
    invalid_rows: int
    consumed_bytes: int

    def to_session_payload(self) -> Dict[str, object]:
        return {
            'total_rows': self.total_rows,
            'valid_rows': self.valid_rows,
            'invalid_rows': self.invalid_rows,
            'consumed_bytes': self.consumed_bytes,
            'rows': [row.to_session_dict() for row in self.rows],
        }


def _normalize_header(header: str) -> str:
    value = (header or '').strip().lower()
    normalized = ''.join(ch if ch.isalnum() else '_' for ch in value)
    while '__' in normalized:
        normalized = normalized.replace('__', '_')
    return normalized.strip('_')


def _normalize_rule_type_token(value: str) -> Optional[str]:
    token = (value or '').strip().lower()
    if not token:
        return None
    token = token.replace('→', ' ').replace('->', ' ').replace('/', ' ')
    token = token.replace('-', ' ').replace('_', ' ')
    token = ' '.join(token.split())  # collapse whitespace
    if not token:
        return None
    compact = token.replace(' ', '')
    if any(word in token for word in ('product', 'produkt')) or compact.startswith('p'):
        return 'product_to_url'
    if any(word in token for word in ('category', 'kategoria')) or compact.startswith('c'):
        return 'category_to_url'
    if 'url' in token:
        return 'url_to_url'
    return None


def _build_header_map(fieldnames: Iterable[str]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        normalized = _normalize_header(raw)
        for canonical, aliases in COLUMN_ALIASES.items():
            if normalized in aliases:
                mapping[raw] = canonical
                break
    return mapping


def _parse_int(value: str, *, field_label: str, errors: List[str]) -> Optional[int]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f'Wartość "{value}" w kolumnie {field_label} nie jest liczbą całkowitą.')
        return None


def _parse_status_code(value: str, errors: List[str]) -> int:
    if not value:
        return 301
    raw = value.strip()
    if not raw:
        return 301
    try:
        code = int(raw)
    except (TypeError, ValueError):
        errors.append(f'Kod HTTP "{raw}" nie jest liczbą. Dozwolone: 301 lub 302.')
        return 301
    if code not in (301, 302):
        errors.append(f'Kod HTTP "{code}" nie jest obsługiwany. Użyj 301 lub 302.')
        return 301
    return code


def _parse_bool(value: str) -> bool:
    if value is None:
        return True
    raw = value.strip().lower()
    if not raw:
        return True
    if raw in {'0', 'false', 'no', 'n', 'off'}:
        return False
    return True


def _detect_rule_type(initial: Optional[str], product_id: Optional[int], category_id: Optional[int], source_url: str) -> Optional[str]:
    if initial in {'url_to_url', 'product_to_url', 'category_to_url'}:
        return initial
    if product_id:
        return 'product_to_url'
    if category_id:
        return 'category_to_url'
    if source_url:
        return 'url_to_url'
    return None


def _mark_duplicates(rows: List[ParsedImportRow]) -> None:
    by_source: Dict[str, List[ParsedImportRow]] = {}
    for row in rows:
        src = row.source_url or ''
        if not src:
            continue
        by_source.setdefault(src.lower(), []).append(row)
    for items in by_source.values():
        if len(items) > 1:
            for row in items:
                row.warnings.append('W pliku występuje więcej niż jedno przekierowanie z tego samego źródłowego URL.')


def parse_redirects_csv(uploaded_file) -> ImportParseResult:
    try:
        raw_bytes = uploaded_file.read()
    except Exception as exc:
        raise RedirectImportError(f'Nie udało się odczytać pliku CSV: {exc}')

    if hasattr(uploaded_file, 'seek'):
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

    if not raw_bytes:
        raise RedirectImportError('Plik CSV jest pusty.')

    try:
        text = raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise RedirectImportError('Plik CSV musi być zakodowany w UTF-8.') from exc

    stream = io.StringIO(text)
    reader = csv.DictReader(stream)
    if reader.fieldnames is None:
        raise RedirectImportError('Plik CSV nie zawiera nagłówka.')

    header_map = _build_header_map(reader.fieldnames)
    if not header_map:
        raise RedirectImportError('Plik CSV nie zawiera rozpoznawalnych kolumn (np. source_url, target_url, product_id).')

    rows: List[ParsedImportRow] = []
    consumed_rows = 0
    for line_number, raw_row in enumerate(reader, start=2):
        if not raw_row:
            continue
        cleaned_values: Dict[str, str] = {}
        for original_header, value in raw_row.items():
            if original_header in header_map:
                cleaned_values[header_map[original_header]] = (value or '').strip()
        if not any(cleaned_values.values()):
            # Skip completely empty rows
            continue

        row = ParsedImportRow(
            index=line_number,
            rule_type=None,
            raw={k: (v or '').strip() for k, v in raw_row.items() if v},
        )
        row.rule_type = _detect_rule_type(
            _normalize_rule_type_token(cleaned_values.get('rule_type', '')),
            None,
            None,
            cleaned_values.get('source_url', ''),
        )

        pid_raw = cleaned_values.get('product_id')
        cid_raw = cleaned_values.get('category_id')
        row.product_id = _parse_int(pid_raw or '', field_label='product_id', errors=row.errors)
        row.category_id = _parse_int(cid_raw or '', field_label='category_id', errors=row.errors)

        source_url = cleaned_values.get('source_url', '')
        target_url = cleaned_values.get('target_url', '')
        status_code = cleaned_values.get('status_code', '')
        active_raw = cleaned_values.get('active', '')

        row.status_code = _parse_status_code(status_code, row.errors)
        row.active = _parse_bool(active_raw)

        # Detect rule type again after parsing IDs
        row.rule_type = _detect_rule_type(row.rule_type, row.product_id, row.category_id, source_url)

        if row.rule_type not in {'url_to_url', 'product_to_url', 'category_to_url'}:
            row.errors.append('Nie udało się określić typu przekierowania (rule_type).')

        row.source_url = _norm_path(source_url) if source_url else ''
        if row.rule_type == 'url_to_url' and not row.source_url:
            row.errors.append('Dla przekierowania URL → URL wymagany jest source_url.')

        if row.rule_type == 'url_to_url':
            row.target_url = _norm_path(target_url) if target_url else ''
            if not row.target_url:
                row.errors.append('Dla przekierowania URL → URL wymagany jest target_url.')
        elif row.rule_type == 'product_to_url':
            if not row.product_id:
                row.errors.append('Dla przekierowania Product ID → URL wymagane jest product_id.')
            if not row.source_url:
                row.errors.append('Dla przekierowania Product ID → URL wymagany jest source_url (skąd przekierować).')
            if target_url:
                row.target_url = _norm_path(target_url)
            else:
                if row.product_id:
                    row.target_url = _norm_path(f'/product/{row.product_id}')
                    row.generated_target = True
        elif row.rule_type == 'category_to_url':
            if not row.category_id:
                row.errors.append('Dla przekierowania Category ID → URL wymagane jest category_id.')
            if not row.source_url:
                row.errors.append('Dla przekierowania Category ID → URL wymagany jest source_url (skąd przekierować).')
            if target_url:
                row.target_url = _norm_path(target_url)
            else:
                if row.category_id:
                    row.target_url = _norm_path(f'/category/{row.category_id}')
                    row.generated_target = True

        rows.append(row)
        consumed_rows += 1

    if not rows:
        raise RedirectImportError('Plik CSV nie zawiera żadnych rekordów do importu.')

    _mark_duplicates(rows)

    valid_rows = sum(1 for row in rows if row.is_valid)
    invalid_rows = len(rows) - valid_rows

    return ImportParseResult(
        rows=rows,
        total_rows=len(rows),
        valid_rows=valid_rows,
        invalid_rows=invalid_rows,
        consumed_bytes=len(raw_bytes),
    )
