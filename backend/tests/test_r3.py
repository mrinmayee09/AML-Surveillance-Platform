"""R3: the GraphSAGE variants and the ablation runner."""

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from app.gnn.sage import VARIANTS, build_model  # noqa: E402
from app.graph.features_v2 import AMLWORLD_SCHEMA  # noqa: E402

N, D, E = AMLWORLD_SCHEMA.node_dim, AMLWORLD_SCHEMA.node_dim, AMLWORLD_SCHEMA.edge_dim


def _graph():
    torch.manual_seed(0)
    x = torch.rand(5, N)
    edge_index = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]])
    edge_attr = torch.rand(4, E)
    return x, edge_index, edge_attr


@pytest.mark.parametrize("variant", VARIANTS)
def test_variants_share_the_output_contract(variant):
    model = build_model(variant, N, E, hidden=16, layers=3, dropout=0.0).eval()
    x, ei, ea = _graph()
    node_logits, _, _, h = model(x, ei, ea)
    assert node_logits.shape == (5,)
    assert h.shape == (5, 16)
    # Graphs with no edges must still work (isolated seed accounts exist)
    empty_logits, *_ = model(x, torch.zeros((2, 0), dtype=torch.long), torch.zeros((0, E)))
    assert empty_logits.shape == (5,)


def test_only_plain_graphsage_ignores_direction():
    x, ei, ea = _graph()
    reversed_ei = ei.flip(0)
    outputs = {}
    for variant in VARIANTS:
        torch.manual_seed(1)
        model = build_model(variant, N, E, hidden=16, layers=2, dropout=0.0).eval()
        with torch.no_grad():
            a = model(x, ei, ea)[0]
            b = model(x, reversed_ei, ea)[0]
        outputs[variant] = torch.allclose(a, b, atol=1e-6)
    assert outputs == {"plain": True, "directed": False, "edge": False}


def test_only_edge_variant_reads_transfer_details():
    x, ei, ea = _graph()
    changed = ea.clone()
    changed[:, 1:] = torch.rand(changed.shape[0], E - 1)  # keep column 0 (amount) fixed
    sensitive = {}
    for variant in VARIANTS:
        torch.manual_seed(2)
        model = build_model(variant, N, E, hidden=16, layers=2, dropout=0.0).eval()
        with torch.no_grad():
            sensitive[variant] = not torch.allclose(model(x, ei, ea)[0], model(x, ei, changed)[0])
    # B only uses the amount (column 0) as a weight; C uses every column
    assert sensitive == {"plain": False, "directed": False, "edge": True}


def test_r3_ablation_end_to_end(tmp_path):
    from app.gnn import r2, r3
    from app.gnn.window_dataset import DatasetConfig
    from app.graph.features_v2 import WindowConfig
    from tests.amlworld_fixture import write_fixture

    trans, pats, _ = write_fixture(tmp_path / "data")
    config = r2.R2Config(
        transactions=trans,
        patterns=pats,
        out_dir=tmp_path / "out",
        seeds=1,
        dataset=DatasetConfig(window=WindowConfig(days=7, hops=2), neg_rate_train=0.5, neg_rate_eval=0.5),
        train=r2.TrainConfig(epochs=2, patience=2),
    )
    report = r3.run(config, export=False)
    assert set(report["results"]) == set(VARIANTS)  # no R2 report yet, so B trained here
    chosen = report["selected"]["variant"]
    best_val = max(report["results"][v]["val"]["pr_auc"]["mean"] for v in VARIANTS)
    assert report["results"][chosen]["val"]["pr_auc"]["mean"] == best_val

    target = r3.export_model(
        Path(report["selected"]["checkpoint"]), report, target=tmp_path / "exported.pt"
    )
    meta = (tmp_path / "exported.meta.json").read_text(encoding="utf-8")
    assert chosen in meta and target.exists()

    from app.gnn import report_md

    md = report_md.build(tmp_path / "out")
    assert "| A. GraphSAGE (plain, undirected) |" in md and "**Selected for the app:**" in md

