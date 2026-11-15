"""Cost calculation and pricing management tests."""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import ApiRequest, ModelPricing, User
from app.providers.base import Usage
from app.services.pricing import estimate_cost, resolve_pricing
from app.services.usage import RequestRecord, record_request


def _user(db) -> User:
    user = User(email=f"{uuid.uuid4().hex[:6]}@x.io", password_hash="x")
    db.add(user)
    db.commit()
    return user


def test_resolve_exact_and_dated_variants_but_not_other_families(db):
    user = _user(db)
    assert resolve_pricing(db, user.id, "openai", "gpt-4o").model == "gpt-4o"
    assert resolve_pricing(db, user.id, "openai", "gpt-4o-2024-08-06").model == "gpt-4o"
    assert resolve_pricing(db, user.id, "openai", "gpt-4o-mini").model == "gpt-4o-mini"
    assert resolve_pricing(db, user.id, "anthropic", "claude-sonnet-4-5-20250929").model == "claude-sonnet-4-5"
    assert resolve_pricing(db, user.id, "gemini", "models/gemini-2.5-flash").model == "gemini-2.5-flash"
    assert resolve_pricing(db, user.id, "gemini", "gemini-2.5-flash-preview-05-20").model == "gemini-2.5-flash"
    # A different model family must not inherit a shorter entry's price.
    assert resolve_pricing(db, user.id, "openai", "gpt-4o-audio-preview") is None
    assert resolve_pricing(db, user.id, "anthropic", "claude-opus-4-7") is None
    assert resolve_pricing(db, user.id, "openai", "") is None
    # Provider must match.
    assert resolve_pricing(db, user.id, "anthropic", "gpt-4o") is None


def test_user_override_wins_and_is_private(db):
    alice, bob = _user(db), _user(db)
    db.add(
        ModelPricing(
            user_id=alice.id,
            provider="openai",
            model="gpt-4o",
            input_price_per_mtok=Decimal("1"),
            output_price_per_mtok=Decimal("2"),
            source="manual",
            verified=True,
        )
    )
    db.commit()
    assert resolve_pricing(db, alice.id, "openai", "gpt-4o").input_price_per_mtok == Decimal("1")
    assert resolve_pricing(db, bob.id, "openai", "gpt-4o").input_price_per_mtok == Decimal("2.5")


def test_estimate_cost_math_and_unknown():
    p = ModelPricing(
        provider="openai", model="m", input_price_per_mtok=Decimal("3"), output_price_per_mtok=Decimal("15")
    )
    est = estimate_cost(Usage(1234, 567), p)
    assert est.input_cost == Decimal("0.00370200")
    assert est.output_cost == Decimal("0.00850500")
    assert est.total_cost == Decimal("0.01220700") and est.status == "estimated"
    zero = estimate_cost(Usage(0, 0), p)
    assert zero.total_cost == Decimal("0")
    unknown = estimate_cost(Usage(10, 10), None)
    assert unknown.total_cost is None and unknown.status == "unknown"


def test_pricing_snapshot_is_preserved_after_price_change(db):
    user = _user(db)
    record_request(
        db,
        RequestRecord(
            "req_snapshot01",
            user.id,
            None,
            None,
            "openai",
            "gpt-4o",
            "chat",
            False,
            200,
            100,
            Usage(1_000_000, 0),
        ),
    )
    row = db.scalar(select(ApiRequest))
    assert row.input_price_per_mtok == Decimal("2.5") and row.cost_total_usd == Decimal("2.5")
    catalog = db.scalar(select(ModelPricing).where(ModelPricing.model == "gpt-4o", ModelPricing.user_id.is_(None)))
    catalog.input_price_per_mtok = Decimal("9")
    db.commit()
    db.refresh(row)
    assert row.input_price_per_mtok == Decimal("2.5") and row.cost_total_usd == Decimal("2.5")


def test_pricing_api_crud_and_catalog_is_read_only(client: TestClient, user):
    h = user["headers"]
    listing = client.get("/api/v1/pricing", headers=h).json()
    catalog_entry = next(p for p in listing if p["model"] == "gpt-4o")
    assert catalog_entry["scope"] == "catalog" and catalog_entry["verified"] is False
    assert client.patch(f"/api/v1/pricing/{catalog_entry['id']}", json={"verified": True}, headers=h).status_code == 404
    assert client.delete(f"/api/v1/pricing/{catalog_entry['id']}", headers=h).status_code == 404

    created = client.post(
        "/api/v1/pricing",
        json={
            "provider": "openai",
            "model": "my-finetune",
            "input_price_per_mtok": "3.5",
            "output_price_per_mtok": "7",
            "notes": "contract price",
        },
        headers=h,
    )
    assert created.status_code == 201 and created.json()["scope"] == "custom"
    dup = client.post(
        "/api/v1/pricing",
        json={
            "provider": "openai",
            "model": "my-finetune",
            "input_price_per_mtok": "1",
            "output_price_per_mtok": "1",
        },
        headers=h,
    )
    assert dup.status_code == 409
    pid = created.json()["id"]
    upd = client.patch(f"/api/v1/pricing/{pid}", json={"output_price_per_mtok": "8", "verified": True}, headers=h)
    assert Decimal(upd.json()["output_price_per_mtok"]) == Decimal("8") and upd.json()["verified"] is True

    preview = client.get(
        "/api/v1/pricing/preview",
        params={
            "provider": "openai",
            "model": "my-finetune",
            "input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
        },
        headers=h,
    ).json()
    assert Decimal(preview["total_cost_usd"]) == Decimal("11.5") and preview["status"] == "estimated"
    assert client.delete(f"/api/v1/pricing/{pid}", headers=h).status_code == 204

    bad = client.post(
        "/api/v1/pricing",
        json={"provider": "openai", "model": "x", "input_price_per_mtok": "-1", "output_price_per_mtok": "1"},
        headers=h,
    )
    assert bad.status_code == 422
