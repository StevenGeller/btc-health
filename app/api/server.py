"""FastAPI server for Bitcoin Health Scorecard."""

import os
from typing import Dict, List, Optional
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.storage.db import (
    get_latest_scores, execute_query, get_meta_config,
    get_latest_metric
)

# Create FastAPI app
app = FastAPI(
    title="Bitcoin Health Scorecard API",
    description="Real-time Bitcoin network health monitoring",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# Response models
class MetricScore(BaseModel):
    """Individual metric score."""
    score: float
    value: Optional[float]
    unit: Optional[str]
    trend_7d: Optional[float]
    trend_30d: Optional[float]
    last_updated: int


class PillarScore(BaseModel):
    """Pillar score with metrics."""
    name: str
    score: float
    weight: float
    trend_7d: Optional[float]
    trend_30d: Optional[float]
    metrics: Dict[str, MetricScore]


class OverallScore(BaseModel):
    """Overall health score response."""
    overall: float
    trend_7d: Optional[float]
    trend_30d: Optional[float]
    pillars: Dict[str, PillarScore]
    last_updated: int


class TimeSeriesPoint(BaseModel):
    """Time series data point."""
    timestamp: int
    value: float


class MetaInfo(BaseModel):
    """System metadata."""
    version: str
    last_collection: Optional[str]
    last_computation: Optional[str]
    data_sources: List[str]


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Bitcoin Health Scorecard API",
        "version": "1.0.0",
        "endpoints": [
            "/score/latest",
            "/score/timeseries",
            "/metrics/{metric_id}",
            "/pillars",
            "/meta",
            "/health"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    # Check database connectivity
    try:
        version = get_meta_config('version')
        return {
            "status": "healthy",
            "version": version,
            "timestamp": int(datetime.now(timezone.utc).timestamp())
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@app.get("/score/latest", response_model=OverallScore)
async def get_latest_score():
    """Get the latest overall and pillar scores."""
    # Get overall score
    overall_scores = execute_query(
        """
        SELECT * FROM scores
        WHERE kind = 'overall' AND id = 'overall'
        ORDER BY ts DESC
        LIMIT 1
        """
    )
    
    if not overall_scores:
        raise HTTPException(status_code=404, detail="No scores available")
    
    overall = overall_scores[0]
    
    # Get pillar scores
    pillar_scores = execute_query(
        """
        SELECT s.*, p.name, p.weight, p.description
        FROM scores s
        JOIN pillar_definitions p ON s.id = p.pillar_id
        WHERE s.kind = 'pillar'
        AND s.ts = (SELECT MAX(ts) FROM scores WHERE kind = 'pillar')
        """
    )
    
    # Get metric scores
    metric_scores = execute_query(
        """
        SELECT s.*, m.pillar_id, m.name, m.direction, m.description,
               met.value, met.unit
        FROM scores s
        JOIN metric_definitions m ON s.id = m.metric_id
        LEFT JOIN metrics met ON met.metric_id = s.id
            AND met.ts = (SELECT MAX(ts) FROM metrics WHERE metric_id = s.id)
        WHERE s.kind = 'metric'
        AND s.ts = (SELECT MAX(ts) FROM scores WHERE kind = 'metric')
        """
    )
    
    # Build response
    pillars = {}
    for pillar in pillar_scores:
        pillar_id = pillar['id']
        pillars[pillar_id] = PillarScore(
            name=pillar['name'],
            score=pillar['score'],
            weight=pillar['weight'],
            trend_7d=pillar.get('trend_7d'),
            trend_30d=pillar.get('trend_30d'),
            metrics={}
        )
    
    # Add metrics to pillars
    for metric in metric_scores:
        pillar_id = metric['pillar_id']
        if pillar_id in pillars:
            pillars[pillar_id].metrics[metric['id']] = MetricScore(
                score=metric['score'],
                value=metric.get('value'),
                unit=metric.get('unit'),
                trend_7d=metric.get('trend_7d'),
                trend_30d=metric.get('trend_30d'),
                last_updated=metric['ts']
            )
    
    return OverallScore(
        overall=overall['score'],
        trend_7d=overall.get('trend_7d'),
        trend_30d=overall.get('trend_30d'),
        pillars=pillars,
        last_updated=overall['ts']
    )


@app.get("/score/timeseries")
async def get_score_timeseries(
    kind: str = Query(..., description="Type: metric, pillar, or overall"),
    id: str = Query(..., description="ID of the metric/pillar (use 'overall' for overall)"),
    days: int = Query(30, description="Number of days of history")
):
    """Get time series data for a score."""
    if kind not in ['metric', 'pillar', 'overall']:
        raise HTTPException(status_code=400, detail="Invalid kind parameter")
    
    cutoff = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
    
    scores = execute_query(
        """
        SELECT ts, score FROM scores
        WHERE kind = ? AND id = ? AND ts >= ?
        ORDER BY ts ASC
        """,
        (kind, id, cutoff)
    )
    
    if not scores:
        raise HTTPException(status_code=404, detail=f"No data found for {kind}/{id}")
    
    return {
        "kind": kind,
        "id": id,
        "days": days,
        "data": [
            TimeSeriesPoint(timestamp=s['ts'], value=s['score'])
            for s in scores
        ]
    }


@app.get("/metrics/{metric_id}")
async def get_metric_details(metric_id: str):
    """Get detailed information about a specific metric."""
    # Get metric definition
    definition = execute_query(
        """
        SELECT * FROM metric_definitions
        WHERE metric_id = ?
        """,
        (metric_id,)
    )
    
    if not definition:
        raise HTTPException(status_code=404, detail=f"Metric {metric_id} not found")
    
    defn = definition[0]
    
    # Get latest value and score
    latest_metric = get_latest_metric(metric_id)
    latest_score = execute_query(
        """
        SELECT * FROM scores
        WHERE kind = 'metric' AND id = ?
        ORDER BY ts DESC
        LIMIT 1
        """,
        (metric_id,)
    )
    
    # Get percentiles
    percentiles = execute_query(
        """
        SELECT * FROM percentiles
        WHERE metric_id = ?
        ORDER BY ts DESC
        LIMIT 1
        """,
        (metric_id,)
    )
    
    return {
        "metric_id": metric_id,
        "name": defn['name'],
        "description": defn['description'],
        "pillar_id": defn['pillar_id'],
        "direction": defn['direction'],
        "target_min": defn.get('target_min'),
        "target_max": defn.get('target_max'),
        "weight": defn['weight'],
        "latest_value": latest_metric['value'] if latest_metric else None,
        "unit": latest_metric.get('unit') if latest_metric else None,
        "latest_score": latest_score[0]['score'] if latest_score else None,
        "trend_7d": latest_score[0].get('trend_7d') if latest_score else None,
        "trend_30d": latest_score[0].get('trend_30d') if latest_score else None,
        "percentiles": percentiles[0] if percentiles else None,
        "last_updated": latest_metric['ts'] if latest_metric else None
    }


@app.get("/pillars")
async def get_pillars():
    """Get list of all pillars with their definitions."""
    pillars = execute_query(
        """
        SELECT * FROM pillar_definitions
        ORDER BY weight DESC
        """
    )
    
    return {
        "pillars": [
            {
                "pillar_id": p['pillar_id'],
                "name": p['name'],
                "weight": p['weight'],
                "description": p['description']
            }
            for p in pillars
        ]
    }


@app.get("/meta", response_model=MetaInfo)
async def get_metadata():
    """Get system metadata and configuration."""
    return MetaInfo(
        version=get_meta_config('version') or "1.0.0",
        last_collection=get_meta_config('last_collection'),
        last_computation=get_meta_config('last_computation'),
        data_sources=[
            "mempool.space",
            "Bitnodes",
            "Blockchain.com",
            "CoinGecko",
            "ForkMonitor"
        ]
    )


@app.get("/collectors/status")
async def get_collector_status():
    """Get status of all data collectors."""
    status = execute_query(
        """
        SELECT * FROM collection_status
        ORDER BY collector
        """
    )
    
    return {
        "collectors": [
            {
                "name": s['collector'],
                "last_run": s['last_run'],
                "last_success": s['last_success'],
                "last_error": s['last_error'],
                "consecutive_failures": s['consecutive_failures'],
                "status": "healthy" if s['consecutive_failures'] == 0 else "failing"
            }
            for s in status
        ]
    }


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', 8080))
    
    uvicorn.run(app, host=host, port=port)
