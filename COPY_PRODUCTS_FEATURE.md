# Funkcjonalność kopiowania produktów między sklepami

## Opis
Dodana nowa funkcjonalność umożliwiająca kopiowanie produktów z jednego sklepu Shoper do innego w systemie ShoperCenter. Produkty są **kopiowane** (nie przenoszone) - oryginalne produkty pozostają w źródłowym sklepie bez zmian.

## Główne cechy
- ✅ Kopiowanie pojedynczych produktów lub wielu produktów naraz
- ✅ Wybór sklepu docelowego z listy dostępnych sklepów użytkownika
- ✅ Podgląd nazw produktów przed kopiowaniem
- ✅ Kopiowanie wszystkich możliwych pól produktu (podstawowe, stock, tłumaczenia)
- ✅ Szczegółowe logowanie każdego kroku operacji
- ✅ **Produkty NIE są usuwane ze źródłowego sklepu**
- ✅ Obsługa błędów z informacją dla użytkownika

## Jak używać

### 1. Kopiowanie wielu produktów (bulk)
1. W widoku modułu produktów zaznacz produkty klikając w checkboxy po lewej stronie
2. Kliknij przycisk **"Kopiuj do sklepu (X)"** w toolbarze (gdzie X to liczba zaznaczonych produktów)
3. W otwartym modalu:
   - Zobacz listę produktów do skopiowania
   - Wybierz sklep docelowy z dropdown
   - Kliknij **"Kopiuj produkty"**
4. Poczekaj na zakończenie operacji - zobaczysz szczegółowe podsumowanie

### 2. Kopiowanie pojedynczego produktu
1. W widoku modułu produktów znajdź produkt w tabeli
2. W kolumnie "Akcje" kliknij przycisk **"Kopiuj do sklepu"**
3. Postępuj jak w punkcie 3 powyżej

## Co jest kopiowane?

### Pola podstawowe produktu:
- `type` - typ produktu
- `category_id` - kategoria
- `code` - kod produktu (SKU)
- `pkwiu` - PKWiU
- `producer_id` - producent
- `group_id` - grupa
- `tax_id` - stawka VAT
- `unit_id` - jednostka
- `currency_id` - waluta
- `ean` - kod EAN
- `producer_code` - kod producenta
- `weight` - waga
- `bestseller`, `newproduct`, `in_loyalty` - flagi
- `external_id` - ID zewnętrzne

### Pola stock (magazynowe):
- `price` - cena
- `active` - aktywność
- `default` - domyślny wariant
- `availability_id` - dostępność
- `delivery_id` - wysyłka
- `stock` - stan magazynowy
- `warn_level` - poziom ostrzeżenia
- `code`, `ean` - kody wariantu
- `weight`, `weight_type` - waga wariantu
- Ceny specjalne i hurtowe

### Tłumaczenia (translations):
- `name` - nazwa produktu
- `short_description` - krótki opis
- `description` - pełny opis
- `active` - aktywność tłumaczenia
- `main_page` - wyświetlanie na stronie głównej
- `seo_title`, `seo_description`, `seo_keywords` - pola SEO
- `page_title` - tytuł strony
- Inne opisy

## Walidacja i auto-uzupełnianie

System automatycznie uzupełnia brakujące wymagane pola:
- 🔧 **pkwiu** - jeśli brak, używa domyślnego `00.00.00.0` (kod generyczny)
- 🔧 **code** - jeśli brak, generuje `COPY-{product_id}`
- 🔧 **category_id** - jeśli brak, używa domyślnej kategorii `1`

Po auto-uzupełnieniu system sprawdza:
- ✅ Czy wszystkie wymagane pola są wypełnione
- ✅ Czy cena jest większa od 0
- ✅ Czy sklep docelowy istnieje i należy do użytkownika
- ✅ Czy nie próbujemy kopiować do tego samego sklepu

**Uwaga:** Auto-uzupełnianie zapewnia, że produkty zostaną skopiowane nawet jeśli mają niekompletne dane. Po skopiowaniu możesz ręcznie poprawić te wartości w sklepie docelowym.

## Logowanie

Każda operacja kopiowania jest szczegółowo logowana w pliku `logs/shopercenter.log`:

```
[timestamp] INFO modules.views: === products_copy_to_shop_json called: method=POST, module_pk=1, user=admin ===
[timestamp] INFO modules.views: Source module: Produkty Sklep A (ID: 1), Shop: Sklep A (ID: 1)
[timestamp] INFO modules.views: Target shop verified: Sklep B (ID: 2)
[timestamp] INFO modules.views: [1/3] === Processing product ID: 123 ===
[timestamp] INFO modules.views: [1/3] Product name: Test Product
[timestamp] INFO modules.views: [1/3] Copied field 'category_id': 5
[timestamp] INFO modules.views: [1/3] Copied field 'code': TEST-001
[timestamp] INFO modules.views: [1/3] ✓ Successfully copied product 123 -> new ID: 456
[timestamp] INFO modules.views: === Copy operation completed: copied=3, failed=0 ===
```

## Pliki zmodyfikowane

1. **`modules/views.py`**
   - Dodana funkcja `products_copy_to_shop_json()` - główna logika kopiowania
   - Obsługa GET (lista sklepów) i POST (wykonanie kopiowania)

2. **`modules/urls.py`**
   - Dodany endpoint: `/modules/<pk>/products/copy_to_shop.json`

3. **`templates/modules/module_detail.html`**
   - Dodany modal `copy-to-shop-modal` z interfejsem użytkownika
   - Dodany przycisk "Kopiuj do sklepu" w toolbarze
   - Dodany przycisk "Kopiuj do sklepu" w kolumnie Akcje
   - Dodane funkcje JavaScript do obsługi kopiowania
   - Zaktualizowana funkcja `updateSelectedUI()` do obsługi licznika kopiowania

## Testowanie

### 1. Sprawdź logi
```bash
tail -f /home/ShoperCenter/logs/shopercenter.log
```

### 2. Testuj różne scenariusze:
- ✅ Kopiowanie 1 produktu
- ✅ Kopiowanie wielu produktów (3-10)
- ✅ Kopiowanie bez zaznaczonych produktów (powinien pokazać alert)
- ✅ Kopiowanie do tego samego sklepu (powinien pokazać błąd)
- ✅ Kopiowanie gdy brak innych sklepów (powinien pokazać info)

### 3. Sprawdź sklep docelowy
Po skopiowaniu zaloguj się do API sklepu docelowego i sprawdź czy produkty zostały utworzone poprawnie.

## Bezpieczeństwo

- ✅ Wymagane zalogowanie (`@login_required`)
- ✅ Sprawdzanie właściciela modułu i sklepu
- ✅ Walidacja danych wejściowych
- ✅ Ochrona CSRF
- ✅ Brak możliwości usunięcia produktów źródłowych

## Obsługa błędów

System obsługuje następujące błędy:
- Nieprawidłowe ID produktu
- Brak wymaganych pól w produkcie źródłowym
- Błąd komunikacji z API Shoper
- Brak dostępu do sklepu docelowego
- Próba kopiowania do tego samego sklepu

Każdy błąd jest:
- Logowany do pliku logów
- Wyświetlany użytkownikowi w modalu
- Uwzględniany w podsumowaniu operacji

## Wsparcie

W razie problemów:
1. Sprawdź logi w `logs/shopercenter.log`
2. Sprawdź konsolę przeglądarki (F12)
3. Sprawdź czy sklepy mają poprawne tokeny API
4. Sprawdź czy produkty źródłowe mają wszystkie wymagane pola
