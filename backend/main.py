"""
QA Dashboard Backend - FastAPI Application
Collects and displays test results from Playwright and API tests
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
import asyncpg
import redis.asyncio as aioredis
import os
import json
import httpx

app = FastAPI(
    title="QA Dashboard API",
    description="Test results aggregation and visualization",
    version="1.0.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/qa_dashboard")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Database connection pool
db_pool = None
redis_client = None


# ============ Models ============

class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    FLAKY = "flaky"


class TestType(str, Enum):
    PLAYWRIGHT = "playwright"
    API = "api"
    UNIT = "unit"
    INTEGRATION = "integration"


class TestResult(BaseModel):
    """Single test result"""
    name: str
    status: TestStatus
    duration_ms: int
    test_type: TestType
    suite: str = "default"
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    retry_count: int = 0
    browser: Optional[str] = None  # For Playwright tests
    tags: List[str] = []


class TestRun(BaseModel):
    """A complete test run (multiple test results)"""
    run_id: Optional[str] = None
    project: str
    branch: str = "main"
    commit_sha: Optional[str] = None
    triggered_by: str = "manual"
    results: List[TestResult]
    environment: str = "staging"
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class TestRunSummary(BaseModel):
    """Summary of a test run"""
    run_id: str
    project: str
    branch: str
    total: int
    passed: int
    failed: int
    skipped: int
    flaky: int
    pass_rate: float
    duration_ms: int
    started_at: datetime
    status: str


class TrendData(BaseModel):
    """Test trend data point"""
    date: str
    pass_rate: float
    total_tests: int
    failed_tests: int


# ============ Database ============

async def init_db():
    """Initialize database connection and create tables"""
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS test_runs (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(100) UNIQUE NOT NULL,
                project VARCHAR(100) NOT NULL,
                branch VARCHAR(100) DEFAULT 'main',
                commit_sha VARCHAR(40),
                triggered_by VARCHAR(100) DEFAULT 'manual',
                environment VARCHAR(50) DEFAULT 'staging',
                total INTEGER NOT NULL,
                passed INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                skipped INTEGER NOT NULL,
                flaky INTEGER DEFAULT 0,
                duration_ms INTEGER NOT NULL,
                started_at TIMESTAMP NOT NULL,
                finished_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS test_results (
                id SERIAL PRIMARY KEY,
                run_id VARCHAR(100) REFERENCES test_runs(run_id),
                name VARCHAR(500) NOT NULL,
                status VARCHAR(20) NOT NULL,
                duration_ms INTEGER NOT NULL,
                test_type VARCHAR(50) NOT NULL,
                suite VARCHAR(200) DEFAULT 'default',
                error_message TEXT,
                stack_trace TEXT,
                retry_count INTEGER DEFAULT 0,
                browser VARCHAR(50),
                tags JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_test_runs_project ON test_runs(project);
        ''')
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_test_runs_created ON test_runs(created_at);
        ''')
        await conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_test_results_status ON test_results(status);
        ''')


async def init_redis():
    """Initialize Redis connection"""
    global redis_client
    redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)


# ============ Notification ============

async def send_slack_notification(run_summary: dict):
    """Send Slack notification for failed test runs"""
    if not SLACK_WEBHOOK_URL:
        return
    
    if run_summary["failed"] == 0:
        return  # Only notify on failures
    
    color = "#ff0000" if run_summary["failed"] > 0 else "#36a64f"
    
    message = {
        "attachments": [{
            "color": color,
            "title": f"🧪 Test Run: {run_summary['project']} ({run_summary['branch']})",
            "fields": [
                {"title": "Status", "value": f"❌ {run_summary['failed']} failed", "short": True},
                {"title": "Pass Rate", "value": f"{run_summary['pass_rate']:.1f}%", "short": True},
                {"title": "Total Tests", "value": str(run_summary['total']), "short": True},
                {"title": "Duration", "value": f"{run_summary['duration_ms']/1000:.1f}s", "short": True},
            ],
            "footer": f"Run ID: {run_summary['run_id']}",
            "ts": int(datetime.now().timestamp())
        }]
    }
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(SLACK_WEBHOOK_URL, json=message)
        except Exception as e:
            print(f"Failed to send Slack notification: {e}")


# ============ API Endpoints ============

@app.on_event("startup")
async def startup():
    await init_db()
    await init_redis()


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.close()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }


@app.post("/api/v1/runs", response_model=TestRunSummary)
async def create_test_run(test_run: TestRun, background_tasks: BackgroundTasks):
    """Submit a new test run with results"""
    import uuid
    
    run_id = test_run.run_id or str(uuid.uuid4())[:8]
    started_at = test_run.started_at or datetime.now()
    finished_at = test_run.finished_at or datetime.now()
    
    # Calculate summary
    total = len(test_run.results)
    passed = sum(1 for r in test_run.results if r.status == TestStatus.PASSED)
    failed = sum(1 for r in test_run.results if r.status == TestStatus.FAILED)
    skipped = sum(1 for r in test_run.results if r.status == TestStatus.SKIPPED)
    flaky = sum(1 for r in test_run.results if r.status == TestStatus.FLAKY)
    duration_ms = sum(r.duration_ms for r in test_run.results)
    pass_rate = (passed / total * 100) if total > 0 else 0
    
    async with db_pool.acquire() as conn:
        # Insert test run
        await conn.execute('''
            INSERT INTO test_runs 
            (run_id, project, branch, commit_sha, triggered_by, environment, 
             total, passed, failed, skipped, flaky, duration_ms, started_at, finished_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ''', run_id, test_run.project, test_run.branch, test_run.commit_sha,
            test_run.triggered_by, test_run.environment, total, passed, failed,
            skipped, flaky, duration_ms, started_at, finished_at)
        
        # Insert individual results
        for result in test_run.results:
            await conn.execute('''
                INSERT INTO test_results
                (run_id, name, status, duration_ms, test_type, suite, 
                 error_message, stack_trace, retry_count, browser, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ''', run_id, result.name, result.status.value, result.duration_ms,
                result.test_type.value, result.suite, result.error_message,
                result.stack_trace, result.retry_count, result.browser,
                json.dumps(result.tags))
    
    # Invalidate cache
    await redis_client.delete(f"runs:{test_run.project}")
    await redis_client.delete(f"trends:{test_run.project}")
    
    summary = {
        "run_id": run_id,
        "project": test_run.project,
        "branch": test_run.branch,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "flaky": flaky,
        "pass_rate": pass_rate,
        "duration_ms": duration_ms,
        "started_at": started_at,
        "status": "failed" if failed > 0 else "passed"
    }
    
    # Send notification in background
    background_tasks.add_task(send_slack_notification, summary)
    
    return TestRunSummary(**summary)


@app.get("/api/v1/runs", response_model=List[TestRunSummary])
async def get_test_runs(
    project: Optional[str] = None,
    branch: Optional[str] = None,
    limit: int = 20
):
    """Get recent test runs"""
    cache_key = f"runs:{project or 'all'}"
    
    # Check cache
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    query = '''
        SELECT run_id, project, branch, total, passed, failed, skipped, flaky,
               duration_ms, started_at,
               CASE WHEN failed > 0 THEN 'failed' ELSE 'passed' END as status,
               ROUND(passed::numeric / NULLIF(total, 0) * 100, 2) as pass_rate
        FROM test_runs
        WHERE ($1::varchar IS NULL OR project = $1)
          AND ($2::varchar IS NULL OR branch = $2)
        ORDER BY started_at DESC
        LIMIT $3
    '''
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(query, project, branch, limit)
    
    results = [
        TestRunSummary(
            run_id=row['run_id'],
            project=row['project'],
            branch=row['branch'],
            total=row['total'],
            passed=row['passed'],
            failed=row['failed'],
            skipped=row['skipped'],
            flaky=row['flaky'],
            pass_rate=float(row['pass_rate'] or 0),
            duration_ms=row['duration_ms'],
            started_at=row['started_at'],
            status=row['status']
        )
        for row in rows
    ]
    
    # Cache for 60 seconds
    await redis_client.setex(cache_key, 60, json.dumps([r.dict() for r in results], default=str))
    
    return results


@app.get("/api/v1/runs/{run_id}")
async def get_test_run_detail(run_id: str):
    """Get detailed test run with all results"""
    async with db_pool.acquire() as conn:
        run = await conn.fetchrow(
            'SELECT * FROM test_runs WHERE run_id = $1', run_id
        )
        if not run:
            raise HTTPException(status_code=404, detail="Test run not found")
        
        results = await conn.fetch(
            'SELECT * FROM test_results WHERE run_id = $1 ORDER BY status DESC, duration_ms DESC',
            run_id
        )
    
    return {
        "run": dict(run),
        "results": [dict(r) for r in results]
    }


@app.get("/api/v1/runs/{run_id}/failures")
async def get_failed_tests(run_id: str):
    """Get only failed tests for a run"""
    async with db_pool.acquire() as conn:
        results = await conn.fetch('''
            SELECT name, error_message, stack_trace, duration_ms, browser, suite
            FROM test_results 
            WHERE run_id = $1 AND status = 'failed'
            ORDER BY duration_ms DESC
        ''', run_id)
    
    return [dict(r) for r in results]


@app.get("/api/v1/trends/{project}", response_model=List[TrendData])
async def get_test_trends(project: str, days: int = 30):
    """Get test pass rate trends over time"""
    cache_key = f"trends:{project}"
    
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)
    
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT 
                DATE(started_at) as date,
                ROUND(AVG(passed::numeric / NULLIF(total, 0) * 100), 2) as pass_rate,
                SUM(total) as total_tests,
                SUM(failed) as failed_tests
            FROM test_runs
            WHERE project = $1 AND started_at > NOW() - INTERVAL '%s days'
            GROUP BY DATE(started_at)
            ORDER BY date DESC
        ''' % days, project)
    
    results = [
        TrendData(
            date=row['date'].isoformat(),
            pass_rate=float(row['pass_rate'] or 0),
            total_tests=row['total_tests'],
            failed_tests=row['failed_tests']
        )
        for row in rows
    ]
    
    await redis_client.setex(cache_key, 300, json.dumps([r.dict() for r in results]))
    
    return results


@app.get("/api/v1/stats/{project}")
async def get_project_stats(project: str):
    """Get overall project statistics"""
    async with db_pool.acquire() as conn:
        stats = await conn.fetchrow('''
            SELECT 
                COUNT(*) as total_runs,
                SUM(total) as total_tests,
                SUM(passed) as total_passed,
                SUM(failed) as total_failed,
                ROUND(AVG(passed::numeric / NULLIF(total, 0) * 100), 2) as avg_pass_rate,
                ROUND(AVG(duration_ms)) as avg_duration_ms
            FROM test_runs
            WHERE project = $1 AND started_at > NOW() - INTERVAL '30 days'
        ''', project)
        
        flaky_tests = await conn.fetch('''
            SELECT name, COUNT(*) as flaky_count
            FROM test_results
            WHERE run_id IN (SELECT run_id FROM test_runs WHERE project = $1)
              AND status = 'flaky'
            GROUP BY name
            ORDER BY flaky_count DESC
            LIMIT 10
        ''', project)
    
    return {
        "project": project,
        "total_runs": stats['total_runs'],
        "total_tests": stats['total_tests'],
        "total_passed": stats['total_passed'],
        "total_failed": stats['total_failed'],
        "avg_pass_rate": float(stats['avg_pass_rate'] or 0),
        "avg_duration_ms": int(stats['avg_duration_ms'] or 0),
        "top_flaky_tests": [dict(t) for t in flaky_tests]
    }


@app.get("/api/v1/projects")
async def get_projects():
    """Get list of all projects"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT DISTINCT project, 
                   COUNT(*) as run_count,
                   MAX(started_at) as last_run
            FROM test_runs
            GROUP BY project
            ORDER BY last_run DESC
        ''')
    
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
