#!/usr/bin/env python3
"""Inside-NBBO uplift on WIDE-SPREAD underliers (XLF/XLI/GLD) with real Polygon quotes.
Same pricing engine as exp_nbbo_real_quotes; runs credit_spread per ticker."""
import sys, json, time
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from strategies import STRATEGY_REGISTRY
from engine.portfolio_backtester import PortfolioBacktester
from scripts.portfolio_blend import get_strategy_params
import scripts.exp_nbbo_real_quotes as R
R.DECISION_ET="15:55"

TICKERS=sys.argv[1].split(",") if len(sys.argv)>1 else ["XLF","XLI","GLD"]
YEARS=list(range(2022,2026))
CAP=100_000

def run():
    cs=STRATEGY_REGISTRY["credit_spread"]
    params=get_strategy_params("credit_spread", risk_override=0.12)
    trades=[]
    for tk in TICKERS:
        for y in YEARS:
            bt=PortfolioBacktester(strategies=[("credit_spread",cs(dict(params)))],
                tickers=[tk],start_date=datetime(y,1,1),end_date=datetime(y,12,31),
                starting_capital=CAP,max_positions=10,max_positions_per_strategy=5)
            try: bt.run()
            except Exception as e: print("skip",tk,y,e); continue
            for t in bt.closed_trades: trades.append(t)
    return trades

def main():
    t0=time.time()
    print("WIDE-SPREAD inside-NBBO:",TICKERS,YEARS)
    trades=run()
    print(f"{len(trades)} trades. pricing with real quotes...",flush=True)
    cost={"cross":0.,"mid":0.,"nbbo":0.}; priced=[]; gross=0.
    half_acc=[]
    for i,t in enumerate(trades):
        c=R.trade_real_costs(t)
        if c is None: continue
        priced.append(t); gross+=t.realized_pnl
        for k in cost: cost[k]+=c[k]
        if (i+1)%25==0: print(f"  priced {len(priced)}/{i+1} calls={R._api_calls}",flush=True)
    ny=len(YEARS)
    def cagr(net): return ((1+net/CAP)**(1/ny)-1)*100
    res={}
    for k in ["cross","mid","nbbo"]:
        net=gross-cost[k]
        res[k]={"exec":round(cost[k],2),"net":round(net,2),"ret_pct":round(net/CAP*100,2),"cagr":round(cagr(net),2)}
        print(f"  {k:6} exec ${cost[k]:,.0f} net ${net:,.0f} ({net/CAP*100:+.1f}%) CAGR {res[k]['cagr']:+.1f}%")
    up=round(res['nbbo']['net']-res['cross']['net'],2)
    print(f"  UPLIFT nbbo vs cross: +${up:,.0f}")
    out={"tickers":TICKERS,"years":YEARS,"n_total":len(trades),"n_priced":len(priced),
         "coverage_pct":round(len(priced)/max(len(trades),1)*100,1),"gross":round(gross,2),
         "profiles":res,"uplift_nbbo_vs_cross":up,"api_calls":R._api_calls,"runtime":round(time.time()-t0,1)}
    (ROOT/"output"/"nbbo_widespread.json").write_text(json.dumps(out,indent=2))
    print(f"coverage {out['coverage_pct']}% ({len(priced)}/{len(trades)}) runtime {out['runtime']}s")
    print("wrote output/nbbo_widespread.json")

if __name__=="__main__": main()
