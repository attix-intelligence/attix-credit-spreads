#!/usr/bin/env python3
"""
EXP-3501: SPX 0DTE 20Δ Aggressive - LOCAL DATA VERSION

Reads data directly from local CSV files instead of Athena.
MUCH faster: minutes instead of hours.
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

START_DATE = "2021-02-01"
END_DATE = "2024-12-31"
INITIAL_CAPITAL = 100_000
CONTRACTS_PER_TRADE = 10

ENTRY_TIME = time(10, 0)  # 10:00 AM ET (better liquidity)
EXIT_TIME = time(15, 0)   # 3:00 PM ET

TARGET_DELTA_PUT = 0.20   # 20Δ put side (aggressive)
TARGET_DELTA_CALL = 0.20  # 20Δ call side (aggressive)
WING_WIDTH = 50           # $50 wings

PROFIT_TARGET = 0.50      # 50% of credit
STOP_LOSS = 2.00          # 200% of credit (lose double)

# Liquidity filters
MIN_BID = 0.05
MIN_ASK = 0.10

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "cboe_complete" / "spx" / "0dte"

# ============================================================
# Helper Functions
# ============================================================

def load_day_data(date: datetime) -> pd.DataFrame:
    """Load CBOE data for a specific date from CSV files."""
    # Note: Files have .csv.csv.gz extension (data pipeline issue)
    month_file = DATA_DIR / f"{date.year}-{date.month:02d}.csv.csv.gz"
    
    if not month_file.exists():
        logger.debug(f"No data file for {date.date()}: {month_file}")
        return pd.DataFrame()
    
    # Load full month
    df = pd.read_csv(month_file, compression='gzip')
    
    # Parse timestamps
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Filter to this date and expiration
    date_str = date.strftime("%Y-%m-%d")
    df = df[
        (df['timestamp'].dt.date == date.date()) & 
        (df['expiration'] == date_str)
    ].copy()
    
    if df.empty:
        return df
    
    return df

def find_strike_by_delta(df: pd.DataFrame, entry_time: time, option_type: str, target_delta: float) -> dict:
    """
    Find the strike closest to target delta at entry time.
    
    Returns dict with: strike, delta, bid, ask, mid
    """
    # Data is hourly, so match exact hour
    entry_dt = datetime.combine(df['timestamp'].iloc[0].date(), entry_time)
    df_entry = df[
        (df['timestamp'] == entry_dt) &
        (df['option_type'] == option_type)
    ].copy()
    
    if df_entry.empty:
        return None
    
    # Use bid_close and ask_close for pricing
    df_entry['bid'] = df_entry['bid_close']
    df_entry['ask'] = df_entry['ask_close']
    
    # Filter for liquidity
    df_entry = df_entry[
        (df_entry['bid'] >= MIN_BID) &
        (df_entry['ask'] >= MIN_ASK)
    ]
    
    if df_entry.empty:
        return None
    
    # For puts: target negative delta (-0.20), find closest
    # For calls: target positive delta (+0.20), find closest
    if option_type == 'P':
        target = -target_delta
    else:
        target = target_delta
    
    df_entry['delta_diff'] = np.abs(df_entry['delta'] - target)
    best = df_entry.nsmallest(1, 'delta_diff').iloc[0]
    
    return {
        'strike': best['strike'],
        'delta': best['delta'],
        'bid': best['bid'],
        'ask': best['ask'],
        'mid': (best['bid'] + best['ask']) / 2
    }

def get_strike_price(df: pd.DataFrame, strike: float, option_type: str, target_time: time) -> dict:
    """Get bid/ask/mid for a specific strike at target time."""
    target_dt = datetime.combine(df['timestamp'].iloc[0].date(), target_time)
    
    df_strike = df[
        (df['timestamp'] == target_dt) &
        (df['strike'] == strike) &
        (df['option_type'] == option_type)
    ].copy()
    
    if df_strike.empty:
        return None
    
    row = df_strike.iloc[0]
    return {
        'bid': row['bid_close'],
        'ask': row['ask_close'],
        'mid': (row['bid_close'] + row['ask_close']) / 2
    }

# ============================================================
# Backtest
# ============================================================

def run_backtest():
    """Run the full backtest."""
    
    logger.info("=" * 60)
    logger.info("EXP-3501: SPX 0DTE 20Δ Aggressive - LOCAL DATA")
    logger.info(f"Period: {START_DATE} to {END_DATE}")
    logger.info(f"Initial capital: ${INITIAL_CAPITAL:,.0f}")
    logger.info(f"Contracts per trade: {CONTRACTS_PER_TRADE}")
    logger.info(f"Target delta: {TARGET_DELTA_PUT}Δ (more aggressive than 30Δ baseline)")
    logger.info("=" * 60)
    
    # Generate trading days (Mon/Wed/Fri)
    start = pd.to_datetime(START_DATE)
    end = pd.to_datetime(END_DATE)
    all_days = pd.date_range(start, end, freq='D')
    trading_days = [d for d in all_days if d.dayofweek in [0, 2, 4]]  # Mon, Wed, Fri
    
    logger.info(f"Total trading days: {len(trading_days)}")
    
    results = []
    capital = INITIAL_CAPITAL
    
    for i, date in enumerate(trading_days, 1):
        if i % 50 == 0 or i <= 5:
            logger.info(f"Progress: {i}/{len(trading_days)} days ({i/len(trading_days)*100:.1f}%)")
        
        # Load data
        df = load_day_data(date)
        
        if df.empty:
            logger.debug(f"No data for {date.date()}")
            continue
        
        underlying = df['underlying_price'].iloc[0]
        
        # Find 20Δ strikes
        put_short = find_strike_by_delta(df, ENTRY_TIME, 'P', TARGET_DELTA_PUT)
        call_short = find_strike_by_delta(df, ENTRY_TIME, 'C', TARGET_DELTA_CALL)
        
        if not put_short or not call_short:
            logger.debug(f"Could not find liquid 20Δ strikes on {date.date()}")
            continue
        
        # Calculate wing strikes
        put_long_strike = put_short['strike'] - WING_WIDTH
        call_long_strike = call_short['strike'] + WING_WIDTH
        
        # Get wing prices
        put_long = get_strike_price(df, put_long_strike, 'P', ENTRY_TIME)
        call_long = get_strike_price(df, call_long_strike, 'C', ENTRY_TIME)
        
        if not put_long or not call_long:
            logger.debug(f"Could not price wings on {date.date()}")
            continue
        
        # Entry: Sell short strikes, buy long strikes
        entry_credit = (
            (put_short['mid'] - put_long['mid']) +  # Put spread
            (call_short['mid'] - call_long['mid'])   # Call spread
        ) * 100 * CONTRACTS_PER_TRADE
        
        if entry_credit <= 0:
            logger.debug(f"Zero or negative credit on {date.date()}")
            continue
        
        # Exit at 3 PM
        put_short_exit = get_strike_price(df, put_short['strike'], 'P', EXIT_TIME)
        call_short_exit = get_strike_price(df, call_short['strike'], 'C', EXIT_TIME)
        put_long_exit = get_strike_price(df, put_long_strike, 'P', EXIT_TIME)
        call_long_exit = get_strike_price(df, call_long_strike, 'C', EXIT_TIME)
        
        if not all([put_short_exit, call_short_exit, put_long_exit, call_long_exit]):
            logger.debug(f"Could not price exit on {date.date()}")
            continue
        
        # Exit: Buy back short strikes, sell long strikes
        exit_debit = (
            (put_short_exit['mid'] - put_long_exit['mid']) +
            (call_short_exit['mid'] - call_long_exit['mid'])
        ) * 100 * CONTRACTS_PER_TRADE
        
        pnl = entry_credit - exit_debit
        pnl_pct = (pnl / entry_credit) * 100 if entry_credit > 0 else 0
        
        capital += pnl
        
        results.append({
            'date': date.date(),
            'underlying': underlying,
            'put_short_strike': put_short['strike'],
            'put_short_delta': put_short['delta'],
            'call_short_strike': call_short['strike'],
            'call_short_delta': call_short['delta'],
            'entry_credit': entry_credit,
            'exit_debit': exit_debit,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'capital': capital
        })
        
        if i <= 5:
            logger.info(f"  {date.date()}: SPX ${underlying:.2f} | "
                       f"Strikes {put_short['strike']}/{call_short['strike']} | "
                       f"Credit ${entry_credit:.2f} | P&L ${pnl:.2f} ({pnl_pct:+.1f}%) | "
                       f"Capital ${capital:,.0f}")
    
    # ============================================================
    # Results Analysis
    # ============================================================
    
    if not results:
        logger.error("❌ No trades executed!")
        return None
    
    df_results = pd.DataFrame(results)
    
    total_trades = len(df_results)
    winners = (df_results['pnl'] > 0).sum()
    losers = (df_results['pnl'] < 0).sum()
    win_rate = winners / total_trades
    
    total_pnl = df_results['pnl'].sum()
    final_capital = INITIAL_CAPITAL + total_pnl
    total_return = (final_capital / INITIAL_CAPITAL - 1) * 100
    
    avg_win = df_results[df_results['pnl'] > 0]['pnl'].mean() if winners > 0 else 0
    avg_loss = df_results[df_results['pnl'] < 0]['pnl'].mean() if losers > 0 else 0
    
    # Equity curve stats
    df_results['equity'] = INITIAL_CAPITAL + df_results['pnl'].cumsum()
    peak = df_results['equity'].cummax()
    drawdown = (df_results['equity'] - peak) / peak * 100
    max_dd = drawdown.min()
    
    # Sharpe ratio (annualized)
    daily_returns = df_results['pnl'] / INITIAL_CAPITAL
    sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0
    
    # Monthly performance
    df_results['month'] = pd.to_datetime(df_results['date']).dt.to_period('M')
    monthly = df_results.groupby('month')['pnl'].sum()
    monthly_return_pct = (monthly / INITIAL_CAPITAL * 100).mean()
    
    # Years of data
    years = (df_results['date'].max() - df_results['date'].min()).days / 365.25
    
    # Print results
    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ BACKTEST RESULTS - EXP-3501 (20Δ Aggressive)")
    logger.info("=" * 60)
    logger.info(f"Period: {df_results['date'].min()} to {df_results['date'].max()}")
    logger.info(f"Duration: {years:.1f} years")
    logger.info(f"Total trades: {total_trades}")
    logger.info(f"Winners: {winners} ({win_rate*100:.1f}%)")
    logger.info(f"Losers: {losers} ({(1-win_rate)*100:.1f}%)")
    logger.info(f"")
    logger.info(f"Initial capital: ${INITIAL_CAPITAL:,.0f}")
    logger.info(f"Final capital: ${final_capital:,.0f}")
    logger.info(f"Total P&L: ${total_pnl:,.0f}")
    logger.info(f"Total return: {total_return:+.1f}%")
    logger.info(f"Annualized return: {(total_return/years):+.1f}%")
    logger.info(f"")
    logger.info(f"Avg win: ${avg_win:,.0f}")
    logger.info(f"Avg loss: ${avg_loss:,.0f}")
    logger.info(f"Win/Loss ratio: {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "N/A")
    logger.info(f"")
    logger.info(f"Max drawdown: {max_dd:.2f}%")
    logger.info(f"Sharpe ratio: {sharpe:.2f}")
    logger.info(f"Avg monthly return: {monthly_return_pct:.2f}%")
    logger.info("=" * 60)
    
    # Save results
    csv_path = Path(__file__).parent / "results" / "exp3501_local_results.csv"
    csv_path.parent.mkdir(exist_ok=True)
    df_results.to_csv(csv_path, index=False)
    logger.info(f"💾 Saved results to: {csv_path}")
    
    return df_results

if __name__ == "__main__":
    results = run_backtest()
