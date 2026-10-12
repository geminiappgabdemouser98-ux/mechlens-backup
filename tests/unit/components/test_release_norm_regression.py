"""CPU-only epsilon-placement sentinels; not a trained Gemma checkpoint acceptance test."""

import pytest
import torch

from transformer_lens.components.rms_norm import RMSNorm
from transformer_lens.config.hooked_transformer_config import HookedTransformerConfig
from transformer_lens.model_bridge.generalized_components.normalization import (
    NormalizationBridge,
)


@pytest.mark.parametrize("implementation", ["hooked", "bridge"])
@pytest.mark.parametrize("length", [4, 128])
@pytest.mark.parametrize("scale", [1.0, 0.0001])
def test_epsilon_inside_normalization(implementation, length, scale, record_property):
    """Low-amplitude activations expose epsilon errors that ordinary inputs can hide."""
    cfg = HookedTransformerConfig(
        n_layers=1,
        d_model=4,
        d_head=2,
        n_heads=2,
        n_ctx=128,
        d_vocab=8,
        act_fn="relu",
        normalization_type="RMS",
        eps=1e-6,
        device="cpu",
    )
    weights = torch.tensor([0.5, 1.0, 1.5, 2.0])
    x = torch.tensor([[-2.0, -0.5, 0.25, 1.0]]).repeat(1, length, 1) * scale
    if implementation == "hooked":
        norm = RMSNorm(cfg)
        with torch.no_grad():
            norm.w.copy_(weights)
    else:
        native = torch.nn.RMSNorm(4, eps=cfg.eps)
        with torch.no_grad():
            native.weight.copy_(weights)
        norm = NormalizationBridge(name="release_norm", config=cfg, uses_rms_norm=True)
        norm.set_original_component(native)
    actual = norm(x)
    # Float64 oracle uses division/sqrt independently of the production forward.
    ref64 = x.double() / torch.sqrt(x.double().square().mean(-1, keepdim=True) + cfg.eps)
    expected = (ref64 * weights.double()).float()
    error = float((actual.detach() - expected).abs().max())
    record_property("scope", "synthetic RMSNorm component; CPU float32")
    record_property("max_absolute_activation_delta", error)
    record_property("absolute_tolerance", 1e-6)
    assert torch.isfinite(actual).all()
    torch.testing.assert_close(actual, expected, atol=1e-6, rtol=0)

    if scale < 1:
        outside_eps = (x / (x.square().mean(-1, keepdim=True).sqrt() + cfg.eps)) * weights
        mutation_error = float((outside_eps - expected).abs().max())
        record_property("epsilon_outside_sqrt_negative_control_delta", mutation_error)
        assert mutation_error > 1e-4, "sentinel must reject the deliberately wrong formula"
