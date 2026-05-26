"""
Unit tests for CBOE DataProvider.

Tests CBOE Athena integration for SPX option backtesting.
Uses mocked Athena client to avoid actual AWS queries.
"""
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from backtest.cboe_data_provider import CBOEDataProvider


class TestCBOEDataProvider(unittest.TestCase):
    """Test CBOE DataProvider implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock the CBOEAthenaClient to avoid real AWS queries
        self.mock_client = MagicMock()
        
        with patch("backtest.cboe_data_provider.CBOEAthenaClient", return_value=self.mock_client):
            self.provider = CBOEDataProvider(
                database="cboe",
                output_bucket="s3://test-bucket/"
            )
    
    def test_ticker_normalization(self):
        """Test SPX → ^SPX conversion."""
        assert self.provider._normalize_ticker("SPX") == "^SPX"
        assert self.provider._normalize_ticker("^SPX") == "^SPX"
        assert self.provider._normalize_ticker("spx") == "^SPX"
    
    def test_get_spread_prices_success(self):
        """Test successful spread price retrieval."""
        # Mock data for short leg
        short_df = pd.DataFrame({
            "timestamp": [datetime(2024, 3, 1, 15, 0)],
            "bid": [10.50],
            "ask": [10.70],
            "delta": [-0.25],
            "gamma": [0.001],
            "theta": [-0.05],
            "vega": [0.15],
            "volume": [100],
            "underlying_price": [5200.0],
        })
        
        # Mock data for long leg
        long_df = pd.DataFrame({
            "timestamp": [datetime(2024, 3, 1, 15, 0)],
            "bid": [3.20],
            "ask": [3.40],
            "delta": [-0.10],
            "gamma": [0.0005],
            "theta": [-0.02],
            "vega": [0.08],
            "volume": [50],
            "underlying_price": [5200.0],
        })
        
        # Mock query_greeks to return our test data
        self.mock_client.query_greeks.side_effect = [short_df, long_df]
        
        result = self.provider.get_spread_prices(
            ticker="SPX",
            expiration="2024-03-15",
            short_strike=5200,
            long_strike=5150,
            option_type="P",
            date="2024-03-01",
        )
        
        # Verify result
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["short_close"], 10.60, places=2)  # (10.50 + 10.70) / 2
        self.assertAlmostEqual(result["long_close"], 3.30, places=2)    # (3.20 + 3.40) / 2
        self.assertAlmostEqual(result["spread_value"], 7.30, places=2)  # 10.60 - 3.30
        
        # Verify bid/ask included
        self.assertEqual(result["short_bid"], 10.50)
        self.assertEqual(result["short_ask"], 10.70)
        self.assertEqual(result["long_bid"], 3.20)
        self.assertEqual(result["long_ask"], 3.40)
    
    def test_get_spread_prices_missing_data(self):
        """Test handling of missing data."""
        # Mock empty DataFrame
        self.mock_client.query_greeks.return_value = pd.DataFrame()
        
        result = self.provider.get_spread_prices(
            ticker="SPX",
            expiration="2024-03-15",
            short_strike=5200,
            long_strike=5150,
            option_type="P",
            date="2024-03-01",
        )
        
        # Should return None for missing data
        self.assertIsNone(result)
    
    def test_get_available_strikes(self):
        """Test available strikes retrieval."""
        # Mock query result
        mock_df = pd.DataFrame({
            "strike": [5100, 5150, 5200, 5250, 5300]
        })
        self.mock_client._execute_query.return_value = mock_df
        
        strikes = self.provider.get_available_strikes(
            ticker="SPX",
            expiration="2024-03-15",
            as_of_date="2024-03-01",
            option_type="P",
        )
        
        # Verify strikes
        self.assertEqual(strikes, [5100.0, 5150.0, 5200.0, 5250.0, 5300.0])
        
        # Verify query was called with correct parameters
        self.mock_client._execute_query.assert_called_once()
        query = self.mock_client._execute_query.call_args[0][0]
        self.assertIn("^SPX", query)  # ticker normalization
        self.assertIn("2024-03-15", query)
        self.assertIn("option_type = 'P'", query)
    
    def test_get_expirations(self):
        """Test expiration dates retrieval."""
        # Mock query result
        mock_df = pd.DataFrame({
            "expiration": ["2024-03-08", "2024-03-15", "2024-03-22"]
        })
        self.mock_client._execute_query.return_value = mock_df
        
        expirations = self.provider.get_expirations(
            ticker="SPX",
            as_of_date=datetime(2024, 3, 1),
            min_dte=7,
            max_dte=30,
        )
        
        # Verify expirations
        self.assertEqual(expirations, ["2024-03-08", "2024-03-15", "2024-03-22"])
    
    def test_get_greeks(self):
        """Test Greeks retrieval."""
        # Mock data with Greeks
        mock_df = pd.DataFrame({
            "timestamp": [datetime(2024, 3, 1, 15, 0)],
            "bid": [10.50],
            "ask": [10.70],
            "delta": [-0.25],
            "gamma": [0.001],
            "theta": [-0.05],
            "vega": [0.15],
            "volume": [100],
            "underlying_price": [5200.0],
        })
        self.mock_client.query_greeks.return_value = mock_df
        
        greeks = self.provider.get_greeks(
            ticker="SPX",
            strike=5200,
            option_type="P",
            expiration="2024-03-15",
            date="2024-03-01",
        )
        
        # Verify Greeks
        self.assertIsNotNone(greeks)
        self.assertAlmostEqual(greeks["delta"], -0.25, places=2)
        self.assertAlmostEqual(greeks["gamma"], 0.001, places=4)
        self.assertAlmostEqual(greeks["theta"], -0.05, places=2)
        self.assertAlmostEqual(greeks["vega"], 0.15, places=2)
    
    def test_get_underlying_price(self):
        """Test underlying price retrieval."""
        # Mock query result
        mock_df = pd.DataFrame({
            "underlying_price": [5200.50]
        })
        self.mock_client._execute_query.return_value = mock_df
        
        price = self.provider.get_underlying_price(
            ticker="SPX",
            date="2024-03-01",
        )
        
        # Verify price
        self.assertAlmostEqual(price, 5200.50, places=2)
    
    def test_get_underlying_price_missing(self):
        """Test handling of missing underlying price."""
        # Mock empty result
        self.mock_client._execute_query.return_value = pd.DataFrame()
        
        price = self.provider.get_underlying_price(
            ticker="SPX",
            date="2024-03-01",
        )
        
        # Should return None
        self.assertIsNone(price)
    
    def test_datetime_handling(self):
        """Test that both datetime and string inputs work."""
        mock_df = pd.DataFrame({
            "strike": [5200]
        })
        self.mock_client._execute_query.return_value = mock_df
        
        # Test with datetime
        strikes1 = self.provider.get_available_strikes(
            ticker="SPX",
            expiration=datetime(2024, 3, 15),
            as_of_date=datetime(2024, 3, 1),
            option_type="P",
        )
        
        # Test with string
        strikes2 = self.provider.get_available_strikes(
            ticker="SPX",
            expiration="2024-03-15",
            as_of_date="2024-03-01",
            option_type="P",
        )
        
        # Both should work
        self.assertEqual(strikes1, [5200.0])
        self.assertEqual(strikes2, [5200.0])


class TestHybridDataProvider(unittest.TestCase):
    """Test HybridDataProvider routing logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        from backtest.hybrid_data_provider import HybridDataProvider
        
        # Mock IronVault provider
        self.mock_ironvault = MagicMock()
        
        # Mock CBOE provider (it's lazy-loaded inside _get_cboe_provider)
        self.mock_cboe = MagicMock()
        self.cboe_patcher = patch("backtest.cboe_data_provider.CBOEDataProvider", return_value=self.mock_cboe)
        self.cboe_patcher.start()
        
        self.hybrid = HybridDataProvider(
            ironvault_data=self.mock_ironvault,
            cboe_database="cboe",
            cboe_output_bucket="s3://test-bucket/"
        )
    
    def tearDown(self):
        """Clean up patchers."""
        self.cboe_patcher.stop()
    
    def test_spx_routes_to_cboe(self):
        """Test that SPX queries route to CBOE."""
        self.mock_cboe.get_spread_prices.return_value = {"spread_value": 7.30}
        
        result = self.hybrid.get_spread_prices(
            ticker="SPX",
            expiration="2024-03-15",
            short_strike=5200,
            long_strike=5150,
            option_type="P",
            date="2024-03-01",
        )
        
        # CBOE should be called, not IronVault
        self.mock_cboe.get_spread_prices.assert_called_once()
        self.mock_ironvault.get_spread_prices.assert_not_called()
    
    def test_spy_routes_to_ironvault(self):
        """Test that SPY queries route to IronVault."""
        self.mock_ironvault.get_spread_prices.return_value = {"spread_value": 0.50}
        
        result = self.hybrid.get_spread_prices(
            ticker="SPY",
            expiration="2024-03-15",
            short_strike=520,
            long_strike=515,
            option_type="P",
            date="2024-03-01",
        )
        
        # IronVault should be called, not CBOE
        self.mock_ironvault.get_spread_prices.assert_called_once()
    
    def test_greeks_only_for_spx(self):
        """Test that Greeks are only available for SPX."""
        # SPX - should have Greeks
        self.mock_cboe.get_greeks.return_value = {"delta": -0.25}
        
        greeks_spx = self.hybrid.get_greeks(
            ticker="SPX",
            strike=5200,
            option_type="P",
            expiration="2024-03-15",
            date="2024-03-01",
        )
        
        self.assertIsNotNone(greeks_spx)
        self.mock_cboe.get_greeks.assert_called_once()
        
        # SPY - should return None (IronVault doesn't have Greeks)
        # Remove the get_greeks attribute from mock to simulate missing method
        delattr(self.mock_ironvault, 'get_greeks')
        
        greeks_spy = self.hybrid.get_greeks(
            ticker="SPY",
            strike=520,
            option_type="P",
            expiration="2024-03-15",
            date="2024-03-01",
        )
        
        self.assertIsNone(greeks_spy)


if __name__ == "__main__":
    unittest.main()
