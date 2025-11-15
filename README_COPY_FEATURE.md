# 🎉 Nowa funkcjonalność: Kopiowanie produktów między sklepami

## 📝 Co zostało dodane?

Zaimplementowano pełną funkcjonalność kopiowania produktów z jednego sklepu Shoper do drugiego w systemie ShoperCenter. 

### ✨ Kluczowe cechy:
- ✅ **Kopiowanie masowe** - możliwość zaznaczenia i skopiowania wielu produktów naraz
- ✅ **Kopiowanie pojedyncze** - przycisk w menu akcji dla każdego produktu
- ✅ **Wybór sklepu docelowego** - wygodny dropdown z listą dostępnych sklepów
- ✅ **Podgląd produktów** - przed kopiowaniem widzisz listę z nazwami i kodami
- ✅ **Szczegółowe logi** - każdy krok operacji jest logowany do pliku
- ✅ **Bezpieczne** - produkty NIE są usuwane ze źródłowego sklepu
- ✅ **Kompletne kopiowanie** - wszystkie możliwe pola (podstawowe, stock, tłumaczenia)

## 🚀 Jak używać?

### Sposób 1: Kopiowanie wielu produktów
1. Wejdź do modułu produktów
2. Zaznacz produkty klikając w checkboxy (lewa kolumna)
3. Kliknij **"Kopiuj do sklepu (X)"** w toolbarze
4. W modalu wybierz sklep docelowy
5. Kliknij **"Kopiuj produkty"**
6. Poczekaj na zakończenie - zobaczysz szczegółowe podsumowanie

### Sposób 2: Kopiowanie pojedynczego produktu
1. W tabeli produktów znajdź produkt
2. W kolumnie "Akcje" kliknij **"Kopiuj do sklepu"**
3. Wybierz sklep docelowy
4. Kliknij **"Kopiuj produkty"**

## 📁 Zmodyfikowane pliki

### 1. Backend
- **`modules/views.py`** - dodana funkcja `products_copy_to_shop_json()` z pełnym logowaniem
- **`modules/urls.py`** - dodany endpoint `/products/copy_to_shop.json`

### 2. Frontend
- **`templates/modules/module_detail.html`**:
  - Dodany modal z interfejsem kopiowania
  - Przycisk "Kopiuj do sklepu" w toolbarze
  - Przycisk "Kopiuj do sklepu" w kolumnie Akcje
  - Funkcje JavaScript do obsługi całego procesu

### 3. Dokumentacja
- **`COPY_PRODUCTS_FEATURE.md`** - pełna dokumentacja funkcjonalności
- **`test_copy_products.py`** - skrypt testowy do automatycznego testowania

## 🔍 Co jest kopiowane?

### Pola produktu:
- Typ, kategoria, kod (SKU), PKWiU
- Producent, grupa, VAT, jednostka, waluta
- EAN, kod producenta, waga
- Flagi: bestseller, nowość, program lojalnościowy

### Stock (magazyn):
- Cena, aktywność, dostępność
- Stan magazynowy, poziom ostrzeżenia
- Kody wariantów, waga wariantu
- Ceny specjalne i hurtowe

### Tłumaczenia (wszystkie języki):
- Nazwa, opisy (krótki i pełny)
- Aktywność, wyświetlanie na stronie głównej
- Pola SEO (tytuł, opis, słowa kluczowe)
- Opisy producenta i inne

## 🛡️ Bezpieczeństwo

- ✅ Wymaga zalogowania
- ✅ Sprawdza właściciela modułu i sklepu
- ✅ Waliduje dane wejściowe
- ✅ Ochrona CSRF
- ✅ **Nie usuwa produktów źródłowych** (tylko kopiuje)
- ✅ Nie można kopiować do tego samego sklepu

## 📊 Logowanie

Każda operacja jest szczegółowo logowana w `logs/shopercenter.log`:

```
INFO: === products_copy_to_shop_json called ===
INFO: Source module: Produkty Sklep A (ID: 1)
INFO: Target shop verified: Sklep B (ID: 2)
INFO: [1/3] Processing product ID: 123
INFO: [1/3] Product name: Test Product
INFO: [1/3] ✓ Successfully copied product 123 -> new ID: 456
INFO: === Copy operation completed: copied=3, failed=0 ===
```

## 🧪 Testowanie

### Ręczne:
1. Zaloguj się do ShoperCenter
2. Przejdź do modułu produktów
3. Przetestuj oba sposoby kopiowania
4. Sprawdź logi: `tail -f logs/shopercenter.log`

### Automatyczne:
```bash
# Edytuj parametry w pliku test_copy_products.py
python test_copy_products.py
```

## 🐛 Rozwiązywanie problemów

### Nie widzę przycisku "Kopiuj do sklepu"
- Sprawdź czy jesteś w module typu "Products"
- Odśwież stronę (Ctrl+F5)

### Nie widzę sklepów w dropdown
- Dodaj przynajmniej 2 sklepy w systemie
- Sprawdź czy sklepy należą do Twojego konta

### Produkty nie są kopiowane
1. Sprawdź logi: `logs/shopercenter.log`
2. Sprawdź konsolę przeglądarki (F12)
3. Upewnij się że tokeny API sklepów są poprawne
4. Sprawdź czy produkty mają wymagane pola

### Błąd "Brak wymaganych pól"
System automatycznie uzupełnia brakujące pola:
- `pkwiu` → używa domyślnego `00.00.00.0`
- `code` → generuje `COPY-{ID}`
- `category_id` → używa kategorii `1`

Jeśli nadal widzisz ten błąd, sprawdź czy produkt ma:
- `stock.price` (cena > 0)
- `translations.pl_PL.name` (nazwa polska)

**Wskazówka:** Po skopiowaniu możesz poprawić auto-uzupełnione wartości w sklepie docelowym.

## 💡 Wskazówki

1. **Przed kopiowaniem** - sprawdź czy kategorie istnieją w sklepie docelowym
2. **Unikaj duplikatów** - system nie zmienia automatycznie kodów produktów
3. **Sprawdź rezultaty** - po kopiowaniu wejdź do sklepu docelowego i zweryfikuj produkty
4. **Używaj logów** - w razie problemów najpierw sprawdź logi
5. **Testuj na małej grupie** - najpierw skopiuj 1-2 produkty testowe

## 📞 Wsparcie

W razie problemów:
1. ✅ Sprawdź plik `COPY_PRODUCTS_FEATURE.md` - szczegółowa dokumentacja
2. ✅ Sprawdź logi `logs/shopercenter.log`
3. ✅ Sprawdź konsolę przeglądarki (F12 -> Console)
4. ✅ Użyj skryptu testowego `test_copy_products.py`

---

**Autor:** GitHub Copilot  
**Data:** 2025-11-15  
**Wersja:** 1.0
