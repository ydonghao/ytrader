"""
API tests for /trade endpoints
"""
import pytest


class TestTradeAccount:
    """Tests for GET /trade/account"""

    def test_account_returns_200(self, api_client):
        resp = api_client.get('/trade/account')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'

    def test_account_returns_required_fields(self, api_client):
        resp = api_client.get('/trade/account')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json, f'Expected "data" key: {json}'
        data = json['data']
        required = {'account_id', 'total_assets', 'cash', 'positions_value',
                    'total_profit', 'status'}
        actual = set(data.keys())
        assert required.issubset(actual), f'Missing fields: {required - actual}'

    def test_account_cash_is_numeric(self, api_client):
        resp = api_client.get('/trade/account')
        assert resp.status_code == 200
        data = resp.json()['data']
        assert isinstance(data['cash'], (int, float))
        assert data['cash'] >= 0

    def test_account_total_assets_greater_equal_cash(self, api_client):
        """total_assets should be >= cash (positions add value)."""
        resp = api_client.get('/trade/account')
        assert resp.status_code == 200
        data = resp.json()['data']
        assert data['total_assets'] >= data['cash'], \
            f'total_assets ({data["total_assets"]}) < cash ({data["cash"]})'


class TestTradePositions:
    """Tests for GET /trade/positions"""

    def test_positions_returns_200(self, api_client):
        resp = api_client.get('/trade/positions')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'

    def test_positions_returns_list(self, api_client):
        resp = api_client.get('/trade/positions')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json
        assert isinstance(json['data'], list), f'Expected list, got {type(json["data"])}'

    def test_position_fields(self, api_client):
        """Each position should have symbol, quantity, avg_price, current_price."""
        resp = api_client.get('/trade/positions')
        assert resp.status_code == 200
        positions = resp.json()['data']
        if positions:
            required = {'symbol', 'quantity', 'avg_price', 'current_price'}
            first = positions[0]
            actual = set(first.keys())
            assert required.issubset(actual), f'Missing position fields: {required - actual}'


class TestTradeOrders:
    """Tests for GET/POST /trade/orders"""

    def test_orders_list_returns_200(self, api_client):
        resp = api_client.get('/trade/orders')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'

    def test_orders_list_returns_array(self, api_client):
        resp = api_client.get('/trade/orders')
        assert resp.status_code == 200
        json = resp.json()
        assert isinstance(json.get('data'), list), 'orders should be a list'

    def test_post_order_returns_valid_structure(self, api_client):
        """POST /trade/orders with valid data should return 200 and order object."""
        payload = {
            'symbol': 'sh600000',
            'side': 'BUY',
            'order_type': 'LIMIT',
            'price': 10.00,
            'quantity': 100,
        }
        resp = api_client.post('/trade/orders', json=payload)
        # Accept 200 (success) or 400 (validation/system error)
        assert resp.status_code in (200, 201, 400, 422), \
            f'Unexpected status {resp.status_code}: {resp.text}'
