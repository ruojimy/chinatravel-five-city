"""Use a planner time choice when a source has no recommendation."""
import math

def visit_minutes(row, default=90):
    try:value=float(row.get('recommendmintime'))
    except (TypeError,ValueError):value=float('nan')
    return max(45,int(round(value*60))) if math.isfinite(value) and value>0 else int(default)
