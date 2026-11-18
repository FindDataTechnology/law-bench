"""judge 调用失败的行必须记 `invalid`（不计分），不能算成 FAIL。

`_score_one` 只按**字符串子串**（`RateLimit` / `429` / `ServiceUnavailable` / `503`）
识别可重试错误；其余异常直接 `metric.error = s` 返回。下游
`success = bool(getattr(g, "success", False))` 在 measure 从未完成时是 `False`，
于是 `verdict = "fail"` 并计入分母。

而 `classify_structural_soundness` 开头就 `if error: return None`，所以这些行
**连 `invalid` 都不算**——硬算 fail。这与代码自己的原则「宁无效不假绿」相反，
也与它上面那段注释直接冲突：注释说 429 绝不能变成 FAIL，因为全员 FAIL（conf=1.0）
会让自迭代循环依据噪声重写条款——`property_service` 就是这么掉到 0/10 的。

为什么子串匹配不够：中继饱和时真实出现的失败是
`APIConnectionError`、`APITimeoutError`、中继 500/502、截断响应的 JSON 解码错误——
一个都不在列表里。

本文件测纯函数层的契约：**带 error 的行必须被判为 invalid**。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.eval.scoring import classify_structural_soundness  # noqa: E402


def test_judge_call_error_is_invalid_not_fail():
    """judge 调用失败的证据（error 非空）必须判 invalid。"""
    verdict = classify_structural_soundness(
        reasoning="", success=False, error="APITimeoutError: request timed out"
    )
    assert verdict is not None, (
        "judge 调用失败（APITimeoutError）被判成 None=结构没问题 → 下游按 success=False 记 fail 并计入分母。"
        "这正是审计 03 §4 描述的失败面：中继超时被记成「条款不合格」，自迭代据此重写本来正确的条款。"
    )


def test_connection_error_is_invalid():
    """连接被重置同样是「没测成」，不是「不合格」。"""
    assert classify_structural_soundness(
        reasoning="", success=False,
        error="openai.APIConnectionError: Connection reset by peer",
    ) is not None


def test_relay_5xx_that_leaked_past_retry_is_invalid():
    """中继 500/502 漏过重试后也是无效，不是 FAIL。"""
    assert classify_structural_soundness(
        reasoning="", success=False, error="InternalServerError: 502 Bad Gateway",
    ) is not None


def test_a_real_fail_verdict_is_still_a_fail():
    """**不许把真实 FAIL 也变成 invalid**——那是假绿的另一头。"""
    verdict = classify_structural_soundness(
        reasoning="条款要求提供完整审计轨迹，但正文未给出。CONFIDENCE: 0.90",
        success=False,
        error=None,
    )
    assert verdict is None, "真实 FAIL（无 error）必须保持 fail，不能洗成 invalid"


def test_a_real_pass_is_untouched():
    """正常 PASS 不受影响。"""
    assert classify_structural_soundness(
        reasoning="条款要求已满足。CONFIDENCE: 0.88", success=True, error=None,
    ) is None


def test_transient_errors_are_recognised_for_retry():
    """瞬态错误（超时/连接重置/5xx）应当被识别为可重试，不只是记 invalid。

    原实现只匹配 `RateLimit|429|ServiceUnavailable|503` 四个子串；中继饱和时
    真正出现的是超时与连接错误，一个都不在列表里——于是本来重试一次就能成功的
    调用直接放弃。修完「记 invalid」之后还要让它有机会重试，否则只是把 FAIL
    换成了 invalid，仍然是白丢一次判定。
    """
    from src.eval.scoring import _is_transient_judge_error

    for err in (
        "APITimeoutError: Request timed out.",
        "openai.APIConnectionError: Connection reset by peer",
        "InternalServerError: 502 Bad Gateway",
        "RateLimitError: 429 Too Many Requests",
        "ServiceUnavailableError: 503",
    ):
        assert _is_transient_judge_error(err), f"没识别成瞬态：{err}"

    for err in (
        "ValidationError: output did not match the required schema",
        "ValueError: criteria list is empty",
    ):
        assert not _is_transient_judge_error(err), f"非瞬态错误被当成可重试：{err}"


def test_partial_invalid_is_never_all_pass():
    """有 invalid 行时 all_pass 必须为 False——否则是「拿没测成当通过」。

    这条是改判 invalid 之后**新引入**的假绿面：`[pass, invalid]` 时滤镜掉 invalid
    后分母剩 1、分子 1 → all_pass=True。原代码只兜底了「全部 invalid」一种，
    漏掉「部分 invalid」。真 PG 上的回归测试
    `tests/test_scoring.py::test_judge_call_error_captured` 抓住了它。
    """
    # 纯逻辑复算，不依赖库：模拟 criteria_results = [pass, invalid]
    criteria_results = [
        {"verdict": "pass"},
        {"verdict": "invalid"},
    ]
    invalid_count = sum(1 for r in criteria_results if r["verdict"] == "invalid")
    valid = [r for r in criteria_results if r["verdict"] != "invalid"]
    n_total, n_passed = len(valid), sum(1 for r in valid if r["verdict"] == "pass")
    all_pass = n_passed == n_total
    if invalid_count:
        all_pass = False
    assert all_pass is False, (
        "部分 invalid 时被判 ALL PASS —— 没测成的条款被当成通过了"
    )


def test_numbers_in_unrelated_text_are_not_treated_as_http_5xx():
    """裸 `"500"` 子串会误伤——我第一版就是这么写的，实测被自己抓到。

    `"ValidationError: max 500 tokens exceeded"` 和 `"score=0.500 below floor"`
    都含 `500` 但都是确定性错误；把它们当瞬态去重试三次纯属浪费。
    数字码必须带 HTTP 语境才算。
    """
    from src.eval.scoring import _is_transient_judge_error as t

    assert not t("ValidationError: max 500 tokens exceeded"), "token 上限被当成 5xx 重试"
    assert not t("score=0.500 below the relevance floor"), "分数里的 500 被当成 5xx"
    # 带 HTTP 语境的仍然要认
    assert t("HTTP 500 from relay")
    assert t("status: 502")
    assert t("upstream returned 504")
