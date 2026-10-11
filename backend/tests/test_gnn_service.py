"""R5: the app scoring live accounts with an exported window GNN."""

from dataclasses import asdict

import pytest

torch = pytest.importorskip("torch")

from app.gnn.sage import build_model  # noqa: E402
from app.graph.features_v2 import AMLWORLD_SCHEMA, WindowConfig  # noqa: E402
from app.models import Alert, GnnAccountScore  # noqa: E402
from app.services import gnn_v2_service  # noqa: E402
from tests.test_db_window import NOW, make_world  # noqa: E402


@pytest.fixture()
def exported_model(tmp_path, monkeypatch):
    """A tiny untrained checkpoint in the exported format, threshold 0 (flag all)."""
    torch.manual_seed(0)
    schema = AMLWORLD_SCHEMA
    model = build_model("edge", schema.node_dim, schema.edge_dim, 16, 2, 0.0)
    path = tmp_path / "aml_gnn_v2.pt"
    torch.save(
        {
            "model_name": "test_gnn", "variant": "edge",
            "state_dict": model.state_dict(),
            "config": {"node_dim": schema.node_dim, "edge_dim": schema.edge_dim, "hidden": 16, "layers": 2},
            "schema": schema.to_dict(), "window": asdict(WindowConfig()),
            "threshold": 0.0, "metrics": {"test": {"pr_auc": 0.1}}, "training_data": "test",
        },
        path,
    )
    monkeypatch.setattr(gnn_v2_service, "EXPORT_PATH", path)
    gnn_v2_service.get_model.cache_clear()
    yield path
    gnn_v2_service.get_model.cache_clear()


def test_status_without_a_model(monkeypatch, tmp_path):
    monkeypatch.setattr(gnn_v2_service, "EXPORT_PATH", tmp_path / "missing.pt")
    gnn_v2_service.get_model.cache_clear()
    assert gnn_v2_service.status()["available"] is False
    gnn_v2_service.get_model.cache_clear()


def test_score_recent_persists_explains_and_alerts(db, exported_model):
    make_world(db)
    status = gnn_v2_service.status()
    assert status["available"] and status["variant"] == "edge"

    result = gnn_v2_service.score_recent(db, hours=24)
    db.commit()
    # A, B and C settled within the last day; D only has held / blocked / stale transfers
    assert result["scored"] == 3 and result["flagged"] == 3

    row = gnn_v2_service.latest_for(db, "B")
    assert row is not None and row.window_nodes == 3 and row.window_edges == 3
    view = gnn_v2_service.to_dict(row)
    for t in view["top_transfers"]:
        assert t["txn_ref"] in {"T1", "T2", "T3"}  # settled transfers only
        assert t["currency"] == "INR"  # shown in the original currency
    alerts = db.query(Alert).filter(Alert.alert_type == gnn_v2_service.ALERT_TYPE).all()
    assert len(alerts) == 3
    assert all("AMLworld" in a.explanation for a in alerts)


def test_rescoring_refreshes_instead_of_duplicating(db, exported_model):
    make_world(db)
    gnn_v2_service.score_recent(db, hours=24)
    gnn_v2_service.score_recent(db, hours=24)
    db.commit()
    assert db.query(GnnAccountScore).count() == 6  # score history is kept
    assert db.query(Alert).filter(Alert.alert_type == gnn_v2_service.ALERT_TYPE).count() == 3


def test_window_end_defaults_to_latest_settlement(db, exported_model):
    make_world(db)
    latest = gnn_v2_service.latest_settlement(db)
    assert latest is not None and latest <= NOW
