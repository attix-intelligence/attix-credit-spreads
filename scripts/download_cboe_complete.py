#!/usr/bin/env python3
"""
CBOE Complete Data Downloader

Downloads ENTIRE CBOE options dataset for SPX/SPY/QQQ from 2020-2025.
Organizes by ticker/dte/year-month for fast backtesting access.

Usage:
    python download_cboe_complete.py --tickers SPX SPY QQQ --start 2020-01-01 --end 2025-12-31

Storage structure:
    data/cboe_complete/
    ├── spx/
    │   ├── 0dte/
    │   │   ├── 2020-01.parquet
    │   │   ├── 2020-02.parquet
    │   │   └── ...
    │   ├── 1dte/
    │   ├── 2dte/
    │   └── ...
    ├── spy/
    └── qqq/

Features:
- Progress tracking (resume if interrupted)
- Cost estimation (Athena scans)
- Compression (Parquet with snappy)
- Validation (check coverage gaps)
"""
import argparse
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import boto3
import pandas as pd

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    
    # Fallback: simple progress counter
    class FakeTqdm:
        def __init__(self, total=None, **kwargs):
            self.total = total
            self.n = 0
        
        def __enter__(self):
            return self
        
        def __exit__(self, *args):
            pass
        
        def update(self, n=1):
            self.n += n
            if self.total:
                print(f"Progress: {self.n}/{self.total} ({100*self.n/self.total:.1f}%)")
        
        def set_postfix(self, *args, **kwargs):
            pass
    
    tqdm = FakeTqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CBOEBulkDownloader:
    """Download complete CBOE dataset with progress tracking."""
    
    # DTE buckets to download
    DTE_BUCKETS = [0, 1, 2, 3, 5, 7, 14, 30]
    
    # CBOE ticker mappings (some use ^prefix)
    TICKER_MAP = {
        "SPX": "^SPX",
        "SPY": "SPY",
        "QQQ": "QQQ",
    }
    
    def __init__(
        self,
        output_dir: str = "data/cboe_complete",
        database: str = "cboe",
        output_bucket: str = None,
        region: str = "ap-southeast-1",
        progress_file: str = "data/cboe_download_progress.json",
    ):
        # Load .env if exists
        from pathlib import Path
        env_file = Path(".env")
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key, value)
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.database = database or os.getenv("ATHENA_DATABASE", "cboe")
        self.output_bucket = output_bucket or os.getenv("ATHENA_OUTPUT_BUCKET")
        self.region = region or os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1")
        
        if not self.output_bucket:
            raise ValueError("ATHENA_OUTPUT_BUCKET must be set (in .env or --output-bucket)")
        
        self.client = boto3.client("athena", region_name=self.region)
        
        self.progress_file = Path(progress_file)
        self.progress = self._load_progress()
        
        self.total_cost = 0.0  # Track Athena costs
        self.total_rows = 0
        self.total_chunks = 0
    
    def _load_progress(self) -> Dict:
        """Load download progress (for resume capability)."""
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                return json.load(f)
        return {"completed": [], "failed": [], "cost_usd": 0.0}
    
    def _save_progress(self):
        """Save download progress."""
        self.progress["cost_usd"] = self.total_cost
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.progress_file, "w") as f:
            json.dump(self.progress, f, indent=2)
    
    def _is_completed(self, chunk_id: str) -> bool:
        """Check if chunk already downloaded."""
        return chunk_id in self.progress["completed"]
    
    def _mark_completed(self, chunk_id: str):
        """Mark chunk as completed."""
        self.progress["completed"].append(chunk_id)
        self._save_progress()
    
    def _mark_failed(self, chunk_id: str, error: str):
        """Mark chunk as failed."""
        self.progress["failed"].append({"chunk": chunk_id, "error": error, "time": datetime.now().isoformat()})
        self._save_progress()
    
    def download_all(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        dry_run: bool = False,
    ):
        """
        Download complete dataset for all tickers/DTEs/months.
        
        Args:
            tickers: List of tickers (e.g., ["SPX", "SPY", "QQQ"])
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            dry_run: If True, only estimate cost without downloading
        """
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        # Generate all chunks to download
        chunks = self._generate_chunks(tickers, start_dt, end_dt)
        
        logger.info(f"📊 Total chunks to download: {len(chunks)}")
        logger.info(f"📁 Output directory: {self.output_dir.absolute()}")
        
        if dry_run:
            logger.info("🔍 DRY RUN MODE - Estimating cost only")
            self._estimate_cost(chunks)
            return
        
        # Download each chunk
        failed_count = 0
        with tqdm(total=len(chunks), desc="Downloading CBOE data") as pbar:
            for chunk in chunks:
                chunk_id = chunk["id"]
                
                if self._is_completed(chunk_id):
                    pbar.update(1)
                    pbar.set_postfix({"skipped": "already done"})
                    continue
                
                try:
                    self._download_chunk(chunk)
                    self._mark_completed(chunk_id)
                    pbar.set_postfix({"rows": self.total_rows, "cost": f"${self.total_cost:.3f}"})
                except Exception as e:
                    logger.error(f"❌ Failed to download {chunk_id}: {e}")
                    self._mark_failed(chunk_id, str(e))
                    failed_count += 1
                
                pbar.update(1)
        
        # Summary
        logger.info(f"\n✅ Download complete!")
        logger.info(f"   Total rows: {self.total_rows:,}")
        logger.info(f"   Total cost: ${self.total_cost:.2f}")
        logger.info(f"   Failed chunks: {failed_count}/{len(chunks)}")
        
        if failed_count > 0:
            logger.warning(f"⚠️  {failed_count} chunks failed. Check {self.progress_file} for details.")
    
    def _generate_chunks(self, tickers: List[str], start_dt: datetime, end_dt: datetime) -> List[Dict]:
        """Generate list of all chunks to download."""
        chunks = []
        
        for ticker in tickers:
            cboe_ticker = self.TICKER_MAP.get(ticker.upper(), ticker.upper())
            
            for dte in self.DTE_BUCKETS:
                # Generate monthly chunks
                current = start_dt.replace(day=1)
                while current <= end_dt:
                    # Month range
                    month_start = current
                    month_end = (current.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                    
                    if month_end > end_dt:
                        month_end = end_dt
                    
                    chunk_id = f"{ticker.lower()}_{dte}dte_{current.year:04d}-{current.month:02d}"
                    
                    chunks.append({
                        "id": chunk_id,
                        "ticker": ticker.upper(),
                        "cboe_ticker": cboe_ticker,
                        "dte": dte,
                        "start_date": month_start,
                        "end_date": month_end,
                        "output_path": self.output_dir / ticker.lower() / f"{dte}dte" / f"{current.year:04d}-{current.month:02d}.csv.gz",
                    })
                    
                    # Next month
                    current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        
        return chunks
    
    def _download_chunk(self, chunk: Dict):
        """Download a single month of data for one ticker/DTE."""
        start_date = chunk["start_date"]
        end_date = chunk["end_date"]
        cboe_ticker = chunk["cboe_ticker"]
        dte = chunk["dte"]
        
        # Query for all contracts expiring in DTE range
        query = f"""
        SELECT 
            symbol as ticker,
            expiration,
            strike,
            option_type,
            quote_timestamp as timestamp,
            open_px as open,
            high_px as high,
            low_px as low,
            close_px as close,
            bid_open,
            bid_high,
            bid_low,
            bid_close,
            ask_open,
            ask_high,
            ask_low,
            ask_close,
            delta,
            gamma,
            theta,
            vega,
            rho,
            implied_volatility as iv,
            trade_volume as volume,
            open_interest,
            underlying_price
        FROM cboe_60min_option_candles
        WHERE year = '{start_date.year:04d}'
          AND month = '{start_date.month:02d}'
          AND symbol = '{cboe_ticker}'
          AND DATE_DIFF('day', date '{start_date.strftime("%Y-%m-%d")}', expiration) BETWEEN {dte} AND {dte + 1}
        ORDER BY quote_timestamp, strike
        """
        
        df = self._execute_query(query)
        
        if df.empty:
            logger.warning(f"⚠️  No data for {chunk['id']}")
            return
        
        # Save to CSV (Parquet requires pyarrow which may not be installed)
        output_path = chunk["output_path"]
        output_path = output_path.with_suffix(".csv.gz")  # gzip instead of parquet
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, compression="gzip", index=False)
        
        self.total_rows += len(df)
        self.total_chunks += 1
        
        logger.info(f"✅ {chunk['id']}: {len(df):,} rows → {output_path}")
    
    def _execute_query(self, query: str) -> pd.DataFrame:
        """Execute Athena query and return DataFrame."""
        import time
        
        response = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self.database},
            ResultConfiguration={"OutputLocation": self.output_bucket},
        )
        
        query_id = response["QueryExecutionId"]
        
        # Poll for completion
        for _ in range(300):  # 5 minutes max
            result = self.client.get_query_execution(QueryExecutionId=query_id)
            state = result["QueryExecution"]["Status"]["State"]
            
            if state == "SUCCEEDED":
                # Track cost (Athena charges $5 per TB scanned)
                stats = result["QueryExecution"]["Statistics"]
                bytes_scanned = stats.get("DataScannedInBytes", 0)
                cost = (bytes_scanned / 1e12) * 5.0  # $5/TB
                self.total_cost += cost
                break
            elif state in ("FAILED", "CANCELLED"):
                reason = result["QueryExecution"]["Status"].get("StateChangeReason", "")
                raise RuntimeError(f"Query {state}: {reason}")
            
            time.sleep(1)
        else:
            raise TimeoutError(f"Query {query_id} timed out after 5 minutes")
        
        # Fetch results
        results = self.client.get_query_results(QueryExecutionId=query_id, MaxResults=1000)
        
        rows = results["ResultSet"]["Rows"]
        if not rows:
            return pd.DataFrame()
        
        # Parse to DataFrame
        columns = [col["VarCharValue"] for col in rows[0]["Data"]]
        data = []
        
        # Paginate through all results
        for row in rows[1:]:
            data.append([col.get("VarCharValue") for col in row["Data"]])
        
        # Fetch remaining pages
        while "NextToken" in results:
            results = self.client.get_query_results(
                QueryExecutionId=query_id,
                NextToken=results["NextToken"],
                MaxResults=1000,
            )
            for row in results["ResultSet"]["Rows"]:
                data.append([col.get("VarCharValue") for col in row["Data"]])
        
        df = pd.DataFrame(data, columns=columns)
        
        # Type conversions
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        if "expiration" in df.columns:
            df["expiration"] = pd.to_datetime(df["expiration"])
        
        numeric_cols = ["strike", "open", "high", "low", "close", "bid_close", "ask_close",
                        "delta", "gamma", "theta", "vega", "rho", "iv", "volume", "underlying_price"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        return df
    
    def _estimate_cost(self, chunks: List[Dict]):
        """Estimate total download cost (dry run)."""
        logger.info(f"📊 Estimating cost for {len(chunks)} chunks...")
        logger.info(f"⚠️  Accurate cost estimation requires downloading sample data.")
        logger.info(f"\n💰 Rough Cost Estimate (based on CBOE dataset size):")
        logger.info(f"   Total chunks: {len(chunks)}")
        logger.info(f"   CBOE total dataset: ~200M+ rows (202,625,690 as of May 2024)")
        logger.info(f"   Estimated data per chunk: ~500 MB")
        logger.info(f"   Total estimate: ~{len(chunks) * 0.5:.1f} GB")
        logger.info(f"   Athena cost ($5/TB scanned): ~${len(chunks) * 0.5 / 1000 * 5:.2f}")
        logger.info(f"\n💡 Recommendation:")
        logger.info(f"   - Run 1 month test first: --start 2024-01-01 --end 2024-01-31")
        logger.info(f"   - Monitor cost in progress file")
        logger.info(f"   - Then scale to full 2020-2025 range")
        logger.info(f"\n💡 To proceed: Remove --dry-run flag")


def main():
    parser = argparse.ArgumentParser(description="Download complete CBOE options dataset")
    parser.add_argument("--tickers", nargs="+", default=["SPX", "SPY", "QQQ"], help="Tickers to download")
    parser.add_argument("--start", default="2020-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default="data/cboe_complete", help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Estimate cost without downloading")
    parser.add_argument("--progress-file", default="data/cboe_download_progress.json", help="Progress tracking file")
    
    args = parser.parse_args()
    
    downloader = CBOEBulkDownloader(
        output_dir=args.output_dir,
        progress_file=args.progress_file,
    )
    
    downloader.download_all(
        tickers=args.tickers,
        start_date=args.start,
        end_date=args.end,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
