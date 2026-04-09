import time
from typing import Awaitable, Callable

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse

from src.common.logging import get_logger
logger = get_logger(__name__)


MAINTENANCE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Ontos — Maintenance</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:#0f172a;color:#e2e8f0;display:flex;align-items:center;
       justify-content:center;min-height:100vh;padding:1rem}
  .card{background:#1e293b;border:1px solid #334155;border-radius:12px;
        padding:2.5rem;max-width:520px;width:100%;text-align:center;
        box-shadow:0 25px 50px -12px rgba(0,0,0,.5)}
  h1{font-size:1.5rem;margin-bottom:.75rem;color:#f8fafc}
  .icon{font-size:2.5rem;margin-bottom:1rem}
  .detail{background:#0f172a;border:1px solid #334155;border-radius:8px;
          padding:.75rem 1rem;margin:1rem 0;font-family:monospace;font-size:.85rem;
          color:#fbbf24;text-align:left;word-break:break-word;max-height:120px;
          overflow-y:auto}
  p{color:#94a3b8;line-height:1.6;margin-bottom:1rem;font-size:.95rem}
  button{background:#6366f1;color:#fff;border:none;border-radius:8px;
         padding:.75rem 2rem;font-size:1rem;cursor:pointer;transition:all .15s;
         font-weight:500}
  button:hover{background:#818cf8;transform:translateY(-1px)}
  button:active{transform:translateY(0)}
  button:disabled{opacity:.6;cursor:not-allowed;transform:none}
  .status{margin-top:1rem;font-size:.85rem;min-height:1.2em}
  .status.ok{color:#34d399}
  .status.err{color:#f87171}
  .auto{color:#64748b;font-size:.8rem;margin-top:1.5rem}
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#9888;&#65039;</div>
  <h1>Service Temporarily Unavailable</h1>
  <p>The application could not connect to the database during startup.
     This is usually temporary — for example, a missing access grant or
     a network issue.</p>
  <div class="detail" id="err">Loading error details&hellip;</div>
  <button id="btn" onclick="retry()">Retry Connection</button>
  <div class="status" id="msg"></div>
  <div class="auto">Auto-retrying every 30 seconds&hellip;</div>
</div>
<script>
  const btn=document.getElementById('btn'),
        msg=document.getElementById('msg'),
        err=document.getElementById('err');

  fetch('/api/health').then(r=>r.json()).then(h=>{
    err.textContent=h.db_error||'Unknown error';
  }).catch(()=>{err.textContent='Could not fetch error details';});

  async function retry(){
    btn.disabled=true; msg.className='status'; msg.textContent='Retrying\u2026';
    try{
      const r=await fetch('/api/health/retry',{method:'POST'});
      const d=await r.json();
      if(r.ok){msg.className='status ok';msg.textContent='Connected! Reloading\u2026';
        setTimeout(()=>location.reload(),1000);
      }else{msg.className='status err';msg.textContent=d.detail||'Retry failed';
        err.textContent=d.detail||err.textContent;btn.disabled=false;}
    }catch(e){msg.className='status err';msg.textContent='Network error';btn.disabled=false;}
  }
  setInterval(()=>{if(!btn.disabled)retry();},30000);
</script>
</body>
</html>"""

class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests and responses."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.debug(f"{request.method} {request.url.path} completed in {process_time:.3f}s")
        return response

class MaintenanceMiddleware(BaseHTTPMiddleware):
    """Serves a maintenance page when the database is not available.

    The health endpoint is always allowed through so the retry button works.
    """

    PASSTHROUGH_PREFIXES = ("/api/health",)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        health = getattr(request.app.state, 'health', {})
        if not health.get('db_ok', True):
            path = request.url.path
            if any(path.startswith(p) for p in self.PASSTHROUGH_PREFIXES):
                return await call_next(request)
            accept = request.headers.get('accept', '')
            if 'text/html' in accept:
                return HTMLResponse(MAINTENANCE_HTML, status_code=503)
            return JSONResponse(
                {"error": "maintenance", "detail": health.get("db_error")},
                status_code=503,
            )
        return await call_next(request)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware for handling errors."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        try:
            return await call_next(request)
        except HTTPException as http_exc: # Handle FastAPI's HTTPExceptions specifically
             logger.warning(f"HTTPException caught by middleware: {http_exc.status_code} {http_exc.detail}")
             # Re-raise HTTPException so FastAPI's default handler can format it
             raise http_exc
        except Exception as e:
            logger.error(f"Unhandled error processing request {request.method} {request.url.path}: {e!s}", exc_info=True)
            # Return a generic 500 response for unhandled exceptions
            return Response(
                content="Internal Server Error",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                media_type="text/plain"
            )
