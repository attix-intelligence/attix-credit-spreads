"""
Unit tests for GreeksProvider

Tests the CBOE Athena Greeks integration without touching IronVault pricing.
"""
import pytest
import pandas as pd
from unittest.mock import Mock, patch

from compass.greeks_provider import GreeksProvider


class TestGreeksProvider:
    """Test suite for GreeksProvider."""

    @pytest.fixture
    def mock_client(self):
        """Mock CBOEAthenaClient for testing."""
        with patch("compass.greeks_provider.CBOEAthenaClient") as mock:
            yield mock

    @pytest.fixture
    def provider(self, mock_client):
        """Create GreeksProvider with mocked client."""
        return GreeksProvider()

    def test_initialization(self, provider, mock_client):
        """Test GreeksProvider initializes correctly."""
        assert provider.client is not None
        mock_client.assert_called_once()

    def test_get_greeks_single_strike(self, provider, mock_client):
        """Test basic Greeks query for single strike."""
        # Setup mock response
        mock_df = pd.DataFrame({
            "timestamp": pd.date_range("2024-03-01 09:30", periods=3, freq="1h"),
            "bid": [2.50, 2.55, 2.60],
            "ask": [2.52, 2.57, 2.62],
            "delta": [-0.30, -0.31, -0.32],
            "gamma": [0.05, 0.05, 0.05],
            "theta": [-0.10, -0.11, -0.12],
            "vega": [0.20, 0.21, 0.22],
        })
        mock_client.return_value.query_greeks.return_value = mock_df

        # Execute
        result = provider.get_greeks(
            ticker="SPY",
            expiration="2024-03-15",
            strikes=[500.0],
            option_type="P",
            date="2024-03-01"
        )

        # Verify
        assert result is not None
        assert len(result) == 3
        assert "strike" in result.columns
        assert "delta" in result.columns
        assert "gamma" in result.columns
        assert "theta" in result.columns
        assert "vega" in result.columns
        assert result["strike"].iloc[0] == 500.0

    def test_get_greeks_multiple_strikes(self, provider, mock_client):
        """Test Greeks query for multiple strikes."""
        # Setup mock responses
        def mock_query_greeks(**kwargs):
            strike = kwargs["strike"]
            return pd.DataFrame({
                "timestamp": pd.date_range("2024-03-01 09:30", periods=2, freq="1h"),
                "bid": [2.50, 2.55],
                "ask": [2.52, 2.57],
                "delta": [-0.30, -0.31],
                "gamma": [0.05, 0.05],
                "theta": [-0.10, -0.11],
                "vega": [0.20, 0.21],
            })

        mock_client.return_value.query_greeks.side_effect = mock_query_greeks

        # Execute
        result = provider.get_greeks(
            ticker="SPY",
            expiration="2024-03-15",
            strikes=[500.0, 505.0, 510.0],
            option_type="P",
            date="2024-03-01"
        )

        # Verify
        assert result is not None
        assert len(result) == 6  # 2 timestamps × 3 strikes
        assert set(result["strike"].unique()) == {500.0, 505.0, 510.0}
        assert mock_client.return_value.query_greeks.call_count == 3

    def test_get_greeks_empty_result(self, provider, mock_client):
        """Test handling of empty results from Athena."""
        # Setup mock to return empty DataFrame
        mock_client.return_value.query_greeks.return_value = pd.DataFrame()

        # Execute
        result = provider.get_greeks(
            ticker="SPY",
            expiration="2024-03-15",
            strikes=[500.0],
            option_type="P",
            date="2024-03-01"
        )

        # Verify
        assert result is None

    def test_get_greeks_error_handling(self, provider, mock_client):
        """Test graceful error handling when Athena times out."""
        # Setup mock to raise error
        mock_client.return_value.query_greeks.side_effect = TimeoutError(
            "Athena query timed out"
        )

        # Execute - should not raise, should return None
        result = provider.get_greeks(
            ticker="SPY",
            expiration="2024-03-15",
            strikes=[500.0],
            option_type="P",
            date="2024-03-01"
        )

        # Verify
        assert result is None

    def test_get_greeks_partial_failure(self, provider, mock_client):
        """Test handling when some strikes fail but others succeed."""
        # Setup mock to fail on first strike, succeed on others
        def mock_query_greeks(**kwargs):
            strike = kwargs["strike"]
            if strike == 500.0:
                raise RuntimeError("Query failed")
            return pd.DataFrame({
                "timestamp": pd.date_range("2024-03-01 09:30", periods=2, freq="1h"),
                "bid": [2.50, 2.55],
                "ask": [2.52, 2.57],
                "delta": [-0.30, -0.31],
                "gamma": [0.05, 0.05],
                "theta": [-0.10, -0.11],
                "vega": [0.20, 0.21],
            })

        mock_client.return_value.query_greeks.side_effect = mock_query_greeks

        # Execute
        result = provider.get_greeks(
            ticker="SPY",
            expiration="2024-03-15",
            strikes=[500.0, 505.0, 510.0],
            option_type="P",
            date="2024-03-01"
        )

        # Verify - should have data for 505 and 510, but not 500
        assert result is not None
        assert len(result) == 4  # 2 timestamps × 2 strikes
        assert set(result["strike"].unique()) == {505.0, 510.0}

    def test_get_greeks_no_strikes(self, provider, mock_client):
        """Test handling of empty strikes list."""
        result = provider.get_greeks(
            ticker="SPY",
            expiration="2024-03-15",
            strikes=[],
            option_type="P",
            date="2024-03-01"
        )

        assert result is None
        mock_client.return_value.query_greeks.assert_not_called()

    def test_get_greeks_single_strike_convenience(self, provider, mock_client):
        """Test single-strike convenience method."""
        # Setup mock response
        mock_df = pd.DataFrame({
            "timestamp": pd.date_range("2024-03-01 09:30", periods=3, freq="1h"),
            "bid": [2.50, 2.55, 2.60],
            "ask": [2.52, 2.57, 2.62],
            "delta": [-0.30, -0.31, -0.32],
            "gamma": [0.05, 0.05, 0.05],
            "theta": [-0.10, -0.11, -0.12],
            "vega": [0.20, 0.21, 0.22],
        })
        mock_client.return_value.query_greeks.return_value = mock_df

        # Execute convenience method
        result = provider.get_greeks_single_strike(
            ticker="SPY",
            expiration="2024-03-15",
            strike=500.0,
            option_type="P",
            date="2024-03-01"
        )

        # Verify - should not have strike column
        assert result is not None
        assert "strike" not in result.columns
        assert len(result) == 3

    def test_cost_tracking_log(self, provider, mock_client, caplog):
        """Test that cost tracking logs are generated."""
        # Setup mock response
        mock_df = pd.DataFrame({
            "timestamp": pd.date_range("2024-03-01 09:30", periods=2, freq="1h"),
            "bid": [2.50, 2.55],
            "ask": [2.52, 2.57],
            "delta": [-0.30, -0.31],
            "gamma": [0.05, 0.05],
            "theta": [-0.10, -0.11],
            "vega": [0.20, 0.21],
        })
        mock_client.return_value.query_greeks.return_value = mock_df

        # Execute
        with caplog.at_level("INFO"):
            provider.get_greeks(
                ticker="SPY",
                expiration="2024-03-15",
                strikes=[500.0],
                option_type="P",
                date="2024-03-01"
            )

        # Verify logging
        assert "Retrieved Greeks" in caplog.text
        assert "data points" in caplog.text


# Integration test (requires AWS credentials)
@pytest.mark.integration
@pytest.mark.skip(reason="Requires AWS credentials and live CBOE data")
def test_greeks_provider_integration():
    """
    Live integration test against CBOE Athena.
    
    Run with: pytest tests/test_greeks_provider.py -m integration -v
    """
    provider = GreeksProvider()
    
    # Query known good data (SPY 500P on 2024-03-01)
    result = provider.get_greeks(
        ticker="SPY",
        expiration="2024-03-15",
        strikes=[500.0],
        option_type="P",
        date="2024-03-01"
    )
    
    assert result is not None
    assert len(result) > 0
    assert "delta" in result.columns
    assert result["delta"].notna().any()
    
    print(f"✓ Retrieved {len(result)} data points")
    print(result.head())
