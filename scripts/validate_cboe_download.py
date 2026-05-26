#!/usr/bin/env python3
"""
Validate CBOE Complete Download

Checks:
1. Coverage matrix (which ticker/DTE/months have data)
2. Data quality (NULL values, valid timestamps, Greeks in range)
3. File integrity (can read all files)
4. Statistics (total rows, size, date range)
"""
import gzip
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd


def validate_download(data_dir="data/cboe_complete"):
    """Validate complete CBOE download."""
    data_path = Path(data_dir)
    
    print("🔍 CBOE Download Validation")
    print("=" * 60)
    print()
    
    # Find all CSV files
    csv_files = list(data_path.rglob("*.csv.gz"))
    
    if not csv_files:
        print("❌ No data files found!")
        return
    
    print(f"✅ Found {len(csv_files)} data files")
    print()
    
    # Parse coverage
    coverage = defaultdict(lambda: defaultdict(set))  # ticker -> dte -> {months}
    total_rows = 0
    total_size = 0
    failed_files = []
    
    print("📊 Scanning files...")
    for csv_file in csv_files:
        # Parse path: data/cboe_complete/{ticker}/{dte}/{YYYY-MM}.csv.gz
        parts = csv_file.parts
        ticker = parts[-3]  # e.g., "spx"
        dte = parts[-2]  # e.g., "0dte"
        month = parts[-1].replace(".csv.gz", "").replace(".csv", "")  # e.g., "2024-01"
        
        coverage[ticker][dte].add(month)
        total_size += csv_file.stat().st_size
        
        # Check if file is readable
        try:
            with gzip.open(csv_file, 'rt') as f:
                df = pd.read_csv(f, nrows=1)
            
            # Count rows (without loading entire file)
            with gzip.open(csv_file, 'rt') as f:
                rows = sum(1 for _ in f) - 1  # Subtract header
            total_rows += rows
        
        except Exception as e:
            failed_files.append((csv_file, str(e)))
    
    print(f"✅ Scanned {len(csv_files)} files")
    print()
    
    # Summary
    print("📈 Summary Statistics")
    print("-" * 60)
    print(f"Total files: {len(csv_files):,}")
    print(f"Total rows: {total_rows:,}")
    print(f"Total size: {total_size / 1e6:.1f} MB (compressed)")
    print(f"Failed files: {len(failed_files)}")
    print()
    
    # Coverage matrix
    print("📋 Coverage Matrix")
    print("-" * 60)
    
    all_dtes = ["0dte", "1dte", "2dte", "3dte", "5dte", "7dte", "14dte", "30dte"]
    all_tickers = sorted(coverage.keys())
    
    for ticker in all_tickers:
        print(f"\n{ticker.upper()}:")
        for dte in all_dtes:
            months = sorted(coverage[ticker].get(dte, set()))
            count = len(months)
            expected = 72  # 2020-01 to 2025-12
            pct = 100 * count / expected if expected > 0 else 0
            
            if count == 0:
                status = "❌"
            elif count < expected:
                status = "⚠️ "
            else:
                status = "✅"
            
            print(f"  {status} {dte:6s}: {count:2d}/72 months ({pct:5.1f}%)")
            
            # Show gaps if incomplete
            if 0 < count < expected:
                all_months = {f"{y:04d}-{m:02d}" for y in range(2020, 2026) for m in range(1, 13) if not (y == 2025 and m > 12)}
                gaps = all_months - set(months)
                if len(gaps) <= 10:
                    print(f"       Missing: {', '.join(sorted(gaps))}")
                else:
                    print(f"       Missing {len(gaps)} months: {', '.join(sorted(gaps)[:5])} ...")
    
    print()
    
    # Failed files
    if failed_files:
        print("❌ Failed Files")
        print("-" * 60)
        for file, error in failed_files:
            print(f"  {file}: {error}")
        print()
    
    # Data quality spot check
    print("🔬 Data Quality Spot Check (5 random files)")
    print("-" * 60)
    
    import random
    sample_files = random.sample(csv_files, min(5, len(csv_files)))
    
    for csv_file in sample_files:
        try:
            df = pd.read_csv(csv_file, compression="gzip")
            
            # Check for NULL values
            null_counts = df.isnull().sum()
            has_nulls = null_counts[null_counts > 0]
            
            # Check Greeks range (should be -1 to 1 for delta, etc.)
            greeks = ["delta", "gamma", "theta", "vega"]
            greek_issues = []
            for g in greeks:
                if g in df.columns:
                    if df[g].min() < -10 or df[g].max() > 10:
                        greek_issues.append(f"{g} out of range")
            
            # Check timestamp validity
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                invalid_ts = df["timestamp"].isnull().sum()
            else:
                invalid_ts = 0
            
            status = "✅" if len(has_nulls) == 0 and len(greek_issues) == 0 and invalid_ts == 0 else "⚠️ "
            
            print(f"{status} {csv_file.name}: {len(df):,} rows")
            if len(has_nulls) > 0:
                print(f"     NULL values: {dict(has_nulls)}")
            if len(greek_issues) > 0:
                print(f"     Greek issues: {', '.join(greek_issues)}")
            if invalid_ts > 0:
                print(f"     Invalid timestamps: {invalid_ts}")
        
        except Exception as e:
            print(f"❌ {csv_file.name}: {e}")
    
    print()
    print("✅ Validation complete!")
    print()
    
    # Generate JSON catalog
    catalog = {
        "generated": datetime.now().isoformat(),
        "total_files": len(csv_files),
        "total_rows": total_rows,
        "total_size_mb": total_size / 1e6,
        "coverage": {
            ticker: {
                dte: sorted(list(months))
                for dte, months in dtes.items()
            }
            for ticker, dtes in coverage.items()
        },
        "failed_files": [str(f) for f, _ in failed_files],
    }
    
    catalog_path = Path(data_dir).parent / "cboe_download_catalog.json"
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)
    
    print(f"📝 Catalog saved: {catalog_path}")


if __name__ == "__main__":
    validate_download()
