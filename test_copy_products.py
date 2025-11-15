#!/usr/bin/env python3
"""
Test script for the copy products feature.
This script demonstrates how to test the copy functionality programmatically.
"""

import json
import requests
from typing import Dict, Any

# Configuration
BASE_URL = "http://localhost:8000"  # Change to your server URL
USERNAME = "admin"  # Change to your username
PASSWORD = "your_password"  # Change to your password

class ShoperCenterTester:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.csrf_token = None
        
    def login(self) -> bool:
        """Login to ShoperCenter and get CSRF token."""
        print(f"🔐 Logging in as {self.username}...")
        
        # Get login page to obtain CSRF token
        login_url = f"{self.base_url}/accounts/login/"
        response = self.session.get(login_url)
        
        if 'csrftoken' in self.session.cookies:
            self.csrf_token = self.session.cookies['csrftoken']
        
        # Perform login
        login_data = {
            'username': self.username,
            'password': self.password,
            'csrfmiddlewaretoken': self.csrf_token
        }
        
        response = self.session.post(login_url, data=login_data, allow_redirects=True)
        
        if response.status_code == 200 and 'sessionid' in self.session.cookies:
            print("✅ Login successful!")
            return True
        else:
            print(f"❌ Login failed: {response.status_code}")
            return False
    
    def get_available_shops(self, module_pk: int) -> Dict[str, Any]:
        """Get list of available target shops."""
        print(f"\n📋 Getting available shops for module {module_pk}...")
        
        url = f"{self.base_url}/modules/{module_pk}/products/copy_to_shop.json"
        headers = {
            'Accept': 'application/json',
            'X-CSRFToken': self.csrf_token
        }
        
        response = self.session.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                shops = data.get('shops', [])
                print(f"✅ Found {len(shops)} available shops:")
                for shop in shops:
                    print(f"   - [{shop['id']}] {shop['name']}")
                return data
            else:
                print(f"❌ Error: {data.get('error')}")
                return data
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return {'ok': False, 'error': f'HTTP {response.status_code}'}
    
    def copy_products(self, module_pk: int, product_ids: list, target_shop_id: int) -> Dict[str, Any]:
        """Copy products to target shop."""
        print(f"\n🔄 Copying {len(product_ids)} products to shop {target_shop_id}...")
        print(f"   Product IDs: {product_ids}")
        
        url = f"{self.base_url}/modules/{module_pk}/products/copy_to_shop.json"
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRFToken': self.csrf_token
        }
        
        payload = {
            'product_ids': product_ids,
            'target_shop_id': target_shop_id
        }
        
        response = self.session.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok'):
                print(f"✅ Copy operation completed!")
                print(f"   ✓ Copied: {data.get('copied', 0)}")
                print(f"   ✗ Failed: {data.get('failed', 0)}")
                print(f"   Target shop: {data.get('target_shop_name', 'Unknown')}")
                
                # Show detailed results
                results = data.get('results', [])
                if results:
                    print(f"\n📊 Detailed results:")
                    for idx, result in enumerate(results, 1):
                        if result.get('ok'):
                            print(f"   [{idx}] ✓ {result.get('product_name', 'Unknown')} "
                                  f"({result.get('source_product_id')} -> {result.get('new_product_id')})")
                        else:
                            print(f"   [{idx}] ✗ {result.get('product_name', result.get('product_id'))} "
                                  f"- Error: {result.get('error')}")
                
                return data
            else:
                print(f"❌ Error: {data.get('error')}")
                return data
        else:
            print(f"❌ HTTP Error: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            return {'ok': False, 'error': f'HTTP {response.status_code}'}
    
    def run_test(self, module_pk: int, product_ids: list, target_shop_id: int = None):
        """Run complete test scenario."""
        print("=" * 60)
        print("🧪 ShoperCenter Copy Products Test")
        print("=" * 60)
        
        # Login
        if not self.login():
            print("\n❌ Test aborted: Login failed")
            return
        
        # Get available shops
        shops_data = self.get_available_shops(module_pk)
        if not shops_data.get('ok'):
            print("\n❌ Test aborted: Cannot get shops list")
            return
        
        shops = shops_data.get('shops', [])
        if not shops:
            print("\n⚠️  No available target shops found. Test cannot continue.")
            return
        
        # Use provided target_shop_id or first available shop
        if target_shop_id is None:
            target_shop_id = shops[0]['id']
            print(f"\n💡 No target shop specified, using first available: [{target_shop_id}] {shops[0]['name']}")
        
        # Copy products
        result = self.copy_products(module_pk, product_ids, target_shop_id)
        
        # Summary
        print("\n" + "=" * 60)
        if result.get('ok'):
            print("✅ TEST PASSED")
        else:
            print("❌ TEST FAILED")
        print("=" * 60)


def main():
    """Main test function."""
    # Initialize tester
    tester = ShoperCenterTester(BASE_URL, USERNAME, PASSWORD)
    
    # Test parameters - MODIFY THESE
    MODULE_PK = 1  # Your module ID
    PRODUCT_IDS = [123, 456, 789]  # Products to copy
    TARGET_SHOP_ID = None  # None = auto-select first available shop, or specify shop ID
    
    # Run test
    tester.run_test(MODULE_PK, PRODUCT_IDS, TARGET_SHOP_ID)
    
    print("\n💡 Tip: Check logs/shopercenter.log for detailed operation logs")


if __name__ == "__main__":
    # Safety check
    print("⚠️  WARNING: This script will copy products to another shop!")
    print("Make sure you have configured the correct parameters in the script.")
    response = input("Continue? (yes/no): ")
    
    if response.lower() == 'yes':
        main()
    else:
        print("Test cancelled.")
