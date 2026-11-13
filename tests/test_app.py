import asyncio

from pydantic import ValidationError
import pytest

from httpx import ASGITransport, AsyncClient

from app import main
from app.main import ChaosSettings, OrderRequest


async def make_request(method: str, path: str, **kwargs):
    async with AsyncClient(
        transport=ASGITransport(app=main.app),
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, **kwargs)


def test_order_request_rejects_invalid_quantity() -> None:
    with pytest.raises(ValidationError):
        OrderRequest(produto_id=1, quantidade=0)


def test_chaos_settings_accepts_assignment_failure_scenarios() -> None:
    latency = ChaosSettings(latencia_ms=800)
    errors = ChaosSettings(taxa_erro=0.2)
    assert latency.latencia_ms == 800
    assert errors.taxa_erro == 0.2


@pytest.mark.parametrize(
    "payload",
    [{"latencia_ms": -1}, {"latencia_ms": 5001}, {"taxa_erro": 1.1}],
)
def test_chaos_settings_reject_out_of_range_values(payload: dict[str, int | float]) -> None:
    with pytest.raises(ValidationError):
        ChaosSettings(**payload)


def test_chaos_endpoint_requires_token_and_updates_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "ADMIN_TOKEN", "test-token")
    denied = asyncio.run(
        make_request("POST", "/admin/caos", json={"latencia_ms": 800})
    )
    accepted = asyncio.run(
        make_request(
            "POST",
            "/admin/caos",
            headers={"X-Admin-Token": "test-token"},
            json={"latencia_ms": 800},
        )
    )

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["latencia_ms"] == 800


def test_metrics_endpoint_exports_required_series() -> None:
    response = asyncio.run(make_request("GET", "/metrics"))

    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text
    assert "pedidos_criados_total" in response.text
    assert "pedidos_valor_reais_total" in response.text
    assert "db_pool_conexoes_em_uso" in response.text
