"""Token usage tracking API routes.

Provides endpoints for querying and managing token usage data.
"""

import csv
import io
import logging

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from clawrium.gui.services.usage_tracker import get_usage_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
async def usage_summary(days: int = Query(default=30, ge=1, le=365)):
    """Get aggregate token usage summary."""
    tracker = get_usage_tracker()
    return tracker.get_summary(days=days)


@router.get("/history")
async def usage_history(
    days: int = Query(default=30, ge=1, le=365),
    granularity: str = Query(default="day", pattern="^(day|hour)$"),
):
    """Get time-series usage data for charts."""
    tracker = get_usage_tracker()
    return {"data": tracker.get_history(days=days, granularity=granularity)}


@router.get("/by-agent")
async def usage_by_agent(days: int = Query(default=30, ge=1, le=365)):
    """Get per-agent usage breakdown."""
    tracker = get_usage_tracker()
    return {"data": tracker.get_by_agent(days=days)}


@router.get("/export")
async def export_usage_csv(days: int = Query(default=365, ge=1, le=3650)):
    """Export all usage data as CSV."""
    tracker = get_usage_tracker()
    rows = tracker.export_all(days=days)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "timestamp",
            "agent_key",
            "provider",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost",
            "session_id",
        ]
    )
    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=clawrium-usage.csv"},
    )


@router.delete("")
async def clear_usage():
    """Clear all usage tracking data."""
    tracker = get_usage_tracker()
    deleted = tracker.clear()
    return {"success": True, "deleted": deleted}
