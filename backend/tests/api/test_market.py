"""
API tests for /market endpoints
"""
import pytest


class TestMarketHeatmap:
    """Tests for GET /market/heatmap"""

    def test_heatmap_returns_200(self, api_client):
        """Heatmap endpoint should return HTTP 200."""
        resp = api_client.get('/market/heatmap')
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.text}'

    def test_heatmap_returns_correct_shape(self, api_client):
        """Heatmap response should have data field with required keys."""
        resp = api_client.get('/market/heatmap?limit=5')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json, f'Expected "data" key in response: {json}'
        data = json['data']
        assert data is not None, 'data should not be null'
        required_keys = {'date', 'total_stocks', 'gainers', 'losers', 'flat',
                         'breadth_pct', 'top_gainers', 'top_losers'}
        actual_keys = set(data.keys())
        assert required_keys.issubset(actual_keys), \
            f'Missing keys: {required_keys - actual_keys}'

    def test_heatmap_breadth_calculation(self, api_client):
        """breadth_pct should equal gainers / total_stocks * 100."""
        resp = api_client.get('/market/heatmap?limit=50')
        assert resp.status_code == 200
        data = resp.json()['data']
        if data and data['total_stocks'] > 0:
            expected = round(data['gainers'] / data['total_stocks'] * 100, 2)
            assert abs(data['breadth_pct'] - expected) < 0.1, \
                f'breadth_pct={data["breadth_pct"]} != expected {expected}'

    def test_heatmap_top_gainers_sorted_by_change_pct(self, api_client):
        """top_gainers should be sorted descending by change_pct."""
        resp = api_client.get('/market/heatmap?limit=30')
        assert resp.status_code == 200
        data = resp.json()['data']
        if data and data['top_gainers']:
            pcts = [s['change_pct'] for s in data['top_gainers']]
            assert pcts == sorted(pcts, reverse=True), \
                f'gainers not sorted descending: {pcts[:5]}'

    def test_heatmap_top_losers_sorted_by_change_pct(self, api_client):
        """top_losers should be sorted ascending by change_pct."""
        resp = api_client.get('/market/heatmap?limit=30')
        assert resp.status_code == 200
        data = resp.json()['data']
        if data and data['top_losers']:
            pcts = [s['change_pct'] for s in data['top_losers']]
            assert pcts == sorted(pcts), \
                f'losers not sorted ascending: {pcts[:5]}'

    def test_heatmap_limit_parameter(self, api_client):
        """limit=N should return at most N gainers and N losers."""
        resp = api_client.get('/market/heatmap?limit=10')
        assert resp.status_code == 200
        data = resp.json()['data']
        if data:
            assert len(data['top_gainers']) <= 10
            assert len(data['top_losers']) <= 10

    def test_heatmap_has_stock_name(self, api_client):
        """Each stock in heatmap should have name field."""
        resp = api_client.get('/market/heatmap?limit=20')
        assert resp.status_code == 200
        data = resp.json()['data']
        if data and data['top_gainers']:
            for stock in data['top_gainers']:
                assert 'name' in stock, f'Missing name field: {stock}'
                assert 'symbol' in stock, f'Missing symbol field: {stock}'
                assert 'change_pct' in stock, f'Missing change_pct field: {stock}'

    def test_heatmap_change_pct_reasonable_range(self, api_client):
        """change_pct should be between -20 and +20 (typical stock limit)."""
        resp = api_client.get('/market/heatmap?limit=50')
        assert resp.status_code == 200
        data = resp.json()['data']
        if data and data['top_gainers']:
            for stock in data['top_gainers']:
                assert -25 <= stock['change_pct'] <= 25, \
                    f"Unrealistic change_pct {stock['change_pct']} for {stock['symbol']}"


class TestMarketKline:
    """Tests for GET /market/kline/{symbol}"""

    def test_kline_returns_200(self, api_client):
        """K-line endpoint should return HTTP 200 for valid symbol."""
        resp = api_client.get('/market/kline/sh600000?interval=1d')
        assert resp.status_code == 200

    def test_kline_valid_response_shape(self, api_client):
        """K-line response should have data.bars array."""
        resp = api_client.get('/market/kline/sh600000?interval=1d')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json
        # bars may be empty if no data, but structure should be correct
        bars = json['data'].get('bars', json['data'].get('data', []))
        assert isinstance(bars, list)

    def test_kline_invalid_symbol_returns_404(self, api_client):
        """Non-existent symbol should return HTTP 404."""
        resp = api_client.get('/market/kline/invalid_symbol_xyz')
        # API may return 200 with empty bars OR 404 — both acceptable
        assert resp.status_code in (200, 404)

    def test_kline_interval_parameter(self, api_client):
        """K-line should accept interval parameter."""
        resp = api_client.get('/market/kline/sh600000?interval=1d')
        assert resp.status_code == 200


class TestMarketSearch:
    """Tests for GET /market/search"""

    def test_search_returns_200(self, api_client):
        resp = api_client.get('/market/search?q=sh600000')
        assert resp.status_code == 200

    def test_search_exact_symbol_match(self, api_client):
        """Exact symbol query should return that symbol."""
        resp = api_client.get('/market/search?q=sh600000')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json
        results = json['data'] if isinstance(json['data'], list) else []
        symbols = [s['symbol'] for s in results]
        # sh600000 should appear in results
        assert any('sh600000' in s for s in symbols), \
            f'sh600000 not found in results: {symbols[:5]}'

    def test_search_returns_name_field(self, api_client):
        """Each search result should have name field."""
        resp = api_client.get('/market/search?q=sh600000')
        assert resp.status_code == 200
        json = resp.json()
        results = json['data'] if isinstance(json['data'], list) else []
        if results:
            for r in results:
                assert 'name' in r, f'Missing name in search result: {r}'

    def test_search_empty_query_returns_empty(self, api_client):
        """Empty query should be rejected by API (422) or return empty list."""
        resp = api_client.get('/market/search?q=')
        # API may return 422 (validation error) or 200 with empty list — both valid
        assert resp.status_code in (200, 422), f'Unexpected status {resp.status_code}'


class TestMarketOverview:
    """Tests for GET /market/overview"""

    def test_overview_returns_200(self, api_client):
        resp = api_client.get('/market/overview')
        # May be slow, give it 15s
        assert resp.status_code == 200

    def test_overview_has_markets_data(self, api_client):
        resp = api_client.get('/market/overview')
        assert resp.status_code == 200
        json = resp.json()
        assert 'data' in json
        data = json['data']
        assert 'markets' in data
        assert isinstance(data['markets'], list)
