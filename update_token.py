#!/usr/bin/env python3
"""
Skrypt do aktualizacji tokenu API w bazie danych
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shopercenter.settings')
django.setup()

from shops.models import Shop

# Pełny token z pliku ShoperAPI.txt
FULL_TOKEN = "0327763146b8312777cccf16c555dce9eb695be1494ced3459970fdd7466d75f"

def main():
    shops = Shop.objects.all()
    
    if not shops.exists():
        print("❌ Brak sklepów w bazie danych")
        return
    
    for shop in shops:
        print(f"\n🏪 Sklep: {shop.name}")
        print(f"   URL: {shop.base_url}")
        print(f"   Stary token (długość): {len(shop.bearer_token)} znaków")
        print(f"   Stary token: {shop.bearer_token[:20]}...{shop.bearer_token[-20:]}")
        
        if len(shop.bearer_token) < 64:
            shop.bearer_token = FULL_TOKEN
            shop.save()
            print(f"   ✅ Token zaktualizowany!")
            print(f"   Nowy token (długość): {len(shop.bearer_token)} znaków")
            print(f"   Nowy token: {shop.bearer_token[:20]}...{shop.bearer_token[-20:]}")
        else:
            print(f"   ℹ️  Token już ma prawidłową długość")

if __name__ == "__main__":
    main()
