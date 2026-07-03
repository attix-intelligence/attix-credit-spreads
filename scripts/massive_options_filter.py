#!/usr/bin/env python3
"""Stream a Massive us_options_opra/quotes_v1 daily file and keep only rows
for target underlyings (SPY/QQQ). Never persists the full file.

Usage: massive_options_filter.py YYYY-MM-DD [SPY,QQQ] [max_seconds] [out.csv.gz]
"""
import boto3, gzip, io, sys, time, zlib
from botocore.config import Config

AK="58e2b161-1ec3-4bca-8764-38316c7c355d"
SK="y3y07kPIE0VkS6M3erj7uNsJ3dpLYDCH"
s3=boto3.client("s3",endpoint_url="https://files.massive.com",
    aws_access_key_id=AK,aws_secret_access_key=SK,
    config=Config(signature_version="s3v4",read_timeout=900,retries={"max_attempts":3}),
    region_name="us-east-1")

date=sys.argv[1] if len(sys.argv)>1 else "2024-06-03"
unders=(sys.argv[2] if len(sys.argv)>2 else "SPY,QQQ").split(",")
max_sec=float(sys.argv[3]) if len(sys.argv)>3 else 60.0
outpath=sys.argv[4] if len(sys.argv)>4 else None
y,m,d=date.split("-")
key=f"us_options_opra/quotes_v1/{y}/{m}/{date}.csv.gz"
prefixes=tuple(f"O:{u}".encode() for u in unders)

obj=s3.get_object(Bucket="flatfiles",Key=key)
body=obj["Body"]; size=obj["ContentLength"]
print(f"file {key}  {size/1e9:.1f} GB compressed", flush=True)

dec=zlib.decompressobj(16+zlib.MAX_WBITS)
out=gzip.open(outpath,"wt") if outpath else None
t0=time.time(); read_bytes=0; kept=0; total=0; header=None; tail=b""
CHUNK=8*1024*1024
while True:
    raw=body.read(CHUNK)
    if not raw: break
    read_bytes+=len(raw)
    data=tail+dec.decompress(raw)
    lines=data.split(b"\n"); tail=lines.pop()
    for ln in lines:
        if header is None:
            header=ln.decode(); 
            if out: out.write(header+"\n")
            continue
        total+=1
        if ln.startswith(prefixes):
            kept+=1
            if out: out.write(ln.decode()+"\n")
    if time.time()-t0>max_sec:
        print(f"[cap {max_sec}s hit]", flush=True); break
el=time.time()-t0
print(f"read {read_bytes/1e9:.2f} GB compressed in {el:.0f}s ({read_bytes/1e6/el:.0f} MB/s)")
print(f"rows scanned {total:,} | kept {kept:,} ({', '.join(unders)})")
if out: out.close(); print("wrote",outpath)
