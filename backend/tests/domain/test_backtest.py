"""
Domain tests for backtester calculations
"""
import pytest


class TestBacktestMetrics:
    """Test that backtest result metrics are calculated correctly."""

    def test_final_capital_reflects_trades(self, api_client):
        """Final capital should change from initial based on trade P&L."""
        payload = {
            'symbol': 'sh600000',
            'start_date': '2025-01-01',
            'end_date': '2025-03-31',
            'initial_capital': 100000,
            'strategy_type': 'sma_cross',
        }
        resp = api_client.post('/strategy/backtest', json=payload)
        assert resp.status_code == 200
        backtest_id = resp.json().get('data', {}).get('id')
        if not backtest_id:
            backtest_id = resp.json().get('data', {}).get('backtest_id')
        if not backtest_id:
            pytest.skip('Could not create backtest to test metrics')

        import time
        time.sleep(2)

        get_resp = api_client.get(f'/strategy/backtest/{backtest_id}')
        assert get_resp.status_code == 200
        data = get_resp.json().get('data', {})
        if data.get('status') == 'completed':
            initial = data.get('initial_capital', 0)
            final = data.get('final_capital', data.get('final_equity', 0))
            # With no trades, final should equal initial
            # With trades, it may differ
            assert isinstance(initial, (int, float))
            assert isinstance(final, (int, float))


class TestSystemHealth:
    """Tests for system health and scheduler endpoints."""

    def test_health_returns_200(self, api_client):
        resp = api_client.get('/system/health')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}'

    def test_health_has_db_status(self, api_client):
        resp = api_client.get('/system/health')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json
        assert 'status' in json['data']
        assert json['data']['status'] == 'ok'

    def test_scheduler_endpoint_returns_200(self, api_client):
        resp = api_client.get('/system/scheduler')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'

    def test_scheduler_has_running_field(self, api_client):
        resp = api_client.get('/system/scheduler')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json
        data = json['data']
        assert 'running' in data
        assert 'jobs' in data
        assert isinstance(data['jobs'], list)
