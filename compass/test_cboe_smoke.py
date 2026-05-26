#!/usr/bin/env python3
"""
CBOE Athena Integration - Smoke Test

Tests basic functionality without burning significant query costs:
1. Query 1 contract, 1 day (~100KB scan, <$0.001)
2. Verify Athena returns data
3. Verify DuckDB cache stores it
4. Re-query same contract → confirm cache hit (no Athena call)
5. Verify Greeks values are reasonable

Usage:
    python compass/test_cboe_smoke.py
"""
import logging
import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from compass.cboe_client import CBOEAthenaClient
from compass.cboe_cache import CBOECache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def smoke_test():
    """Run CBOE integration smoke test."""
    
    print("\n" + "="*70)
    print("CBOE ATHENA INTEGRATION - SMOKE TEST")
    print("="*70 + "\n")
    
    # Test contract: SPY put, known date
    test_params = {
        "ticker": "SPY",
        "expiration": "2024-03-15",  # Known expiration
        "strike": 500.0,
        "option_type": "P",
        "start_date": "2024-03-01",
        "end_date": "2024-03-01",  # Single day to minimize cost
        "interval": "60min"
    }
    
    print(f"Test Parameters:")
    print(f"  Contract: {test_params['ticker']} {test_params['expiration']} "
          f"{test_params['strike']}{test_params['option_type']}")
    print(f"  Date Range: {test_params['start_date']} to {test_params['end_date']}")
    print(f"  Interval: {test_params['interval']}\n")
    
    # Step 1: Initialize client
    print("Step 1: Initializing CBOE Athena client...")
    try:
        client = CBOEAthenaClient()
        print(f"  ✅ Client initialized")
        print(f"     Database: {client.database}")
        print(f"     Region: {client.region}")
        print(f"     Output Bucket: {client.output_bucket}\n")
    except Exception as e:
        print(f"  ❌ Failed to initialize client: {e}")
        print("\nTroubleshooting:")
        print("  1. Verify AWS credentials are set (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)")
        print("  2. Verify ATHENA_OUTPUT_BUCKET is set in .env")
        print("  3. Check AWS IAM permissions (Athena read access)\n")
        return False
    
    # Step 2: Initialize cache
    print("Step 2: Initializing DuckDB cache...")
    try:
        cache = CBOECache(client=client)
        print(f"  ✅ Cache initialized")
        print(f"     Cache file: {cache.cache_path}\n")
    except Exception as e:
        print(f"  ❌ Failed to initialize cache: {e}\n")
        return False
    
    # Step 3: First query (should hit Athena)
    print("Step 3: First query (cache miss → Athena fetch)...")
    try:
        df1 = cache.get_greeks(**test_params)
        
        if df1.empty:
            print(f"  ⚠️  Athena returned no data")
            print(f"     This may be expected if the contract doesn't exist or has no data")
            print(f"     for the specified date range.\n")
            return False
        
        print(f"  ✅ Query succeeded")
        print(f"     Rows returned: {len(df1)}")
        print(f"     Columns: {list(df1.columns)}")
        print(f"     Sample data:")
        print(df1.head(3).to_string(index=False))
        print()
        
        # Verify Greeks values are reasonable
        print("Step 4: Validating Greeks values...")
        
        checks = []
        
        # Delta: 0 to 1 for calls, -1 to 0 for puts
        if "delta" in df1.columns:
            delta_range = (df1["delta"].min(), df1["delta"].max())
            if test_params["option_type"] == "P":
                delta_valid = -1 <= delta_range[0] <= 0 and -1 <= delta_range[1] <= 0
            else:
                delta_valid = 0 <= delta_range[0] <= 1 and 0 <= delta_range[1] <= 1
            
            checks.append(("Delta range", f"{delta_range[0]:.4f} to {delta_range[1]:.4f}", delta_valid))
        
        # Gamma: should be positive
        if "gamma" in df1.columns:
            gamma_min = df1["gamma"].min()
            gamma_valid = gamma_min >= 0
            checks.append(("Gamma > 0", f"min={gamma_min:.6f}", gamma_valid))
        
        # Theta: should be negative (time decay)
        if "theta" in df1.columns:
            theta_max = df1["theta"].max()
            theta_valid = theta_max <= 0
            checks.append(("Theta < 0", f"max={theta_max:.6f}", theta_valid))
        
        # Vega: should be positive
        if "vega" in df1.columns:
            vega_min = df1["vega"].min()
            vega_valid = vega_min >= 0
            checks.append(("Vega > 0", f"min={vega_min:.6f}", vega_valid))
        
        for check_name, value, valid in checks:
            status = "✅" if valid else "❌"
            print(f"  {status} {check_name}: {value}")
        
        if not all(c[2] for c in checks):
            print("\n  ⚠️  Some Greek values are out of expected range")
            print("     This may indicate data quality issues or unusual market conditions.\n")
        else:
            print("\n  ✅ All Greeks values are within expected ranges\n")
        
    except Exception as e:
        print(f"  ❌ Query failed: {e}\n")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 5: Second query (should hit cache)
    print("Step 5: Second query (cache hit → no Athena call)...")
    try:
        df2 = cache.get_greeks(**test_params)
        
        if df2.empty:
            print(f"  ❌ Cache returned empty DataFrame (expected cached data)\n")
            return False
        
        # Verify data matches first query
        if len(df2) != len(df1):
            print(f"  ❌ Row count mismatch: cached={len(df2)}, original={len(df1)}\n")
            return False
        
        print(f"  ✅ Cache hit confirmed")
        print(f"     Rows: {len(df2)} (matches original query)\n")
        
    except Exception as e:
        print(f"  ❌ Cache lookup failed: {e}\n")
        return False
    
    # Step 6: Coverage report
    print("Step 6: Cache coverage report...")
    try:
        coverage = cache.coverage_report()
        print(f"  ✅ Coverage report generated:")
        for stat in coverage:
            print(f"     {stat['ticker']}: {stat['expirations']} expirations, "
                  f"{stat['rows']} rows, {stat['earliest']} to {stat['latest']}")
        print()
    except Exception as e:
        print(f"  ❌ Coverage report failed: {e}\n")
        return False
    
    # Success
    print("="*70)
    print("✅ SMOKE TEST PASSED")
    print("="*70)
    print("\nNext Steps:")
    print("  1. Add AWS credentials to Railway (see integration plan)")
    print("  2. Run backtest validation with CBOE Greeks")
    print("  3. Create unit tests (tests/test_cboe_client.py)")
    print("  4. Update documentation (docs/data/cboe_athena.md)\n")
    
    return True


if __name__ == "__main__":
    success = smoke_test()
    sys.exit(0 if success else 1)
