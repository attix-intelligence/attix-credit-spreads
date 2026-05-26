"""
EXP-3505: Master runner for all 1-3 DTE backtests.

Runs all three variants and generates comparison report.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_backtest(script_name: str) -> dict:
    """Run a backtest script and return results."""
    logger.info("")
    logger.info("=" * 80)
    logger.info(f"Running {script_name}")
    logger.info("=" * 80)
    
    script_path = Path(__file__).parent / script_name
    
    try:
        # Run the backtest
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Print output
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        # Load results
        dte = script_name.split('_')[1].replace('dte.py', '')
        results_file = Path(__file__).parent / f'{dte}dte_results.json'
        
        if results_file.exists():
            with open(results_file, 'r') as f:
                return json.load(f)
        else:
            logger.error(f"Results file not found: {results_file}")
            return {'error': 'Results file not found'}
    
    except subprocess.CalledProcessError as e:
        logger.error(f"Backtest failed: {e}")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        return {'error': str(e)}
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return {'error': str(e)}


def generate_comparison_report(results_1dte: dict, results_2dte: dict, results_3dte: dict):
    """Generate HTML comparison report."""
    
    # Build comparison table
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>EXP-3505: SPX 1-3 DTE Iron Condor Comparison</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 40px auto;
            padding: 20px;
            background: white;
        }
        h1 {
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }
        h2 {
            color: #34495e;
            margin-top: 30px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            border: 1px solid #ddd;
            padding: 12px;
            text-align: right;
        }
        th {
            background-color: #3498db;
            color: white;
            font-weight: bold;
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        .metric {
            text-align: left;
            font-weight: bold;
        }
        .winner {
            background-color: #d5f4e6 !important;
            font-weight: bold;
        }
        .loser {
            background-color: #fadbd8 !important;
        }
        .summary {
            background-color: #eaf2f8;
            padding: 20px;
            border-radius: 5px;
            margin: 20px 0;
        }
        .success {
            color: #27ae60;
            font-weight: bold;
        }
        .failure {
            color: #e74c3c;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <h1>EXP-3505: SPX 1-3 DTE Iron Condor Backtest Results</h1>
    
    <div class="summary">
        <h2>Objective</h2>
        <p><strong>Test if 1-3 DTE avoids 0DTE gamma explosion while maintaining profitability</strong></p>
        <p>0DTE failed with -25% to -107% returns. These longer DTEs should provide:</p>
        <ul>
            <li>More time for mean reversion</li>
            <li>Lower gamma risk (less explosive moves)</li>
            <li>Better liquidity</li>
        </ul>
        <p><strong>Success Criteria:</strong></p>
        <ul>
            <li>✅ Positive returns (unlike 0DTE)</li>
            <li>✅ Sharpe > 1.5</li>
            <li>✅ Win rate > 70%</li>
            <li>✅ Monthly return > 15%</li>
        </ul>
    </div>
    
    <h2>Performance Comparison</h2>
    <table>
        <tr>
            <th class="metric">Metric</th>
            <th>1 DTE<br>(Daily)</th>
            <th>2 DTE<br>(Every Other Day)</th>
            <th>3 DTE<br>(3-Day Hold)</th>
        </tr>
"""
    
    # Helper to format values
    def fmt_pct(val):
        if val is None or 'error' in str(val):
            return 'ERROR'
        return f"{val:.1f}%"
    
    def fmt_num(val):
        if val is None or 'error' in str(val):
            return 'ERROR'
        return f"{val:,.0f}"
    
    def fmt_ratio(val):
        if val is None or 'error' in str(val):
            return 'ERROR'
        return f"{val:.2f}"
    
    # Determine winners for each metric
    def get_class(values, idx, higher_is_better=True):
        try:
            vals = [float(v) if v is not None else -999999 for v in values]
            if higher_is_better:
                if vals[idx] == max(vals):
                    return 'winner'
                elif vals[idx] == min(vals):
                    return 'loser'
            else:
                if vals[idx] == min(vals):
                    return 'winner'
                elif vals[idx] == max(vals):
                    return 'loser'
        except:
            pass
        return ''
    
    # Build comparison rows
    metrics = [
        ('Total Trades', 'total_trades', fmt_num, False),
        ('Win Rate', 'win_rate', fmt_pct, True),
        ('Total Return', 'total_return_pct', fmt_pct, True),
        ('Annual Return', 'annual_return_pct', fmt_pct, True),
        ('Avg Monthly Return', 'avg_monthly_return_pct', fmt_pct, True),
        ('Avg Trade P&L', 'avg_trade', fmt_num, True),
        ('Avg Win', 'avg_win', fmt_num, True),
        ('Avg Loss', 'avg_loss', fmt_num, False),  # Lower is better (less negative)
        ('Max Drawdown', 'max_drawdown_pct', fmt_pct, False),  # Lower is better
        ('Sharpe Ratio', 'sharpe_ratio', fmt_ratio, True),
        ('Trades/Year', 'trades_per_year', fmt_num, False),
    ]
    
    for metric_name, key, formatter, higher_is_better in metrics:
        val_1 = results_1dte.get(key)
        val_2 = results_2dte.get(key)
        val_3 = results_3dte.get(key)
        
        values = [val_1, val_2, val_3]
        
        html += f"""
        <tr>
            <td class="metric">{metric_name}</td>
            <td class="{get_class(values, 0, higher_is_better)}">{formatter(val_1)}</td>
            <td class="{get_class(values, 1, higher_is_better)}">{formatter(val_2)}</td>
            <td class="{get_class(values, 2, higher_is_better)}">{formatter(val_3)}</td>
        </tr>
"""
    
    html += """
    </table>
    
    <h2>Winner Analysis</h2>
    <div class="summary">
"""
    
    # Determine overall winner
    try:
        returns = [
            results_1dte.get('annual_return_pct', -999),
            results_2dte.get('annual_return_pct', -999),
            results_3dte.get('annual_return_pct', -999)
        ]
        sharpes = [
            results_1dte.get('sharpe_ratio', -999),
            results_2dte.get('sharpe_ratio', -999),
            results_3dte.get('sharpe_ratio', -999)
        ]
        
        labels = ['1 DTE', '2 DTE', '3 DTE']
        
        # Find winner
        best_idx = returns.index(max(returns))
        winner = labels[best_idx]
        winner_return = returns[best_idx]
        winner_sharpe = sharpes[best_idx]
        
        # Check success criteria
        criteria_met = []
        if winner_return > 0:
            criteria_met.append('✅ Positive returns')
        else:
            criteria_met.append('❌ Positive returns')
        
        if winner_sharpe > 1.5:
            criteria_met.append('✅ Sharpe > 1.5')
        else:
            criteria_met.append('❌ Sharpe > 1.5')
        
        best_results = [results_1dte, results_2dte, results_3dte][best_idx]
        if best_results.get('win_rate', 0) > 70:
            criteria_met.append('✅ Win rate > 70%')
        else:
            criteria_met.append('❌ Win rate > 70%')
        
        if best_results.get('avg_monthly_return_pct', 0) > 15:
            criteria_met.append('✅ Monthly return > 15%')
        else:
            criteria_met.append('❌ Monthly return > 15%')
        
        html += f"""
        <h3>🏆 Winner: {winner}</h3>
        <ul>
            <li><strong>Annual Return:</strong> {winner_return:.1f}%</li>
            <li><strong>Sharpe Ratio:</strong> {winner_sharpe:.2f}</li>
            <li><strong>Win Rate:</strong> {best_results.get('win_rate', 0):.1f}%</li>
            <li><strong>Avg Monthly Return:</strong> {best_results.get('avg_monthly_return_pct', 0):.1f}%</li>
        </ul>
        
        <h3>Success Criteria Assessment</h3>
        <ul>
"""
        for criterion in criteria_met:
            html += f"            <li>{criterion}</li>\n"
        
        html += """
        </ul>
        
        <h3>Path A Fit</h3>
"""
        
        # Check if this fits Path A
        all_criteria = all('✅' in c for c in criteria_met)
        if all_criteria and winner_return > 50:  # Need high returns for Path A
            html += f"""
        <p class="success">
            <strong>✅ EXCELLENT PATH A CANDIDATE!</strong><br>
            {winner} meets all criteria and provides strong returns to support $100K → $10M goal.
            Projected monthly return: {best_results.get('avg_monthly_return_pct', 0):.1f}%
        </p>
"""
        elif winner_return > 0:
            html += f"""
        <p>
            <strong>⚠️ PARTIAL SUCCESS</strong><br>
            {winner} is profitable but may not meet all Path A requirements.
            Consider as secondary strategy or optimization candidate.
        </p>
"""
        else:
            html += """
        <p class="failure">
            <strong>❌ PATH A REJECTED</strong><br>
            All 1-3 DTE variants failed to produce positive returns.
            Must explore other strategies (spreads, different underliers, or different timeframes).
        </p>
"""
        
    except Exception as e:
        html += f"<p>Error analyzing results: {e}</p>"
    
    html += """
    </div>
    
    <h2>Strategy Details</h2>
    <table>
        <tr>
            <th class="metric">Strategy</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>Strikes</th>
            <th>Frequency</th>
        </tr>
        <tr>
            <td class="metric">1 DTE</td>
            <td>9:45 AM daily</td>
            <td>Next day at open</td>
            <td>25Δ put/call</td>
            <td>Daily (~250/year)</td>
        </tr>
        <tr>
            <td class="metric">2 DTE</td>
            <td>9:45 AM every other day</td>
            <td>2 days later</td>
            <td>25Δ put/call</td>
            <td>3×/week (~125/year)</td>
        </tr>
        <tr>
            <td class="metric">3 DTE</td>
            <td>Mon/Wed 9:45 AM</td>
            <td>Thu/Mon</td>
            <td>30Δ put/call</td>
            <td>2×/week (~100/year)</td>
        </tr>
    </table>
    
    <p><em>Report generated: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC') + """</em></p>
</body>
</html>
"""
    
    # Save report
    output_path = Path(__file__).parent / 'EXP-3505_COMPARISON_REPORT.html'
    with open(output_path, 'w') as f:
        f.write(html)
    
    logger.info(f"\n📊 Comparison report saved to: {output_path}")
    return output_path


def main():
    """Run all backtests and generate comparison."""
    logger.info("=" * 80)
    logger.info("EXP-3505: SPX 1-3 DTE IRON CONDOR BACKTEST SUITE")
    logger.info("=" * 80)
    logger.info("")
    logger.info("Testing 3 variants:")
    logger.info("  1. 1 DTE - Daily entries")
    logger.info("  2. 2 DTE - Every other day")
    logger.info("  3. 3 DTE - 3-day hold")
    logger.info("")
    
    # Run all backtests
    results_1dte = run_backtest('backtest_1dte.py')
    results_2dte = run_backtest('backtest_2dte.py')
    results_3dte = run_backtest('backtest_3dte.py')
    
    # Generate comparison report
    logger.info("")
    logger.info("=" * 80)
    logger.info("Generating Comparison Report")
    logger.info("=" * 80)
    
    report_path = generate_comparison_report(results_1dte, results_2dte, results_3dte)
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("ALL BACKTESTS COMPLETE!")
    logger.info("=" * 80)
    logger.info(f"\n📊 View results: {report_path}")
    
    # Print summary
    logger.info("\n" + "=" * 80)
    logger.info("QUICK SUMMARY")
    logger.info("=" * 80)
    
    for label, results in [('1 DTE', results_1dte), ('2 DTE', results_2dte), ('3 DTE', results_3dte)]:
        if 'error' in results:
            logger.info(f"{label}: ERROR - {results['error']}")
        else:
            logger.info(f"{label}: {results.get('annual_return_pct', 0):.1f}% annual return, "
                       f"Sharpe {results.get('sharpe_ratio', 0):.2f}, "
                       f"{results.get('win_rate', 0):.1f}% win rate")


if __name__ == '__main__':
    main()
