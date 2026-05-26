"""
EXP-3505: SPX 1 DTE Iron Condors

Strategy:
- Entry: 9:45 AM daily
- Exit: Next day at open (1 day hold)
- Strikes: 25Δ put/call
- Frequency: Daily (~250 days/year)
- Test period: 2023-2025

This tests if 1 DTE avoids 0DTE gamma explosion while maintaining high frequency.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

# Add parent dirs to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backtest.cboe_csv_provider import CBOECSVProvider

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SPX1DTEBacktest:
    """Backtest SPX 1 DTE iron condors."""
    
    def __init__(self, start_date: str, end_date: str):
        self.start_date = start_date
        self.end_date = end_date
        
        # Initialize CBOE CSV provider
        cache_dir = Path(__file__).parent.parent.parent / "data" / "cboe_complete" / "spx" / "1dte"
        self.provider = CBOECSVProvider(cache_dir=str(cache_dir))
        
        # Strategy params
        self.target_delta = 0.25
        self.wing_width = 50  # $50 wide spreads
        self.contracts = 1
        
        # Results tracking
        self.trades = []
        self.equity_curve = []
        self.initial_capital = 100000
        self.current_capital = self.initial_capital
    
    def get_trading_days(self) -> list[str]:
        """Get all trading days in the period."""
        start = pd.to_datetime(self.start_date)
        end = pd.to_datetime(self.end_date)
        
        # Generate all weekdays
        dates = pd.bdate_range(start, end)
        
        # Filter to days with data
        trading_days = []
        for date in dates:
            date_str = date.strftime('%Y-%m-%d')
            if self.provider.get_underlying_price('SPX', date_str) is not None:
                trading_days.append(date_str)
        
        return trading_days
    
    def find_strikes_for_delta(self, ticker: str, date: str, dte: int, 
                               target_delta: float) -> tuple[float, float]:
        """
        Find put and call strikes closest to target delta.
        
        Returns:
            (put_strike, call_strike)
        """
        # Get options chain for this DTE
        chain = self.provider.get_options_chain(ticker, date, dte)
        if chain is None or chain.empty:
            return None, None
        
        # Separate puts and calls
        puts = chain[chain['option_type'] == 'put'].copy()
        calls = chain[chain['option_type'] == 'call'].copy()
        
        if puts.empty or calls.empty:
            return None, None
        
        # Find put strike closest to -target_delta
        puts['delta_diff'] = abs(puts['delta'] + target_delta)
        put_strike = puts.loc[puts['delta_diff'].idxmin(), 'strike']
        
        # Find call strike closest to +target_delta
        calls['delta_diff'] = abs(calls['delta'] - target_delta)
        call_strike = calls.loc[calls['delta_diff'].idxmin(), 'strike']
        
        return float(put_strike), float(call_strike)
    
    def get_spread_price(self, ticker: str, date: str, dte: int,
                        short_strike: float, long_strike: float,
                        option_type: str) -> float:
        """
        Get price for a credit spread (short - long).
        
        Returns credit received (positive number).
        """
        chain = self.provider.get_options_chain(ticker, date, dte)
        if chain is None or chain.empty:
            return 0.0
        
        # Filter to this option type
        chain = chain[chain['option_type'] == option_type]
        
        # Get short leg (sell at bid)
        short_data = chain[chain['strike'] == short_strike]
        if short_data.empty:
            return 0.0
        short_price = float(short_data.iloc[0]['bid'])
        
        # Get long leg (buy at ask)
        long_data = chain[chain['strike'] == long_strike]
        if long_data.empty:
            return 0.0
        long_price = float(long_data.iloc[0]['ask'])
        
        # Credit = what we receive - what we pay
        credit = short_price - long_price
        
        return max(0.0, credit)  # Can't be negative
    
    def calculate_pnl(self, ticker: str, entry_date: str, exit_date: str,
                     put_short: float, put_long: float,
                     call_short: float, call_long: float,
                     entry_credit: float) -> tuple[float, str]:
        """
        Calculate P&L for an iron condor.
        
        Returns:
            (pnl, exit_reason)
        """
        # Get exit prices (0 DTE on exit date)
        chain = self.provider.get_options_chain(ticker, exit_date, 0)
        if chain is None or chain.empty:
            # Can't exit - assume max loss
            max_loss = -(self.wing_width - entry_credit) * 100 * self.contracts
            return max_loss, 'no_exit_data'
        
        # Get underlying at exit
        underlying_exit = self.provider.get_underlying_price(ticker, exit_date)
        if underlying_exit is None:
            max_loss = -(self.wing_width - entry_credit) * 100 * self.contracts
            return max_loss, 'no_underlying_exit'
        
        # Calculate intrinsic value at expiration
        # Put spread value (we're short the higher strike)
        put_value = 0.0
        if underlying_exit < put_short:
            # Puts in the money
            put_value = min(put_short - underlying_exit, self.wing_width)
        
        # Call spread value (we're short the lower strike)
        call_value = 0.0
        if underlying_exit > call_short:
            # Calls in the money
            call_value = min(underlying_exit - call_short, self.wing_width)
        
        # Total value we owe at expiration
        total_value = put_value + call_value
        
        # P&L = credit received - value owed
        pnl = (entry_credit - total_value) * 100 * self.contracts
        
        # Determine exit reason
        if put_value > 0 and call_value > 0:
            exit_reason = 'both_breached'
        elif put_value > 0:
            exit_reason = 'put_breached'
        elif call_value > 0:
            exit_reason = 'call_breached'
        else:
            exit_reason = 'expired_otm'
        
        return pnl, exit_reason
    
    def run_backtest(self):
        """Run the backtest."""
        logger.info("=" * 80)
        logger.info("SPX 1 DTE IRON CONDOR BACKTEST")
        logger.info("=" * 80)
        logger.info(f"Period: {self.start_date} to {self.end_date}")
        logger.info(f"Target Delta: {self.target_delta}")
        logger.info(f"Wing Width: ${self.wing_width}")
        logger.info(f"Initial Capital: ${self.initial_capital:,.0f}")
        logger.info("")
        
        # Get trading days
        trading_days = self.get_trading_days()
        logger.info(f"Found {len(trading_days)} trading days")
        logger.info("")
        
        # Track progress
        total_days = len(trading_days)
        
        # Backtest each day
        for i, entry_date in enumerate(trading_days[:-1], 1):  # Skip last day (need next day for exit)
            # Get next trading day for exit
            exit_date = trading_days[i] if i < len(trading_days) else None
            if exit_date is None:
                continue
            
            # Progress
            if i % 50 == 0:
                logger.info(f"Processing day {i}/{total_days-1}: {entry_date}")
            
            # Get underlying price
            underlying = self.provider.get_underlying_price('SPX', entry_date)
            if underlying is None:
                continue
            
            # Find strikes (1 DTE on entry)
            put_strike, call_strike = self.find_strikes_for_delta('SPX', entry_date, 1, self.target_delta)
            if put_strike is None or call_strike is None:
                continue
            
            # Build iron condor
            put_long = put_strike - self.wing_width
            call_long = call_strike + self.wing_width
            
            # Get entry credits
            put_credit = self.get_spread_price('SPX', entry_date, 1, put_strike, put_long, 'put')
            call_credit = self.get_spread_price('SPX', entry_date, 1, call_strike, call_long, 'call')
            total_credit = put_credit + call_credit
            
            if total_credit <= 0:
                continue
            
            # Calculate P&L at exit
            pnl, exit_reason = self.calculate_pnl(
                'SPX', entry_date, exit_date,
                put_strike, put_long, call_strike, call_long, total_credit
            )
            
            # Update capital
            self.current_capital += pnl
            
            # Record trade
            trade = {
                'entry_date': entry_date,
                'exit_date': exit_date,
                'dte': 1,
                'underlying': underlying,
                'put_short': put_strike,
                'put_long': put_long,
                'call_short': call_strike,
                'call_long': call_long,
                'credit': total_credit,
                'pnl': pnl,
                'capital': self.current_capital,
                'exit_reason': exit_reason
            }
            self.trades.append(trade)
            
            # Record equity point
            self.equity_curve.append({
                'date': exit_date,
                'capital': self.current_capital
            })
        
        logger.info("")
        logger.info("Backtest complete!")
        logger.info(f"Total trades: {len(self.trades)}")
        
        return self.analyze_results()
    
    def analyze_results(self) -> dict:
        """Analyze backtest results."""
        if not self.trades:
            return {'error': 'No trades executed'}
        
        df = pd.DataFrame(self.trades)
        
        # Basic stats
        total_pnl = df['pnl'].sum()
        total_return = (self.current_capital / self.initial_capital - 1) * 100
        
        # Win rate
        wins = df[df['pnl'] > 0]
        losses = df[df['pnl'] < 0]
        win_rate = len(wins) / len(df) * 100
        
        # Average trade
        avg_win = wins['pnl'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl'].mean() if len(losses) > 0 else 0
        avg_trade = df['pnl'].mean()
        
        # Drawdown
        equity = pd.DataFrame(self.equity_curve)
        equity['peak'] = equity['capital'].cummax()
        equity['drawdown'] = (equity['capital'] - equity['peak']) / equity['peak'] * 100
        max_drawdown = equity['drawdown'].min()
        
        # Monthly returns
        df['month'] = pd.to_datetime(df['exit_date']).dt.to_period('M')
        monthly = df.groupby('month')['pnl'].sum()
        
        # Annualized metrics
        years = (pd.to_datetime(self.end_date) - pd.to_datetime(self.start_date)).days / 365.25
        annual_return = (((self.current_capital / self.initial_capital) ** (1/years)) - 1) * 100
        
        # Sharpe
        monthly_returns = monthly / self.initial_capital * 100
        sharpe = (monthly_returns.mean() / monthly_returns.std() * np.sqrt(12)) if len(monthly_returns) > 1 else 0
        
        results = {
            'total_trades': len(df),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_return_pct': total_return,
            'annual_return_pct': annual_return,
            'avg_trade': avg_trade,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_drawdown_pct': max_drawdown,
            'sharpe_ratio': sharpe,
            'final_capital': self.current_capital,
            'avg_monthly_return_pct': monthly_returns.mean(),
            'trades_per_year': len(df) / years
        }
        
        # Print results
        logger.info("")
        logger.info("=" * 80)
        logger.info("BACKTEST RESULTS - SPX 1 DTE IRON CONDORS")
        logger.info("=" * 80)
        logger.info(f"Total Trades:      {results['total_trades']}")
        logger.info(f"Win Rate:          {results['win_rate']:.1f}%")
        logger.info(f"")
        logger.info(f"Total P&L:         ${results['total_pnl']:,.0f}")
        logger.info(f"Total Return:      {results['total_return_pct']:.1f}%")
        logger.info(f"Annual Return:     {results['annual_return_pct']:.1f}%")
        logger.info(f"")
        logger.info(f"Avg Trade:         ${results['avg_trade']:,.0f}")
        logger.info(f"Avg Win:           ${results['avg_win']:,.0f}")
        logger.info(f"Avg Loss:          ${results['avg_loss']:,.0f}")
        logger.info(f"")
        logger.info(f"Max Drawdown:      {results['max_drawdown_pct']:.1f}%")
        logger.info(f"Sharpe Ratio:      {results['sharpe_ratio']:.2f}")
        logger.info(f"")
        logger.info(f"Avg Monthly Return: {results['avg_monthly_return_pct']:.1f}%")
        logger.info(f"Trades/Year:       {results['trades_per_year']:.0f}")
        logger.info(f"")
        logger.info(f"Final Capital:     ${results['final_capital']:,.0f}")
        logger.info("=" * 80)
        
        return results


def main():
    """Run 1 DTE backtest."""
    # Test period: 2023-2025
    backtest = SPX1DTEBacktest(
        start_date='2023-01-01',
        end_date='2024-12-31'
    )
    
    results = backtest.run_backtest()
    
    # Save results
    output_dir = Path(__file__).parent
    
    # Save trades
    if backtest.trades:
        trades_df = pd.DataFrame(backtest.trades)
        trades_df.to_csv(output_dir / '1dte_trades.csv', index=False)
        logger.info(f"Saved trades to {output_dir / '1dte_trades.csv'}")
    
    # Save equity curve
    if backtest.equity_curve:
        equity_df = pd.DataFrame(backtest.equity_curve)
        equity_df.to_csv(output_dir / '1dte_equity.csv', index=False)
        logger.info(f"Saved equity curve to {output_dir / '1dte_equity.csv'}")
    
    # Save summary
    import json
    with open(output_dir / '1dte_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"Saved results to {output_dir / '1dte_results.json'}")


if __name__ == '__main__':
    main()
