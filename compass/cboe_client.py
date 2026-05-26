"""
CBOE Options Data Client (AWS Athena)

Queries historical options data from CBOE's 4-table Athena schema:
  - cboe.options_1min
  - cboe.options_5min
  - cboe.options_15min
  - cboe.options_60min

Each table schema:
  ticker, expiration, strike, option_type, timestamp,
  bid, ask, delta, gamma, theta, vega, volume, open_interest
"""
import logging
import os
import time
from datetime import datetime
from typing import List, Optional

import boto3
import pandas as pd

logger = logging.getLogger(__name__)


class CBOEAthenaClient:
    """Query CBOE options data via AWS Athena."""
    
    def __init__(
        self,
        database: str = None,
        output_bucket: str = None,
        region: str = None,
    ):
        self.database = database or os.getenv("ATHENA_DATABASE", "cboe")
        self.output_bucket = output_bucket or os.getenv("ATHENA_OUTPUT_BUCKET")
        self.region = region or os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1")
        
        if not self.output_bucket:
            raise ValueError("ATHENA_OUTPUT_BUCKET must be set")
        
        self.client = boto3.client("athena", region_name=self.region)
    
    def query_greeks(
        self,
        ticker: str,
        expiration: str,
        strike: float,
        option_type: str,
        start_date: str,
        end_date: str,
        interval: str = "60min",
    ) -> pd.DataFrame:
        """
        Query Greeks for a specific option contract over a date range.
        
        Returns DataFrame with columns:
          timestamp, bid, ask, delta, gamma, theta, vega, volume, open_interest
        """
        # CBOE table naming: cboe_01min_option_candles, cboe_60min_option_candles, etc.
        table = f"cboe_{interval}_option_candles"
        
        # Extract year, month, day for partition pruning (CRITICAL for cost control)
        from datetime import datetime
        start_dt = datetime.strptime(start_date.split()[0], "%Y-%m-%d")
        end_dt = datetime.strptime(end_date.split()[0], "%Y-%m-%d")
        
        query = f"""
        SELECT quote_timestamp as timestamp, bid_close as bid, ask_close as ask, 
               delta, gamma, theta, vega, trade_volume as volume, underlying_price
        FROM {table}
        WHERE year = '{start_dt.year:04d}' 
          AND month = '{start_dt.month:02d}'
          AND day >= '{start_dt.day:02d}' AND day <= '{end_dt.day:02d}'
          AND symbol = '{ticker}'
          AND expiration = date '{expiration}'
          AND strike = {strike}
          AND option_type = '{option_type}'
        ORDER BY quote_timestamp
        """
        
        return self._execute_query(query)
    
    def _execute_query(self, query: str) -> pd.DataFrame:
        """Execute Athena query, wait for completion, return DataFrame."""
        response = self.client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self.database},
            ResultConfiguration={"OutputLocation": self.output_bucket},
        )
        
        query_id = response["QueryExecutionId"]
        
        # Poll for completion (max 60s)
        for _ in range(60):
            result = self.client.get_query_execution(QueryExecutionId=query_id)
            state = result["QueryExecution"]["Status"]["State"]
            
            if state == "SUCCEEDED":
                break
            elif state in ("FAILED", "CANCELLED"):
                reason = result["QueryExecution"]["Status"].get("StateChangeReason", "")
                raise RuntimeError(f"Athena query {state}: {reason}")
            
            time.sleep(1)
        else:
            raise TimeoutError(f"Athena query {query_id} timed out after 60s")
        
        # Fetch results
        results = self.client.get_query_results(QueryExecutionId=query_id)
        
        # Parse to DataFrame
        rows = results["ResultSet"]["Rows"]
        if not rows:
            return pd.DataFrame()
        
        # First row is header
        columns = [col["VarCharValue"] for col in rows[0]["Data"]]
        data = []
        for row in rows[1:]:
            data.append([col.get("VarCharValue") for col in row["Data"]])
        
        df = pd.DataFrame(data, columns=columns)
        
        # Type conversions
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        for col in ["bid", "ask", "delta", "gamma", "theta", "vega"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        return df
