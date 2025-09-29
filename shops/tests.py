from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch, Mock

from .models import Shop


User = get_user_model()


class ShopViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', password='p1')

    def test_list_requires_login(self):
        resp = self.client.get(reverse('shops:list'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp['Location'])

    def test_create_shop_assigns_owner(self):
        self.client.login(username='u1', password='p1')
        data = {
            'name': 'Sklep Test',
            'base_url': 'https://example.com/webapi',
            'bearer_token': 'token123',
        }
        resp = self.client.post(reverse('shops:add'), data, follow=True)
        self.assertEqual(resp.status_code, 200)
        shop = Shop.objects.get(name='Sklep Test')
        self.assertEqual(shop.owner, self.user)

    @patch('shops.views.requests.get')
    def test_test_connection_success(self, mock_get):
        self.client.login(username='u1', password='p1')
        shop = Shop.objects.create(owner=self.user, name='S', base_url='https://example.com/webapi', bearer_token='x')
        mock_resp = Mock(status_code=200)
        mock_resp.json.return_value = {"version": "1.0"}
        mock_get.return_value = mock_resp

        resp = self.client.get(reverse('shops:test', args=[shop.pk]), follow=True)
        self.assertEqual(resp.status_code, 200)
        # Message should be in context
        messages = list(resp.context['messages'])
        self.assertTrue(any('Połączenie OK' in str(m) for m in messages))

# Create your tests here.
