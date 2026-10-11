"""AMLworld pipeline: loading, temporal splits, window store and the R2 run."""

from datetime import timedelta

import numpy as np
import pytest

from app.datasets import amlworld
from app.gnn import metrics
from app.gnn.window_dataset import DatasetConfig, WindowStore, build_or_load, temporal_splits
from app.graph.features_v2 import AMLWORLD_SCHEMA, WindowConfig
from tests.amlworld_fixture import EUR_PER_USD, write_fixture


@pytest.fixture(scope="module")
def fixture_files(tmp_path_factory):
    return write_fixture(tmp_path_factory.mktemp("amlworld"))


@pytest.fixture(scope="module")
def data(fixture_files):
    trans, pats, _ = fixture_files
    return amlworld.load(trans, pats)


def test_loader_parses_converts_and_labels(data, fixture_files):
    _, _, truth = fixture_files
    cols = data.source.columns
    assert data.num_transfers == truth["rows"]
    assert int(data.is_laundering.sum()) == truth["laundering"]
    assert all(":" in k for k in cols.account_keys)  # "<bank>:<account>"
    assert data.fx_per_usd["Euro"] == pytest.approx(EUR_PER_USD)
    assert int(cols.is_international.sum()) == truth["euro_cross"]
    assert cols.cross_institution.any() and not cols.cross_institution.all()

    names = data.typology_names
    counts = {n: int((data.typology == i).sum()) for i, n in enumerate(names)}
    assert counts["FAN-OUT"] == truth["FAN-OUT"]
    assert counts["CYCLE"] == truth["CYCLE"]
    assert data.unmatched_pattern_rows == 0
    assert set(cols.channel_names) == {"ACH", "Wire", "Cheque", "Credit Card", "Cash"}


def test_loader_rejects_other_files(tmp_path):
    bad = tmp_path / "x.csv"
    bad.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(amlworld.AmlworldFormatError):
        amlworld.load(bad)


def test_temporal_splits_are_ordered_and_cover_everything(data):
    splits = temporal_splits(data.source, data.is_laundering)
    assert [s.name for s in splits] == ["train", "val", "test"]
    assert splits[0].end == splits[1].start and splits[1].end == splits[2].start
    assert sum(s.transfers for s in splits) == data.num_transfers
    for s in splits:
        assert s.start.hour == 0 and s.end.hour == 0  # day-aligned
        assert s.anchors[0] == s.start + timedelta(days=1) and s.anchors[-1] == s.end


def test_window_store_labels_weights_and_roundtrip(data, tmp_path):
    config = DatasetConfig(window=WindowConfig(days=7, hops=2), neg_rate_train=0.5, neg_rate_eval=0.5)
    stores, _ = build_or_load(
        data.source, data.is_laundering, data.typology, config, AMLWORLD_SCHEMA, tmp_path, "fixture"
    )
    train = stores["train"]
    assert train.label.sum() > 0 and (train.label == 0).sum() > 0
    assert np.allclose(train.weight[train.label == 0], 2.0)  # 1 / neg_rate
    assert np.allclose(train.weight[train.label == 1], 1.0)
    assert train.node_features.shape[1] == AMLWORLD_SCHEMA.node_dim
    assert np.all(train.seed_features()[:, -1] == 1.0)  # ego marker on every seed

    # Every positive seed touches a laundering transfer on its anchor day
    for i in np.flatnonzero(train.label == 1):
        w = train.window(int(i))
        src, dst = w["edge_index"]
        own = (src == 0) | (dst == 0)
        assert (own & w["edge_label"] & w["edge_in_target_day"]).any()

    again, _ = build_or_load(
        data.source, data.is_laundering, data.typology, config, AMLWORLD_SCHEMA, tmp_path, "fixture"
    )
    for name in ("train", "val", "test"):
        np.testing.assert_array_equal(stores[name].node_features, again[name].node_features)
        np.testing.assert_array_equal(stores[name].label, again[name].label)
        assert stores[name].seed_keys == again[name].seed_keys


def test_weighted_metrics_estimate_the_full_population():
    # 2 positives kept, 4 sampled negatives standing for 400 (rate 1%)
    y = np.array([1, 1, 0, 0, 0, 0])
    score = np.array([0.9, 0.4, 0.8, 0.1, 0.1, 0.1])
    w = np.array([1, 1, 100, 100, 100, 100], dtype=float)
    out = metrics.evaluate(y, score, w, threshold=0.5)
    assert out["recall"] == pytest.approx(0.5)
    assert out["precision"] == pytest.approx(1 / 101)  # one TP against ~100 FPs
    assert out["base_rate"] == pytest.approx(2 / 402)


def test_r2_run_end_to_end(fixture_files, tmp_path):
    torch = pytest.importorskip("torch")
    from app.gnn import r2

    trans, pats, _ = fixture_files
    config = r2.R2Config(
        transactions=trans,
        patterns=pats,
        out_dir=tmp_path,
        seeds=1,
        dataset=DatasetConfig(window=WindowConfig(days=7, hops=2), neg_rate_train=0.5, neg_rate_eval=0.5),
        train=r2.TrainConfig(epochs=2, patience=2),
    )
    report = r2.run(config)
    assert set(report["results"]) == {"seed-only", "seed+context", "logistic", "gnn"}
    for result in report["results"].values():
        assert "pr_auc" in result["test"]
    assert "FAN-OUT" in report["results"]["gnn"]["test"]["recall_by_typology"]
    checkpoint = torch.load(next(tmp_path.glob("r2_gnn_baseline-*.pt")), weights_only=False)
    assert checkpoint["schema"]["include_profile"] is False
    assert "test" in checkpoint["metrics"]
    assert r2.format_table(report).count("\n") == 4


def test_until_cuts_the_tail_and_is_reported(fixture_files):
    from datetime import date

    trans, pats, truth = fixture_files
    full = amlworld.load(trans, pats)
    cut = amlworld.load(trans, pats, until=date(2022, 9, 9))
    last = max(d["day"] for d in cut.daily_profile())
    assert last == "2022-09-09"
    dropped = full.num_transfers - cut.num_transfers
    assert dropped > 0 and any(f"dropped {dropped} later" in n for n in cut.notes)
    assert cut.summary()["daily"][-1]["day"] == "2022-09-09"
