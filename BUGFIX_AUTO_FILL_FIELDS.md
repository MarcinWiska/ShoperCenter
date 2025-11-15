# 🔧 Poprawka: Auto-uzupełnianie brakujących pól

## Problem
Produkty źródłowe nie miały wypełnionego pola `pkwiu`, które jest wymagane przez API Shopera. Powodowało to błąd:
```
ERROR [5/5] Validation failed: Brak wymaganych pól: pkwiu
```

## Rozwiązanie
Dodano automatyczne uzupełnianie brakujących wymaganych pól wartościami domyślnymi:

### 1. PKWiU (kod statystyczny)
- **Jeśli brak:** System automatycznie używa `00.00.00.0` (kod generyczny dla produktów)
- **Log:** `WARNING Missing pkwiu, using default: 00.00.00.0`

### 2. Code (kod produktu/SKU)
- **Jeśli brak:** Generuje `COPY-{product_id}` (np. `COPY-123`)
- **Log:** `WARNING Missing code, using fallback: COPY-123`

### 3. Category ID
- **Jeśli brak:** Używa domyślnej kategorii `1`
- **Log:** `WARNING Missing category_id, using default: 1`

## Przykład logów po poprawce

### PRZED (błąd):
```
INFO [1/5] Validating required fields...
ERROR [1/5] Validation failed: Brak wymaganych pól: pkwiu
INFO === Copy operation completed: copied=0, failed=5 ===
```

### PO (sukces):
```
INFO [1/5] Auto-filling missing required fields...
WARNING [1/5] Missing pkwiu, using default: 00.00.00.0
INFO [1/5] Validating required fields...
INFO [1/5] Validation passed
INFO [1/5] Creating product in target shop...
INFO [1/5] ✓ Successfully copied product 123 -> new ID: 456
INFO === Copy operation completed: copied=5, failed=0 ===
```

## Co się dzieje teraz?

1. **System wykrywa brakujące pole** (np. pkwiu)
2. **Automatycznie uzupełnia wartość domyślną**
3. **Loguje ostrzeżenie** (WARNING) do pliku logów
4. **Kontynuuje kopiowanie** produktu
5. **Produkt zostaje skopiowany** z auto-uzupełnionymi polami

## Zalecenia

### Po skopiowaniu produktów:
1. **Sprawdź sklep docelowy** - produkty zostały skopiowane
2. **Popraw auto-uzupełnione wartości:**
   - PKWiU: `00.00.00.0` → właściwy kod statystyczny
   - Code: `COPY-123` → unikalny kod produktu
   - Category: `1` → właściwa kategoria

### Aby uniknąć auto-uzupełniania w przyszłości:
1. **Uzupełnij pola w sklepie źródłowym** przed kopiowaniem
2. **Szczególnie ważne:**
   - `pkwiu` - kod PKWiU zgodny z kategorią produktu
   - `code` - unikalny kod SKU
   - `category_id` - poprawna kategoria

## Które pola są wymagane i NIE są auto-uzupełniane?

Te pola **MUSZĄ** istnieć w produkcie źródłowym:
- ✅ `stock.price` (cena > 0) - brak sensownej wartości domyślnej
- ✅ `translations.pl_PL.name` (nazwa) - musi pochodzić z oryginału

Jeśli ich brakuje, produkt **NIE zostanie** skopiowany i zobaczysz błąd.

## Testy

### Test 1: Produkt bez pkwiu
```python
# Produkt źródłowy:
{
  "category_id": 5,
  "code": "TEST-001",
  # pkwiu: BRAK!
  "stock": {"price": 99.99},
  "translations": {"pl_PL": {"name": "Test"}}
}

# Rezultat: ✅ Skopiowano z pkwiu = "00.00.00.0"
```

### Test 2: Produkt bez kodu
```python
# Produkt źródłowy (ID: 123):
{
  "category_id": 5,
  # code: BRAK!
  "pkwiu": "12.34.56.0",
  "stock": {"price": 99.99},
  "translations": {"pl_PL": {"name": "Test"}}
}

# Rezultat: ✅ Skopiowano z code = "COPY-123"
```

### Test 3: Produkt bez kategorii
```python
# Produkt źródłowy:
{
  # category_id: BRAK!
  "code": "TEST-001",
  "pkwiu": "12.34.56.0",
  "stock": {"price": 99.99},
  "translations": {"pl_PL": {"name": "Test"}}
}

# Rezultat: ✅ Skopiowano z category_id = 1
```

### Test 4: Produkt bez ceny
```python
# Produkt źródłowy:
{
  "category_id": 5,
  "code": "TEST-001",
  "pkwiu": "12.34.56.0",
  "stock": {"price": 0},  # lub brak
  "translations": {"pl_PL": {"name": "Test"}}
}

# Rezultat: ❌ NIE skopiowano - brak sensownej wartości domyślnej dla ceny
```

### Test 5: Produkt bez nazwy
```python
# Produkt źródłowy:
{
  "category_id": 5,
  "code": "TEST-001",
  "pkwiu": "12.34.56.0",
  "stock": {"price": 99.99},
  "translations": {"pl_PL": {}}  # brak name!
}

# Rezultat: ❌ NIE skopiowano - nazwa jest wymagana
```

## Monitoring

Sprawdź logi aby zobaczyć które pola zostały auto-uzupełnione:

```bash
# Zobacz ostrzeżenia o auto-uzupełnianiu
tail -f logs/shopercenter.log | grep "Missing"

# Przykładowe wyjście:
# WARNING [1/5] Missing pkwiu, using default: 00.00.00.0
# WARNING [2/5] Missing code, using fallback: COPY-456
# WARNING [3/5] Missing category_id, using default: 1
```

## Podsumowanie

| Pole | Auto-uzupełnienie | Wartość domyślna | Czy można pominąć? |
|------|-------------------|------------------|-------------------|
| `pkwiu` | ✅ TAK | `00.00.00.0` | ✅ TAK |
| `code` | ✅ TAK | `COPY-{ID}` | ✅ TAK |
| `category_id` | ✅ TAK | `1` | ✅ TAK |
| `stock.price` | ❌ NIE | - | ❌ NIE (musi być > 0) |
| `translations.pl_PL.name` | ❌ NIE | - | ❌ NIE (wymagana) |

---

**Data poprawki:** 2025-11-15  
**Status:** ✅ Gotowe do użycia  
**Wpływ:** Znaczne zwiększenie liczby produktów, które mogą być skopiowane
