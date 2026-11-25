from __future__ import annotations

import copy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

_NO_REASONING: Mapping[str, Any] = MappingProxyType({})


def _body(**keys: Any) -> Mapping[str, Any]:
    return MappingProxyType(dict(keys))



@dataclass(frozen=True)
class LLMModel:
    id: str
    provider: str
    api_model: str = ""
    input_per_1k_cents: float = 0.0
    # Cache-hit rate: long stable prompts are mostly hits, so billing them as misses over-counts ~50x.
    input_cache_hit_per_1k_cents: float = 0.0
    input_cache_write_per_1k_cents: float = 0.0
    output_per_1k_cents: float = 0.0
    # Literal body fragment stating the reasoning mode, per MODEL (providers disagree). Never state a mode by omission or by model name.
    reasoning_body: Mapping[str, Any] = _NO_REASONING
    effort_choices: tuple[str, ...] = ()
    # Pinned per model: ~30 call sites pass none, and another provider's default would run at a setting nobody measured.
    reasoning_effort: str = ""
    # Policy flag: text-only until someone clears a model for images; the Brain dropdown offers every MODELS key.
    vision_ok: bool = False
    # Claude 4.7+ 400s on any temperature below 1; False omits it.
    sends_temperature: bool = True
    # False = never route a JSON lane here; Anthropic's compat layer 400s on response_format json_object.
    json_object_ok: bool = True

    def reasoning_keys(self) -> dict[str, Any]:
        # Fresh copy: the shared process-lifetime body must never be mutated by a request builder.
        return copy.deepcopy(dict(self.reasoning_body))

    def wire_model(self) -> str:
        return self.api_model or self.id


# Prices are cents per 1k tokens. DeepSeek is seeded at PEAK on purpose: the cap must never under-count (off-peak is half).
MODELS: dict[str, LLMModel] = {
    # Our ids are the wire names; the mode lives only in reasoning_body (DeepSeek retired its mode-by-name aliases and every call 400'd).
    "deepseek-v4-flash": LLMModel(
        "deepseek-v4-flash", "deepseek",
        input_per_1k_cents=0.044, input_cache_hit_per_1k_cents=0.0014,
        output_per_1k_cents=0.132, reasoning_body=_body(thinking={"type": "disabled"}),
    ),
    "deepseek-v4-pro": LLMModel(
        "deepseek-v4-pro", "deepseek",
        input_per_1k_cents=0.132, input_cache_hit_per_1k_cents=0.0044,
        output_per_1k_cents=0.396,
        reasoning_body=_body(thinking={"type": "enabled"}),
        effort_choices=("low", "medium", "high"), reasoning_effort="high",
    ),
    # Prices read from DeepInfra's model list; an under-counting seed lets a sweep run past the daily cap.
    "qwen3-vl-30b": LLMModel(
        "qwen3-vl-30b", "deepinfra", api_model="Qwen/Qwen3-VL-30B-A3B-Instruct",
        input_per_1k_cents=0.015, output_per_1k_cents=0.06, vision_ok=True,
    ),
    "qwen3-vl-235b": LLMModel(
        "qwen3-vl-235b", "deepinfra", api_model="Qwen/Qwen3-VL-235B-A22B-Instruct",
        input_per_1k_cents=0.02, output_per_1k_cents=0.088, vision_ok=True,
    ),
    # GLM-5.3-Flash (Z.ai). Registered for CHAT only — see `vision_ok` above.
    # The model does accept `image_url` parts and described test images
    # correctly when probed (2026-08-27); leaving the image paths on Qwen is a
    # scope decision, not a limitation of this model.
    #
    # Priced at LIST — $0.15 miss / $0.03 hit in · $0.50 out per 1M — NOT at the
    # $0.075/$0.015/$0.25 on z.ai's pricing page today. That is a 50% promotion
    # which the page itself says ends 2026-09-09, and a seed that expires is a
    # cap that starts under-counting by 2x on a date nobody will be watching.
    # Erring high only makes the cap stricter, which is the safe direction; the
    # comment above the Qwen block is the argument, and it was written from a
    # real 35% under-count. Note the shape against DeepSeek flash: the MISS rate
    # is comparable but the HIT rate is ~10x DEARER, and on the long stable
    # system prompts these lanes send almost all input is a cache hit.
    #
    # This model ALWAYS reasons — "This model always engages in thinking and
    # cannot be disabled" — so `reasoning_effort` is the only control it has and
    # sending it is mandatory. Pinned to "low" because that is the setting the
    # latency was measured at: p50 1822ms on a production-shaped prompt, level
    # with the incumbent flash model. Omitting the field cost 327 reasoning
    # tokens and 8.9s on the same prompt.
    # glm-5.3-flash 400s on the `thinking` object that glm-4.5-air requires.
    "glm-5.3-flash": LLMModel(
        "glm-5.3-flash", "zai", api_model="glm-5.3-flash",
        input_per_1k_cents=0.015, input_cache_hit_per_1k_cents=0.003,
        output_per_1k_cents=0.05,
        effort_choices=("low", "high", "max"), reasoning_effort="low",
    ),
    # Honours the `thinking` object both ways; accepts reasoning_effort but ignores it, so no effort_choices.
    "glm-4.5-air": LLMModel(
        "glm-4.5-air", "zai", api_model="glm-4.5-air",
        input_per_1k_cents=0.02, input_cache_hit_per_1k_cents=0.003,
        output_per_1k_cents=0.11,
        reasoning_body=_body(thinking={"type": "disabled"}),
    ),
    # All three 400 on thinking:enabled; Opus 400s on disabled and Sonnet wants adaptive, Haiku takes disabled.
    "claude-opus-5-5": LLMModel(
        "claude-opus-5-5", "anthropic",
        input_per_1k_cents=0.4, input_cache_hit_per_1k_cents=0.02,
        input_cache_write_per_1k_cents=0.5,
        output_per_1k_cents=2.0, sends_temperature=False, json_object_ok=False,
        reasoning_body=_body(thinking={"type": "adaptive"}),
    ),
    "claude-sonnet-5-5": LLMModel(
        "claude-sonnet-5-5", "anthropic",
        input_per_1k_cents=0.2, input_cache_hit_per_1k_cents=0.01,
        input_cache_write_per_1k_cents=0.25,
        output_per_1k_cents=1.0, sends_temperature=False, json_object_ok=False,
        reasoning_body=_body(thinking={"type": "adaptive"}),
    ),
    "claude-haiku-5-5": LLMModel(
        "claude-haiku-5-5", "anthropic",
        input_per_1k_cents=0.01, input_cache_hit_per_1k_cents=0.001,
        input_cache_write_per_1k_cents=0.0125,
        output_per_1k_cents=0.05, sends_temperature=False, json_object_ok=False,
        reasoning_body=_body(thinking={"type": "disabled"}),
    ),
    # json_object_ok=False: no host documents json_object.
    "euryale-v2.3": LLMModel(
        "euryale-v2.3", "nanogpt", api_model="Sao10K/L3.3-70B-Euryale-v2.3",
        input_per_1k_cents=0.0493, input_cache_hit_per_1k_cents=0.0493,
        output_per_1k_cents=0.0493, json_object_ok=False,
    ),
    "euryale-v2.2": LLMModel(
        "euryale-v2.2", "openrouter", api_model="sao10k/l3.1-euryale-70b",
        input_per_1k_cents=0.085, input_cache_hit_per_1k_cents=0.085,
        output_per_1k_cents=0.085, json_object_ok=False,
    ),
    "euryale-v2.3-deepinfra": LLMModel(
        "euryale-v2.3-deepinfra", "deepinfra", api_model="Sao10K/L3.3-70B-Euryale-v2.3",
        input_per_1k_cents=0.085, input_cache_hit_per_1k_cents=0.085,
        output_per_1k_cents=0.085, json_object_ok=False,
    ),
    "hermes-4-405b": LLMModel(
        "hermes-4-405b", "openrouter", api_model="nousresearch/hermes-4-405b",
        input_per_1k_cents=0.1, input_cache_hit_per_1k_cents=0.1,
        output_per_1k_cents=0.3, json_object_ok=False,
    ),
}

for _mid, _m in MODELS.items():
    assert not _m.reasoning_effort or _m.reasoning_effort in _m.effort_choices, (
        f"{_mid}: pinned reasoning_effort {_m.reasoning_effort!r} is not in "
        f"effort_choices {_m.effort_choices}")
