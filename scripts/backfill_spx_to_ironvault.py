#!/usr/bin/env python3
"""
Backfill SPX Options Data to IronVault

Downloads historical SPX options data from Polygon and adds to options_cache.db.

Usage:
    python scripts/backfill_spx_to_ironvault.py --start-date 2023-01-01 --end-date 2025-12-31

Options:
    --start-date  Start date (YYYY-MM-DD)
    --end-date    End date (YYYY-MM-DD) 
    --strikes     Strikes to download (default: ATM ±20%)
    --expirations Expirations to download (default: monthlies + weeklies)
    --dry-run     Show what would be downloaded without actually downloading
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import sqlite3
import pandas as pd

# Polygon API key
POLYGON_KEY = os.getenv("POLYGON_API_KEY", "y3y07kPIE0VkS6M3erj7uNsJ3dpLYDCH")
DB_PATH = "data/options_cache.db"

def get_spx_price(date_str: str) -> float:
    """Get SPX index price for a date."""
    url = f"https://api.polygon.io/v2/aggs/ticker/I:SPX/range/1/day/{date_str}/{date_str}"
    params = {"apiKey": POLYGON_KEY}
    
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data.get('results'):
            return data['results'][0]['c']  # closing price
    
    # Fallback: estimate around 5200 for 2024
    return 5200.0

def get_spx_expirations(start_date: str, end_date: str) -> list:
    """Get all SPX option expirations in date range."""
    print(f"Finding SPX expirations between {start_date} and {end_date}...")
    
    url = "https://api.polygon.io/v3/reference/options/contracts"
    params = {
        "underlying_ticker": "SPX",
        "expiration_date.gte": start_date,
        "expiration_date.lte": end_date,
        "limit": 1000,
        "apiKey": POLYGON_KEY
    }
    
    expirations = set()
    
    while True:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"Error fetching expirations: {response.status_code}")
            break
        
        data = response.json()
        results = data.get('results', [])
        
        if not results:
            break
        
        for contract in results:
            expirations.add(contract['expiration_date'])
        
        # Check for next page
        next_url = data.get('next_url')
        if not next_url:
            break
        
        url = next_url
        params = {}  # next_url has params embedded
        time.sleep(0.1)  # Rate limiting
    
    expirations = sorted(list(expirations))
    print(f"Found {len(expirations)} unique expirations")
    
    return expirations

def get_strikes_for_expiration(expiration: str, spx_price: float, width_pct: float = 0.20) -> list:
    """Get strikes within ±width_pct of SPX price for an expiration."""
    url = "https://api.polygon.io/v3/reference/options/contracts"
    params = {
        "underlying_ticker": "SPX",
        "expiration_date": expiration,
        "limit": 1000,
        "apiKey": POLYGON_KEY
    }
    
    response = requests.get(url, params=params)
    if response.status_code != 200:
        return []
    
    data = response.json()
    results = data.get('results', [])
    
    # Filter strikes within range
    min_strike = spx_price * (1 - width_pct)
    max_strike = spx_price * (1 + width_pct)
    
    strikes = set()
    for contract in results:
        strike = contract['strike_price']
        if min_strike <= strike <= max_strike:
            strikes.add(strike)
    
    return sorted(list(strikes))

def download_option_ohlc(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Download OHLC data for an option contract."""
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
    params = {"apiKey": POLYGON_KEY}
    
    response = requests.get(url, params=params)
    if response.status_code != 200:
        return pd.DataFrame()
    
    data = response.json()
    results = data.get('results', [])
    
    if not results:
        return pd.DataFrame()
    
    df = pd.DataFrame(results)
    df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
    df = df.rename(columns={
        'o': 'open',
        'h': 'high', 
        'l': 'low',
        'c': 'close',
        'v': 'volume',
        'n': 'transactions'
    })
    
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

def insert_to_ironvault(ticker: str, expiration: str, strike: float, option_type: str, df: pd.DataFrame):
    """Insert option data into IronVault database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create table if not exists (match IronVault schema)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_data (
            ticker TEXT,
            expiration DATE,
            strike REAL,
            option_type TEXT,
            timestamp TIMESTAMP,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            PRIMARY KEY (ticker, expiration, strike, option_type, timestamp)
        )
    """)
    
    # Insert rows
    for _, row in df.iterrows():
        cursor.execute("""
            INSERT OR REPLACE INTO options_data 
            (ticker, expiration, strike, option_type, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            ticker, expiration, strike, option_type,
            row['timestamp'], row['open'], row['high'], row['low'], row['close'], row['volume']
        ))
    
    conn.commit()
    conn.close()

def backfill_spx(start_date: str, end_date: str, dry_run: bool = False):
    """Main backfill function."""
    print("="*70)
    print("SPX Options Backfill to IronVault")
    print("="*70)
    print(f"Date range: {start_date} to {end_date}")
    print(f"Database: {DB_PATH}")
    print(f"Dry run: {dry_run}")
    print()
    
    # Step 1: Get SPX price for strike selection
    print("Step 1: Getting SPX price for strike selection...")
    spx_price = get_spx_price(start_date)
    print(f"SPX price (reference): {spx_price:.2f}")
    print()
    
    # Step 2: Get all expirations
    print("Step 2: Finding SPX expirations...")
    expirations = get_spx_expirations(start_date, end_date)
    
    if not expirations:
        print("❌ No expirations found!")
        return
    
    print(f"Found {len(expirations)} expirations")
    print(f"First: {expirations[0]}, Last: {expirations[-1]}")
    print()
    
    # Step 3: For each expiration, download strikes
    total_contracts = 0
    total_rows = 0
    
    for i, exp in enumerate(expirations, 1):
        print(f"Processing expiration {i}/{len(expirations)}: {exp}")
        # Get strikes for this expiration
        strikes = get_strikes_for_expiration(exp, spx_price, width_pct=0.15)
        
        if not strikes:
            continue
        
        # Download each strike (call and put)
        for strike in strikes:
            for opt_type in ['call', 'put']:
                # Build Polygon ticker
                strike_str = f"{int(strike * 1000):08d}"
                opt_char = 'C' if opt_type == 'call' else 'P'
                exp_str = exp.replace('-', '')[2:]  # YYMMDD format
                polygon_ticker = f"O:SPX{exp_str}{opt_char}{strike_str}"
                
                if dry_run:
                    total_contracts += 1
                    continue
                
                # Download OHLC
                df = download_option_ohlc(polygon_ticker, start_date, end_date)
                
                if df.empty:
                    continue
                
                # Insert to IronVault
                insert_to_ironvault("SPX", exp, strike, opt_char, df)
                
                total_contracts += 1
                total_rows += len(df)
                
                # Rate limiting
                time.sleep(0.1)
    
    print()
    print("="*70)
    print("BACKFILL COMPLETE")
    print("="*70)
    print(f"Contracts processed: {total_contracts}")
    print(f"Total rows inserted: {total_rows}")
    print()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill SPX options to IronVault")
    parser.add_argument("--start-date", default="2023-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    
    args = parser.parse_args()
    
    backfill_spx(args.start_date, args.end_date, args.dry_run)
