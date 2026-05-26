#!/bin/bash
# Monitor CBOE download progress

PROGRESS_FILE="data/cboe_download_progress.json"
LOG_FILE="logs/cboe_download.log"
DATA_DIR="data/cboe_complete"

echo "📊 CBOE Download Progress Report"
echo "================================"
echo ""

# Check if process is running
PID_FILE="/tmp/cboe_download.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "✅ Download process: RUNNING (PID: $PID)"
    else
        echo "⚠️  Download process: NOT RUNNING (may have completed or crashed)"
    fi
else
    echo "⚠️  PID file not found"
fi

echo ""

# Parse progress file
if [ -f "$PROGRESS_FILE" ]; then
    COMPLETED=$(python3 << EOF
import json
with open("$PROGRESS_FILE") as f:
    data = json.load(f)
    print(len(data["completed"]))
EOF
)
    FAILED=$(python3 << EOF
import json
with open("$PROGRESS_FILE") as f:
    data = json.load(f)
    print(len(data["failed"]))
EOF
)
    COST=$(python3 << EOF
import json
with open("$PROGRESS_FILE") as f:
    data = json.load(f)
    print(f"\${data['cost_usd']:.2f}")
EOF
)
    
    TOTAL=1728
    PCT=$(python3 -c "print(f'{100*$COMPLETED/$TOTAL:.1f}')")
    
    echo "📈 Progress:"
    echo "   Completed: $COMPLETED / $TOTAL ($PCT%)"
    echo "   Failed: $FAILED"
    echo "   Cost: $COST"
    echo ""
    
    # ETA calculation
    if [ -f "$LOG_FILE" ]; then
        FIRST_TIME=$(head -1 "$LOG_FILE" | awk '{print $1" "$2}')
        LAST_TIME=$(tail -1 "$LOG_FILE" | awk '{print $1" "$2}')
        
        START_TS=$(date -d "$FIRST_TIME" +%s 2>/dev/null || echo "0")
        CURRENT_TS=$(date -d "$LAST_TIME" +%s 2>/dev/null || date +%s)
        
        if [ "$START_TS" != "0" ] && [ "$COMPLETED" -gt "0" ]; then
            ELAPSED=$((CURRENT_TS - START_TS))
            AVG_SEC=$((ELAPSED / COMPLETED))
            REMAINING=$((TOTAL - COMPLETED))
            ETA_SEC=$((AVG_SEC * REMAINING))
            ETA_HOURS=$((ETA_SEC / 3600))
            
            echo "⏱️  Timing:"
            echo "   Elapsed: $((ELAPSED / 3600))h $((ELAPSED % 3600 / 60))m"
            echo "   Avg per chunk: ${AVG_SEC}s"
            echo "   ETA: ${ETA_HOURS}h $((ETA_SEC % 3600 / 60))m"
            echo ""
        fi
    fi
else
    echo "⚠️  Progress file not found: $PROGRESS_FILE"
    echo ""
fi

# File count
if [ -d "$DATA_DIR" ]; then
    FILE_COUNT=$(find "$DATA_DIR" -name "*.csv.gz" | wc -l)
    TOTAL_SIZE=$(du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}')
    
    echo "📁 Downloaded Files:"
    echo "   Count: $FILE_COUNT"
    echo "   Total size: $TOTAL_SIZE"
    echo ""
fi

# Recent activity
if [ -f "$LOG_FILE" ]; then
    echo "📝 Last 5 downloads:"
    grep "✅.*rows →" "$LOG_FILE" | tail -5 | sed 's/^/   /'
    echo ""
    
    echo "⚠️  Recent warnings/errors:"
    grep -E "(WARNING|ERROR)" "$LOG_FILE" | tail -5 | sed 's/^/   /' || echo "   None"
fi

echo ""
echo "💡 Commands:"
echo "   Monitor live: tail -f $LOG_FILE"
echo "   Check progress: bash scripts/check_download_progress.sh"
echo "   Stop download: pkill -f download_cboe_complete"
