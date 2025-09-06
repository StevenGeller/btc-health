"""
Production-grade FastAPI server for Bitcoin Health Scorecard.
Implements caching, rate limiting, monitoring, and error handling.
"""

import os
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
import asyncio
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator
from prometheus_client import Counter, Histogram, Gauge, generate_latest
import redis
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.storage.db import (
    get_latest_scores, execute_query, get_meta_config,
    get_latest_metric, get_metric_history
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Metrics for monitoring
request_count = Counter('btc_health_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
request_duration = Histogram('btc_health_request_duration_seconds', 'Request duration', ['method', 'endpoint'])
active_requests = Gauge('btc_health_active_requests', 'Active requests')
cache_hits = Counter('btc_health_cache_hits_total', 'Cache hits', ['endpoint'])
cache_misses = Counter('btc_health_cache_misses_total', 'Cache misses', ['endpoint'])
error_count = Counter('btc_health_errors_total', 'Total errors', ['type'])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)


# Response models with validation
class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service health status")
    version: str = Field(..., description="API version")
    timestamp: int = Field(..., description="Current timestamp")
    database: str = Field(..., description="Database status")
    cache: str = Field(..., description="Cache status")
    collectors: Dict[str, str] = Field(default_factory=dict, description="Collector statuses")


class MetricScore(BaseModel):
    """Individual metric score with metadata."""
    score: float = Field(..., ge=0, le=100, description="Score from 0-100")
    value: Optional[float] = Field(None, description="Raw metric value")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    trend_7d: Optional[float] = Field(None, description="7-day trend percentage")
    trend_30d: Optional[float] = Field(None, description="30-day trend percentage")
    last_updated: int = Field(..., description="Last update timestamp")
    quality: str = Field(default="high", description="Data quality indicator")
    
    @validator('score')
    def validate_score(cls, v):
        """Ensure score is within valid range."""
        return max(0, min(100, v))


class PillarScore(BaseModel):
    """Pillar score with constituent metrics."""
    name: str = Field(..., description="Pillar name")
    score: float = Field(..., ge=0, le=100, description="Pillar score")
    weight: float = Field(..., ge=0, le=1, description="Weight in overall score")
    trend_7d: Optional[float] = Field(None, description="7-day trend")
    trend_30d: Optional[float] = Field(None, description="30-day trend")
    metrics: Dict[str, MetricScore] = Field(default_factory=dict, description="Component metrics")
    health_status: str = Field(default="healthy", description="Health status")
    
    @validator('health_status')
    def determine_health_status(cls, v, values):
        """Determine health status based on score."""
        score = values.get('score', 0)
        if score >= 75:
            return "healthy"
        elif score >= 50:
            return "degraded"
        else:
            return "critical"


class OverallScore(BaseModel):
    """Overall system health score."""
    overall: float = Field(..., ge=0, le=100, description="Overall health score")
    trend_7d: Optional[float] = Field(None, description="7-day trend")
    trend_30d: Optional[float] = Field(None, description="30-day trend")
    pillars: Dict[str, PillarScore] = Field(default_factory=dict, description="Pillar scores")
    last_updated: int = Field(..., description="Last update timestamp")
    data_freshness: str = Field(default="fresh", description="Data freshness indicator")
    alerts: List[str] = Field(default_factory=list, description="Active alerts")


class TimeSeriesPoint(BaseModel):
    """Time series data point."""
    timestamp: int = Field(..., description="Unix timestamp")
    value: float = Field(..., description="Metric value")
    
    @validator('timestamp')
    def validate_timestamp(cls, v):
        """Ensure timestamp is reasonable."""
        now = int(time.time())
        if v > now + 86400:  # Not more than 1 day in future
            raise ValueError("Timestamp too far in future")
        if v < now - (365 * 86400 * 5):  # Not more than 5 years old
            raise ValueError("Timestamp too old")
        return v


class TimeSeriesResponse(BaseModel):
    """Time series data response."""
    kind: str = Field(..., description="Data type")
    id: str = Field(..., description="Metric/pillar ID")
    days: int = Field(..., description="Number of days")
    data: List[TimeSeriesPoint] = Field(default_factory=list, description="Time series data")
    statistics: Dict[str, float] = Field(default_factory=dict, description="Statistical summary")


class CacheManager:
    """Simple cache manager with Redis support."""
    
    def __init__(self):
        self.redis_client = None
        self.memory_cache = {}
        self.cache_ttl = 60  # seconds
        
        try:
            self.redis_client = redis.Redis(
                host=os.getenv('REDIS_HOST', 'localhost'),
                port=int(os.getenv('REDIS_PORT', 6379)),
                db=0,
                decode_responses=True,
                socket_connect_timeout=2
            )
            self.redis_client.ping()
            logger.info("Redis cache connected")
        except Exception as e:
            logger.warning(f"Redis not available, using memory cache: {e}")
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        # Try Redis first
        if self.redis_client:
            try:
                value = self.redis_client.get(key)
                if value:
                    cache_hits.labels(endpoint=key.split(':')[0]).inc()
                    return json.loads(value)
            except Exception as e:
                logger.debug(f"Redis get error: {e}")
        
        # Fallback to memory cache
        if key in self.memory_cache:
            value, expiry = self.memory_cache[key]
            if time.time() < expiry:
                cache_hits.labels(endpoint=key.split(':')[0]).inc()
                return value
            else:
                del self.memory_cache[key]
        
        cache_misses.labels(endpoint=key.split(':')[0]).inc()
        return None
    
    async def set(self, key: str, value: Any, ttl: int = None) -> None:
        """Set value in cache."""
        ttl = ttl or self.cache_ttl
        
        # Set in Redis
        if self.redis_client:
            try:
                self.redis_client.setex(key, ttl, json.dumps(value, default=str))
            except Exception as e:
                logger.debug(f"Redis set error: {e}")
        
        # Also set in memory cache
        self.memory_cache[key] = (value, time.time() + ttl)
    
    async def invalidate(self, pattern: str) -> None:
        """Invalidate cache entries matching pattern."""
        # Clear from Redis
        if self.redis_client:
            try:
                for key in self.redis_client.scan_iter(match=pattern):
                    self.redis_client.delete(key)
            except Exception as e:
                logger.debug(f"Redis invalidate error: {e}")
        
        # Clear from memory cache
        keys_to_delete = [k for k in self.memory_cache.keys() if pattern.replace('*', '') in k]
        for key in keys_to_delete:
            del self.memory_cache[key]


# Create cache manager instance
cache = CacheManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting Bitcoin Health Scorecard API v2")
    
    # Initialize background tasks
    asyncio.create_task(cleanup_old_data())
    asyncio.create_task(warm_cache())
    
    yield
    
    # Shutdown
    logger.info("Shutting down Bitcoin Health Scorecard API")


# Create FastAPI app with production settings
app = FastAPI(
    title="Bitcoin Health Scorecard API",
    description="Production-grade Bitcoin network health monitoring API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    default_response_class=ORJSONResponse,
    lifespan=lifespan
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("ALLOWED_HOSTS", "*").split(",")
)

# Add rate limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Middleware for metrics and logging
@app.middleware("http")
async def add_metrics(request: Request, call_next):
    """Add metrics and logging to all requests."""
    start_time = time.time()
    active_requests.inc()
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Record metrics
        request_count.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        
        request_duration.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
        
        # Add custom headers
        response.headers["X-Response-Time"] = f"{duration:.3f}"
        response.headers["X-API-Version"] = "2.0.0"
        
        return response
        
    except Exception as e:
        error_count.labels(type=type(e).__name__).inc()
        raise
        
    finally:
        active_requests.dec()


@app.get("/", tags=["General"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Bitcoin Health Scorecard API",
        "version": "2.0.0",
        "status": "operational",
        "documentation": "/docs",
        "endpoints": {
            "health": "/health",
            "scores": "/api/v2/score/latest",
            "timeseries": "/api/v2/score/timeseries",
            "metrics": "/api/v2/metrics/{metric_id}",
            "pillars": "/api/v2/pillars",
            "alerts": "/api/v2/alerts"
        }
    }


@app.get("/health", response_model=HealthResponse, tags=["General"])
@limiter.limit("10/minute")
async def health_check(request: Request):
    """Comprehensive health check endpoint."""
    try:
        # Check database
        db_status = "healthy"
        try:
            version = get_meta_config('version')
        except:
            db_status = "unhealthy"
        
        # Check cache
        cache_status = "healthy"
        try:
            await cache.set("health_check", True, ttl=1)
            await cache.get("health_check")
        except:
            cache_status = "degraded"
        
        # Check collectors
        collectors = {}
        collector_status = execute_query(
            "SELECT collector, last_success, consecutive_failures FROM collection_status"
        )
        
        for status in collector_status:
            if status['consecutive_failures'] == 0:
                collectors[status['collector']] = "healthy"
            elif status['consecutive_failures'] < 3:
                collectors[status['collector']] = "degraded"
            else:
                collectors[status['collector']] = "unhealthy"
        
        return HealthResponse(
            status="healthy" if db_status == "healthy" else "degraded",
            version=version or "2.0.0",
            timestamp=int(time.time()),
            database=db_status,
            cache=cache_status,
            collectors=collectors
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unavailable")


@app.get("/api/v2/score/latest", response_model=OverallScore, tags=["Scores"])
@limiter.limit("30/minute")
async def get_latest_score(request: Request, use_cache: bool = True):
    """Get the latest overall and pillar scores with caching."""
    cache_key = "score:latest"
    
    # Check cache
    if use_cache:
        cached = await cache.get(cache_key)
        if cached:
            return OverallScore(**cached)
    
    try:
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
        
        # Get pillar scores with validation
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
        
        # Check data freshness
        age_seconds = int(time.time()) - overall['ts']
        if age_seconds < 3600:
            freshness = "fresh"
        elif age_seconds < 86400:
            freshness = "recent"
        else:
            freshness = "stale"
        
        # Generate alerts
        alerts = []
        if overall['score'] < 30:
            alerts.append("Critical: Overall health score below 30")
        for pillar_id, pillar in pillars.items():
            if pillar.score < 40:
                alerts.append(f"Warning: {pillar.name} score below 40")
        
        response = OverallScore(
            overall=overall['score'],
            trend_7d=overall.get('trend_7d'),
            trend_30d=overall.get('trend_30d'),
            pillars=pillars,
            last_updated=overall['ts'],
            data_freshness=freshness,
            alerts=alerts
        )
        
        # Cache the response
        await cache.set(cache_key, response.dict(), ttl=60)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting latest scores: {e}")
        error_count.labels(type="score_fetch").inc()
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v2/score/timeseries", response_model=TimeSeriesResponse, tags=["Scores"])
@limiter.limit("20/minute")
async def get_score_timeseries(
    request: Request,
    kind: str = Query(..., regex="^(metric|pillar|overall)$", description="Type of score"),
    id: str = Query(..., description="ID of the metric/pillar"),
    days: int = Query(30, ge=1, le=365, description="Number of days of history"),
    use_cache: bool = Query(True, description="Use cached data")
):
    """Get time series data for a score with statistics."""
    cache_key = f"timeseries:{kind}:{id}:{days}"
    
    # Check cache
    if use_cache:
        cached = await cache.get(cache_key)
        if cached:
            return TimeSeriesResponse(**cached)
    
    try:
        cutoff = int(time.time()) - (days * 86400)
        
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
        
        # Convert to time series points
        data_points = [
            TimeSeriesPoint(timestamp=s['ts'], value=s['score'])
            for s in scores
        ]
        
        # Calculate statistics
        values = [s['score'] for s in scores]
        statistics = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
            "median": sorted(values)[len(values) // 2],
            "std_dev": (sum((x - sum(values)/len(values))**2 for x in values) / len(values))**0.5,
            "latest": values[-1] if values else 0
        }
        
        response = TimeSeriesResponse(
            kind=kind,
            id=id,
            days=days,
            data=data_points,
            statistics=statistics
        )
        
        # Cache the response
        await cache.set(cache_key, response.dict(), ttl=300)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting timeseries: {e}")
        error_count.labels(type="timeseries_fetch").inc()
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v2/metrics/{metric_id}", tags=["Metrics"])
@limiter.limit("30/minute")
async def get_metric_details(request: Request, metric_id: str):
    """Get detailed information about a specific metric."""
    try:
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
        
        # Get 24h statistics
        history = get_metric_history(metric_id, days=1)
        if history:
            values = [h['value'] for h in history]
            stats_24h = {
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "count": len(values)
            }
        else:
            stats_24h = None
        
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
            "stats_24h": stats_24h,
            "last_updated": latest_metric['ts'] if latest_metric else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metric details: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/v2/alerts", tags=["Monitoring"])
async def get_active_alerts():
    """Get active system alerts based on thresholds."""
    alerts = []
    
    try:
        # Check overall score
        overall = execute_query(
            "SELECT score FROM scores WHERE kind='overall' ORDER BY ts DESC LIMIT 1"
        )
        if overall and overall[0]['score'] < 30:
            alerts.append({
                "level": "critical",
                "type": "overall_health",
                "message": f"Overall health critically low: {overall[0]['score']:.1f}",
                "timestamp": int(time.time())
            })
        
        # Check pillar scores
        pillars = execute_query(
            """
            SELECT id, score FROM scores 
            WHERE kind='pillar' 
            AND ts = (SELECT MAX(ts) FROM scores WHERE kind='pillar')
            """
        )
        
        for pillar in pillars:
            if pillar['score'] < 40:
                alerts.append({
                    "level": "warning",
                    "type": "pillar_health",
                    "pillar": pillar['id'],
                    "message": f"{pillar['id']} health low: {pillar['score']:.1f}",
                    "timestamp": int(time.time())
                })
        
        # Check data freshness
        last_collection = execute_query(
            "SELECT MAX(ts) as last_ts FROM raw_mempool_snapshot"
        )
        if last_collection:
            age_hours = (time.time() - last_collection[0]['last_ts']) / 3600
            if age_hours > 2:
                alerts.append({
                    "level": "warning",
                    "type": "data_freshness",
                    "message": f"Data is {age_hours:.1f} hours old",
                    "timestamp": int(time.time())
                })
        
        return {"alerts": alerts, "count": len(alerts)}
        
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        return {"alerts": [], "count": 0, "error": str(e)}


@app.get("/metrics", tags=["Monitoring"])
async def get_prometheus_metrics():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type="text/plain")


# Mount static files for frontend
if os.path.exists("frontend"):
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


# Background tasks
async def cleanup_old_data():
    """Periodically clean up old data."""
    while True:
        try:
            # Clean data older than 90 days
            cutoff = int(time.time()) - (90 * 86400)
            execute_query("DELETE FROM metrics WHERE ts < ?", (cutoff,))
            execute_query("DELETE FROM scores WHERE ts < ?", (cutoff,))
            logger.info("Cleaned up old data")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        
        await asyncio.sleep(86400)  # Run daily


async def warm_cache():
    """Periodically warm the cache with frequently accessed data."""
    while True:
        try:
            # Warm latest scores
            await get_latest_score(None, use_cache=False)
            logger.info("Cache warmed")
        except Exception as e:
            logger.error(f"Cache warming error: {e}")
        
        await asyncio.sleep(300)  # Run every 5 minutes


if __name__ == "__main__":
    import uvicorn
    import json
    
    uvicorn.run(
        "app.api.server_v2:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_level="info",
        access_log=True
    )
