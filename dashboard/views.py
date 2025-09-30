from typing import Dict, Any, List
import logging
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Count

from shops.models import Shop
from modules.models import Module
from seo_redirects.models import RedirectRule
from modules.shoper import fetch_rows, build_rest_url, auth_headers
import requests

logger = logging.getLogger(__name__)


def get_order_stats(shop: Shop) -> Dict[str, Any]:
    """Pobiera statystyki zamówień z API Shopera"""
    try:
        # Pobierz zamówienia z ostatnich 30 dni
        orders = fetch_rows(shop.base_url, shop.bearer_token, 'orders', limit=1000)
        
        if not orders:
            logger.warning(f"No orders fetched for shop {shop.name}")
            return {
                'total': 0,
                'pending_payment': 0,
                'paid': 0,
                'in_delivery': 0,
                'completed': 0,
                'cancelled': 0,
                'today': 0,
                'this_week': 0,
                'this_month': 0,
            }
        
        # Statystyki według statusu
        stats = {
            'total': len(orders),
            'pending_payment': 0,  # status_id = 1 (nowe, nieopłacone)
            'paid': 0,              # status_id = 2 (opłacone)
            'in_delivery': 0,       # status_id = 3-4 (w realizacji/wysłane)
            'completed': 0,         # status_id = 5 (zrealizowane)
            'cancelled': 0,         # status_id = 6-7 (anulowane/zwroty)
            'today': 0,
            'this_week': 0,
            'this_month': 0,
        }
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=now.weekday())
        month_start = today_start.replace(day=1)
        
        for order in orders:
            # Status zamówienia
            status_id = order.get('status_id')
            
            if status_id == 1:
                stats['pending_payment'] += 1
            elif status_id == 2:
                stats['paid'] += 1
            elif status_id in (3, 4):
                stats['in_delivery'] += 1
            elif status_id == 5:
                stats['completed'] += 1
            elif status_id in (6, 7):
                stats['cancelled'] += 1
            
            # Data zamówienia
            date_add = order.get('date_add') or order.get('add_date')
            if date_add:
                try:
                    # Parse date (format: YYYY-MM-DD HH:MM:SS lub YYYY-MM-DDTHH:MM:SS)
                    if 'T' in date_add:
                        order_date = datetime.fromisoformat(date_add.replace('Z', '+00:00'))
                    else:
                        order_date = datetime.strptime(date_add, '%Y-%m-%d %H:%M:%S')
                    
                    if order_date >= today_start:
                        stats['today'] += 1
                    if order_date >= week_start:
                        stats['this_week'] += 1
                    if order_date >= month_start:
                        stats['this_month'] += 1
                except Exception as e:
                    logger.debug(f"Could not parse date {date_add}: {e}")
        
        return stats
        
    except Exception as e:
        logger.error(f"Error fetching order stats for shop {shop.name}: {e}")
        return {
            'total': 0,
            'pending_payment': 0,
            'paid': 0,
            'in_delivery': 0,
            'completed': 0,
            'cancelled': 0,
            'today': 0,
            'this_week': 0,
            'this_month': 0,
        }


def get_product_stats(shop: Shop) -> Dict[str, int]:
    """Pobiera statystyki produktów"""
    try:
        products = fetch_rows(shop.base_url, shop.bearer_token, 'products', limit=0)
        
        active = 0
        inactive = 0
        out_of_stock = 0
        
        for product in products:
            # Sprawdź aktywność (translations.pl_PL.active)
            translations = product.get('translations', {})
            pl_trans = translations.get('pl_PL', {})
            is_active = pl_trans.get('active', False)
            
            if is_active:
                active += 1
            else:
                inactive += 1
            
            # Sprawdź stan magazynowy
            stock_data = product.get('stock', {})
            stock_level = stock_data.get('stock', 0)
            if stock_level <= 0:
                out_of_stock += 1
        
        return {
            'total': len(products),
            'active': active,
            'inactive': inactive,
            'out_of_stock': out_of_stock,
        }
        
    except Exception as e:
        logger.error(f"Error fetching product stats: {e}")
        return {
            'total': 0,
            'active': 0,
            'inactive': 0,
            'out_of_stock': 0,
        }


@login_required
def dashboard_view(request):
    """Główny widok dashboardu z statystykami"""
    
    # Pobierz sklepy użytkownika
    shops = Shop.objects.filter(owner=request.user)
    
    # Pobierz statystyki podstawowe
    modules_count = Module.objects.filter(owner=request.user).count()
    redirects_count = RedirectRule.objects.filter(owner=request.user).count()
    
    # Agregowane statystyki zamówień ze wszystkich sklepów
    total_order_stats = {
        'total': 0,
        'pending_payment': 0,
        'paid': 0,
        'in_delivery': 0,
        'completed': 0,
        'cancelled': 0,
        'today': 0,
        'this_week': 0,
        'this_month': 0,
    }
    
    # Agregowane statystyki produktów
    total_product_stats = {
        'total': 0,
        'active': 0,
        'inactive': 0,
        'out_of_stock': 0,
    }
    
    # Statystyki per sklep
    shop_stats = []
    
    for shop in shops:
        order_stats = get_order_stats(shop)
        product_stats = get_product_stats(shop)
        
        # Dodaj do sumy całkowitej
        for key in total_order_stats:
            total_order_stats[key] += order_stats.get(key, 0)
        
        for key in total_product_stats:
            total_product_stats[key] += product_stats.get(key, 0)
        
        shop_stats.append({
            'shop': shop,
            'orders': order_stats,
            'products': product_stats,
        })
    
    context = {
        'shops_count': shops.count(),
        'modules_count': modules_count,
        'redirects_count': redirects_count,
        'order_stats': total_order_stats,
        'product_stats': total_product_stats,
        'shop_stats': shop_stats,
    }
    
    return render(request, 'dashboard/dashboard.html', context)
