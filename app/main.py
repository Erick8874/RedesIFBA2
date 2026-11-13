from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import asyncpg
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://cafe:local-dev-only@127.0.0.1:5432/cafeplanalto",
)
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total de requisições HTTP da API.",
    ("rota", "metodo", "status"),
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "Duração das requisições HTTP da API.",
    ("rota",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2.5, 5),
)
ORDERS_CREATED = Counter("pedidos_criados_total", "Pedidos persistidos com sucesso.")
ORDER_REVENUE = Counter(
    "pedidos_valor_reais_total",
    "Faturamento acumulado dos pedidos, em reais.",
)
DB_CONNECTIONS_IN_USE = Gauge(
    "db_pool_conexoes_em_uso",
    "Conexões do pool PostgreSQL atualmente emprestadas.",
)

logger = logging.getLogger("cafeplanalto.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "nivel": record.levelname,
            "mensagem": record.getMessage(),
        }
        if record.exc_info:
            payload["erro"] = self.formatException(record.exc_info)
        payload.update(getattr(record, "context", {}))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


for handler in logging.getLogger().handlers:
    handler.setFormatter(JsonLogFormatter())


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    produto_id: int = Field(gt=0)
    quantidade: int = Field(ge=1, le=100)


class ChaosSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latencia_ms: int = Field(default=0, ge=0, le=5000)
    taxa_erro: float = Field(default=0, ge=0, le=1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=int(os.getenv("DB_POOL_MAX_SIZE", "10")),
        command_timeout=5,
    )
    async with app.state.pool.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS produtos (
                id SERIAL PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE,
                preco_centavos INTEGER NOT NULL CHECK (preco_centavos >= 0)
            );
            CREATE TABLE IF NOT EXISTS pedidos (
                id BIGSERIAL PRIMARY KEY,
                produto_id INTEGER NOT NULL REFERENCES produtos(id),
                quantidade INTEGER NOT NULL CHECK (quantidade > 0),
                valor_centavos BIGINT NOT NULL CHECK (valor_centavos >= 0),
                criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            INSERT INTO produtos (nome, preco_centavos)
            VALUES
                ('Café Especial Mogiana 250g', 3290),
                ('Café Especial Chapada 250g', 3590),
                ('Kit Degustação da Casa', 8990)
            ON CONFLICT (nome) DO NOTHING;
            """
        )
    yield
    await app.state.pool.close()


app = FastAPI(title="Café Planalto API", version="1.0.0", lifespan=lifespan)


@asynccontextmanager
async def database_connection(request: Request):
    pool: asyncpg.Pool = request.app.state.pool
    connection = await pool.acquire()
    DB_CONNECTIONS_IN_USE.inc()
    try:
        yield connection
    finally:
        DB_CONNECTIONS_IN_USE.dec()
        await pool.release(connection)


def route_name(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    trace_id = request.headers.get("x-trace-id")
    if not trace_id:
        traceparent = request.headers.get("traceparent", "")
        trace_id = traceparent.split("-")[1] if len(traceparent.split("-")) > 1 else None
    try:
        excluded = {"/health", "/metrics", "/admin/caos"}
        if request.url.path not in excluded:
            await asyncio.sleep(app.state.chaos.latencia_ms / 1000)
            if random.random() < app.state.chaos.taxa_erro:
                status = 500
                return JSONResponse(status_code=500, content={"detail": "Falha injetada"})
        response = await call_next(request)
        status = response.status_code
        return response
    except Exception:
        logger.error(
            "Falha ao processar requisição",
            exc_info=True,
        )
        status = 500
        return JSONResponse(status_code=500, content={"detail": "Erro interno"})
    finally:
        elapsed = time.perf_counter() - started
        route = route_name(request)
        if route not in {"/health", "/metrics", "/admin/caos", "/ready"}:
            HTTP_REQUESTS.labels(route, request.method, str(status)).inc()
            HTTP_DURATION.labels(route).observe(elapsed)
        logger.info(
            "Requisição HTTP",
            extra={
                "context": {
                    "rota": route,
                    "metodo": request.method,
                    "status": status,
                    "duracao_ms": round(elapsed * 1000, 3),
                    "trace_id": trace_id,
                }
            },
        )


app.state.chaos = ChaosSettings()


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def storefront() -> str:
    return """<!doctype html>
<html lang="pt-BR"><meta charset="utf-8"><title>Café Planalto</title>
<body><main><h1>Café Planalto</h1><p>Loja de cafés especiais.</p>
<button id="load">Ver catálogo</button><pre id="catalog"></pre>
<script>
document.querySelector('#load').onclick=async()=>{
 const r=await fetch('/produtos'); document.querySelector('#catalog').textContent=await r.text();
};
</script></main></body></html>"""


@app.get("/produtos")
async def list_products(request: Request) -> list[dict[str, Any]]:
    try:
        async with database_connection(request) as connection:
            rows = await connection.fetch(
                "SELECT id, nome, preco_centavos FROM produtos ORDER BY id"
            )
    except (asyncpg.PostgresError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc
    return [
        {
            "id": row["id"],
            "nome": row["nome"],
            "preco_reais": round(row["preco_centavos"] / 100, 2),
        }
        for row in rows
    ]


@app.post("/pedidos", status_code=201)
async def create_order(order: OrderRequest, request: Request) -> dict[str, Any]:
    try:
        async with database_connection(request) as connection:
            async with connection.transaction():
                product = await connection.fetchrow(
                    "SELECT id, preco_centavos FROM produtos WHERE id = $1",
                    order.produto_id,
                )
                if product is None:
                    raise HTTPException(status_code=404, detail="Produto não encontrado")
                total = product["preco_centavos"] * order.quantidade
                row = await connection.fetchrow(
                    """
                    INSERT INTO pedidos (produto_id, quantidade, valor_centavos)
                    VALUES ($1, $2, $3)
                    RETURNING id, criado_em
                    """,
                    order.produto_id,
                    order.quantidade,
                    total,
                )
    except HTTPException:
        raise
    except (asyncpg.PostgresError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc
    ORDERS_CREATED.inc()
    ORDER_REVENUE.inc(total / 100)
    return {
        "pedido_id": row["id"],
        "produto_id": order.produto_id,
        "quantidade": order.quantidade,
        "valor_reais": round(total / 100, 2),
        "criado_em": row["criado_em"].isoformat(),
    }


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    try:
        async with database_connection(request) as connection:
            await connection.fetchval("SELECT 1")
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Banco de dados indisponível") from exc
    return {"status": "ok", "database": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/admin/caos")
async def configure_chaos(
    settings: ChaosSettings,
    x_admin_token: str | None = Header(default=None),
) -> dict[str, int | float | str]:
    if not ADMIN_TOKEN or not x_admin_token or not hmac.compare_digest(
        ADMIN_TOKEN.encode(), x_admin_token.encode()
    ):
        raise HTTPException(status_code=403, detail="Token administrativo inválido")
    app.state.chaos = settings
    return {
        "status": "atualizado",
        "latencia_ms": settings.latencia_ms,
        "taxa_erro": settings.taxa_erro,
    }


@app.get("/ready", include_in_schema=False)
async def ready() -> PlainTextResponse:
    return PlainTextResponse("ready")
