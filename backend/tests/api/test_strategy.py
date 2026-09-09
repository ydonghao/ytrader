"""
API tests for /strategy endpoints
"""
import pytest
import time


class TestStrategyList:
    """Tests for GET/POST /strategy/strategies"""

    def test_list_returns_200(self, api_client):
        resp = api_client.get('/strategy/strategies')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'

    def test_list_returns_array(self, api_client):
        resp = api_client.get('/strategy/strategies')
        assert resp.status_code == 200
        json = resp.json()
        assert isinstance(json.get('data'), list), 'strategies should be a list'

    def test_post_strategy_returns_201(self, api_client):
        """Create a new SMA strategy."""
        name = f'test_sma_{int(time.time())}'
        payload = {
            'name': name,
            'type': 'sma_cross',
            'config': {'fast_period': 5, 'slow_period': 20},
        }
        resp = api_client.post('/strategy/strategies', json=payload)
        assert resp.status_code in (200, 201), f'Expected 200/201, got {resp.status_code}: {resp.text}'
        json = resp.json()
        assert json.get('code') == 0, f'Expected code=0: {json}'
        assert 'data' in json

    def test_post_and_delete_strategy(self, api_client):
        """Create then delete a strategy."""
        name = f'test_del_{int(time.time())}'
        payload = {
            'name': name,
            'type': 'sma_cross',
            'config': {'fast_period': 5, 'slow_period': 20},
        }
        create_resp = api_client.post('/strategy/strategies', json=payload)
        assert create_resp.status_code in (200, 201), f'Create failed: {create_resp.status_code}'
        data = create_resp.json().get('data', {})
        strategy_id = data.get('id') or data.get('strategy_id')
        if strategy_id:
            del_resp = api_client.delete(f'/strategy/strategies/{strategy_id}')
            assert del_resp.status_code in (200, 204), \
                f'Delete failed: {del_resp.status_code} {del_resp.text}'


class TestStrategyBacktest:
    """Tests for POST/GET /strategy/backtest"""

    def test_post_backtest_returns_200(self, api_client):
        """POST /strategy/backtest should return a backtest id."""
        payload = {
            'symbol': 'sh600000',
            'start_date': '2025-01-01',
            'end_date': '2025-03-31',
            'initial_capital': 100000,
            'strategy_type': 'sma_cross',
        }
        resp = api_client.post('/strategy/backtest', json=payload)
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'
        json = resp.json()
        assert json.get('code') == 0, f'Expected code=0: {json}'
        assert 'data' in json
        data = json['data']
        assert 'id' in data or 'backtest_id' in data, f'No id in response: {data}'

    def test_get_backtest_returns_completed_result(self, api_client):
        """Create a backtest then immediately fetch it."""
        payload = {
            'symbol': 'sh600000',
            'start_date': '2025-01-01',
            'end_date': '2025-03-31',
            'initial_capital': 100000,
            'strategy_type': 'sma_cross',
        }
        create_resp = api_client.post('/strategy/backtest', json=payload)
        assert create_resp.status_code == 200
        backtest_id = create_resp.json().get('data', {}).get('id')
        if not backtest_id:
            backtest_id = create_resp.json().get('data', {}).get('backtest_id')

        if backtest_id:
            # Give it a moment to complete
            import time as time_module
            time_module.sleep(2)
            get_resp = api_client.get(f'/strategy/backtest/{backtest_id}')
            assert get_resp.status_code == 200, f'GET failed: {get_resp.status_code}'
            json = get_resp.json()
            if 'data' in json:
                data = json['data']
                assert 'status' in data, f'No status field: {data}'
                # Completed backtest should have final_capital or final_equity
                if data.get('status') == 'completed':
                    has_capital = 'final_capital' in data or 'final_equity' in data
                    assert has_capital, f'Completed backtest missing capital field: {data}'

    def test_backtest_invalid_symbol(self, api_client):
        """Backtest with invalid symbol should not crash."""
        payload = {
            'symbol': 'invalid_symbol_xyz',
            'start_date': '2025-01-01',
            'end_date': '2025-03-31',
            'initial_capital': 100000,
            'strategy_type': 'sma_cross',
        }
        resp = api_client.post('/strategy/backtest', json=payload)
        # Should return 200 with status=failed, not 500
        assert resp.status_code in (200, 400, 422), \
            f'Unexpected status {resp.status_code}: {resp.text}'
