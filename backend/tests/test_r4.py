"""R4: occlusion explanations and the fidelity test."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from app.gnn.explain_v2 import candidate_edges, deletion_test, explain  # noqa: E402
from app.gnn.sage import build_model  # noqa: E402
from app.graph.features_v2 import AMLWORLD_SCHEMA  # noqa: E402

N, E = AMLWORLD_SCHEMA.node_dim, AMLWORLD_SCHEMA.edge_dim


def _window(seed=0):
    rng = np.random.default_rng(seed)
    x = rng.random((6, N)).astype(np.float32)
    # 0 <-> 1, 1 -> 2, 2 -> 3, 4 -> 0, 5 -> 4 (5 is two hops away)
    edge_index = np.array([[0, 1, 1, 2, 4, 5], [1, 0, 2, 3, 0, 4]], dtype=np.int64)
    edge_attr = rng.random((6, E)).astype(np.float32)
    return x, edge_index, edge_attr


def test_candidates_are_the_seeds_neighbourhood():
    x, ei, ea = _window()
    cands = set(candidate_edges(ei, ea).tolist())
    # every edge touching node 0 or its direct counterparties 1 and 4
    assert cands == {0, 1, 2, 4, 5}
    assert 3 not in cands  # 2 -> 3 touches neither the seed nor a direct counterparty


def test_explain_matches_direct_scoring_and_ranks_by_drop():
    x, ei, ea = _window()
    torch.manual_seed(0)
    model = build_model("edge", N, E, hidden=16, layers=2, dropout=0.0).eval()
    out = explain(model, x, ei, ea, top_k=5)
    with torch.no_grad():
        direct = torch.sigmoid(model(torch.from_numpy(x), torch.from_numpy(ei), torch.from_numpy(ea))[0][0])
    assert out["score"] == pytest.approx(float(direct), abs=1e-6)
    drops = [a.score_drop for a in out["top"]]
    assert drops == sorted(drops, reverse=True) and all(d > 0 for d in drops)
    assert [a.rank for a in out["top"]] == list(range(1, len(drops) + 1))


def test_deletion_test_reports_both_drops():
    x, ei, ea = _window(1)
    torch.manual_seed(1)
    model = build_model("directed", N, E, hidden=16, layers=2, dropout=0.0).eval()
    out = deletion_test(model, x, ei, ea, k=2, random_draws=3)
    if out is not None:  # None only when nothing raises the score
        assert set(out) == {"base", "top_k_drop", "random_k_drop"}


def test_fidelity_on_the_fixture(tmp_path):
    from app.gnn import r2
    from app.gnn.r4 import fidelity
    from app.gnn.v2_model import load_checkpoint
    from app.gnn.window_dataset import DatasetConfig
    from app.graph.features_v2 import WindowConfig
    from tests.amlworld_fixture import write_fixture

    trans, pats, _ = write_fixture(tmp_path / "data")
    config = r2.R2Config(
        transactions=trans, patterns=pats, out_dir=tmp_path / "out", seeds=1,
        dataset=DatasetConfig(window=WindowConfig(days=7, hops=2), neg_rate_train=0.5, neg_rate_eval=0.5),
        train=r2.TrainConfig(epochs=2, patience=2),
    )
    r2.run(config)
    loaded = load_checkpoint(next((tmp_path / "out").glob("r2_gnn_baseline-*.pt")))
    assert loaded.variant == "directed" and loaded.schema == AMLWORLD_SCHEMA
    _, stores, _ = r2.prepare(config)
    result = fidelity(loaded, stores["test"], k=2, max_windows=20)
    assert {"all_flagged", "true_positives_only", "flagged_test_windows"} <= set(result)
