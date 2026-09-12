"""개발 루프 계약 테스트.

이 루프의 존재 이유는 두 가지다.

  1. 생성물을 **실행해서** 판정한다. 겉이 깨끗한 판본이 로직은 깨져 있던 실측이 있다.
  2. 실패를 스펙 개선으로 되먹인다. 6개 모듈에서 실패 원인 8건 중 6건이
     스펙의 빈틈이었다 — 코드만 고치면 같은 실수가 다음 모듈에서 반복된다.

⚠ 모델 호출은 주입한다. 테스트가 네트워크를 타지 않는다.
"""

import pytest

from browsing.devloop.loop import Round, choose_best, extract_spec_feedback, run_loop


class FakeGen:
    """정해진 코드를 순서대로 뱉는 가짜 생성기."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.outputs.pop(0) if self.outputs else ""


def fake_runner(results):
    """정해진 (passed, failed, output) 을 순서대로 돌려주는 가짜 테스트 러너."""
    seq = list(results)

    def run(_code_path):
        return seq.pop(0) if seq else (0, 1, "no result")

    return run


# ── 성공 경로 ────────────────────────────────────────────────────────────────

def test_stops_at_first_passing_round(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("do the thing")
    gen = FakeGen(["print('a')", "print('b')"])
    result = run_loop(spec, tmp_path / "out.py", generate=gen,
                      run_tests=fake_runner([(5, 0, "ok")]), max_rounds=3)
    assert result.ok is True
    assert len(result.rounds) == 1
    assert len(gen.prompts) == 1, "통과했는데 또 생성하면 안 된다"


def test_writes_the_passing_code_to_out(tmp_path):
    out = tmp_path / "out.py"
    spec = tmp_path / "s.md"
    spec.write_text("x")
    run_loop(spec, out, generate=FakeGen(["print('final')"]),
             run_tests=fake_runner([(3, 0, "ok")]), max_rounds=2)
    assert "final" in out.read_text()


# ── 실패 피드백이 다음 프롬프트에 실제로 들어가는가 ───────────────────────────

def test_failure_output_is_fed_back_into_the_next_prompt(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("the spec body")
    gen = FakeGen(["bad code", "good code"])
    run_loop(spec, tmp_path / "out.py", generate=gen,
             run_tests=fake_runner([(1, 2, "AssertionError: boom"), (3, 0, "ok")]),
             max_rounds=3)
    assert len(gen.prompts) == 2
    assert "AssertionError: boom" in gen.prompts[1]
    assert "bad code" in gen.prompts[1], "직전 생성물도 함께 줘야 고칠 수 있다"


def test_first_prompt_has_no_failure_section(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("the spec body")
    gen = FakeGen(["c"])
    run_loop(spec, tmp_path / "out.py", generate=gen,
             run_tests=fake_runner([(1, 0, "ok")]), max_rounds=2)
    assert "PREVIOUS ATTEMPT" not in gen.prompts[0]


def test_prompt_asks_for_spec_feedback(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    gen = FakeGen(["c1", "c2"])
    run_loop(spec, tmp_path / "out.py", generate=gen,
             run_tests=fake_runner([(0, 1, "fail"), (1, 0, "ok")]), max_rounds=3)
    assert "SPEC_FEEDBACK" in gen.prompts[1]


# ── 최선 판본 유지 — 2차가 1차보다 나쁠 수 있다 (실측) ────────────────────────

def test_keeps_the_best_round_not_the_last(tmp_path):
    """weekly.py 에서 2차 생성이 1차보다 나빴다(20통과 → SQL 오류로 전멸).

    마지막 판본을 남기면 더 나쁜 코드로 끝난다.
    """
    out = tmp_path / "out.py"
    spec = tmp_path / "s.md"
    spec.write_text("x")
    run_loop(spec, out, generate=FakeGen(["GOOD", "WORSE", "ALSO_BAD"]),
             run_tests=fake_runner([(20, 5, "f1"), (0, 25, "f2"), (2, 23, "f3")]),
             max_rounds=3)
    assert "GOOD" in out.read_text(), "가장 성적 좋은 판본이 남아야 한다"


def test_choose_best_prefers_more_passed():
    rounds = [Round(1, "a", 10, 5, ""), Round(2, "b", 20, 5, "")]
    assert choose_best(rounds).code == "b"


def test_choose_best_breaks_ties_by_fewer_failures():
    rounds = [Round(1, "a", 10, 5, ""), Round(2, "b", 10, 1, "")]
    assert choose_best(rounds).code == "b"


def test_choose_best_prefers_earlier_round_on_exact_tie():
    """동점이면 먼저 나온 것을 남긴다 — 뒤로 갈수록 회귀하는 경향을 봤다."""
    rounds = [Round(1, "first", 10, 2, ""), Round(2, "second", 10, 2, "")]
    assert choose_best(rounds).code == "first"


# ── 라운드 상한 ──────────────────────────────────────────────────────────────

def test_gives_up_after_max_rounds(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    gen = FakeGen(["a", "b", "c", "d"])
    result = run_loop(spec, tmp_path / "out.py", generate=gen,
                      run_tests=fake_runner([(0, 1, "f")] * 4), max_rounds=3)
    assert result.ok is False
    assert len(result.rounds) == 3
    assert len(gen.prompts) == 3


def test_empty_generation_is_recorded_not_crashed(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    result = run_loop(spec, tmp_path / "out.py", generate=FakeGen([""]),
                      run_tests=fake_runner([(0, 1, "empty")]), max_rounds=1)
    assert result.ok is False
    assert result.rounds[0].code == ""


# ── 스펙 피드백 추출 ─────────────────────────────────────────────────────────

def test_extracts_spec_feedback_block():
    text = """some code here
SPEC_FEEDBACK: the return type of helper() was never stated
more text"""
    assert "return type" in extract_spec_feedback(text)


def test_extracts_multiline_spec_feedback():
    text = """code
SPEC_FEEDBACK:
- point one
- point two
"""
    fb = extract_spec_feedback(text)
    assert "point one" in fb and "point two" in fb


def test_no_feedback_returns_empty_string():
    assert extract_spec_feedback("just code, no feedback marker") == ""


def test_feedback_is_collected_across_rounds(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    gen = FakeGen([
        "c1",
        "c2\nSPEC_FEEDBACK: return type unclear",
        "c3\nSPEC_FEEDBACK: timezone not specified",
    ])
    result = run_loop(spec, tmp_path / "out.py", generate=gen,
                      run_tests=fake_runner([(0, 3, "f"), (1, 2, "f"), (2, 1, "f")]),
                      max_rounds=3)
    joined = " ".join(result.spec_feedback)
    assert "return type unclear" in joined
    assert "timezone not specified" in joined


def test_feedback_marker_is_stripped_from_saved_code(tmp_path):
    """SPEC_FEEDBACK 은 사람에게 주는 메모지 코드가 아니다."""
    out = tmp_path / "out.py"
    spec = tmp_path / "s.md"
    spec.write_text("x")
    run_loop(spec, out, generate=FakeGen(["print('hi')\nSPEC_FEEDBACK: something"]),
             run_tests=fake_runner([(1, 0, "ok")]), max_rounds=1)
    assert "SPEC_FEEDBACK" not in out.read_text()


# ── 라운드 기록 ──────────────────────────────────────────────────────────────

def test_every_round_is_recorded_with_its_score(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    result = run_loop(spec, tmp_path / "out.py",
                      generate=FakeGen(["a", "b"]),
                      run_tests=fake_runner([(1, 4, "f1"), (5, 0, "ok")]),
                      max_rounds=3)
    assert [(r.passed, r.failed) for r in result.rounds] == [(1, 4), (5, 0)]


def test_rounds_are_numbered_from_one(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    result = run_loop(spec, tmp_path / "out.py", generate=FakeGen(["a", "b"]),
                      run_tests=fake_runner([(0, 1, "f"), (1, 0, "ok")]), max_rounds=3)
    assert [r.index for r in result.rounds] == [1, 2]


def test_missing_spec_file_raises(tmp_path):
    with pytest.raises((FileNotFoundError, ValueError)):
        run_loop(tmp_path / "nope.md", tmp_path / "o.py",
                 generate=FakeGen(["a"]), run_tests=fake_runner([(1, 0, "")]),
                 max_rounds=1)


# ── 0 passed 는 통과가 아니다 (루프 자신이 저지른 조용한 실패) ────────────────

def test_zero_tests_run_is_not_a_pass(tmp_path):
    """실전 첫 투입에서 '0 passed, 0 failed [PASS]' 가 나왔다.

    pytest collection error 가 0/0 으로 파싱됐고 failed==0 이라 통과로 판정됐다.
    아무것도 돌지 않은 것은 성공이 아니다.
    """
    spec = tmp_path / "s.md"
    spec.write_text("x")
    result = run_loop(spec, tmp_path / "out.py", generate=FakeGen(["c1", "c2"]),
                      run_tests=fake_runner([(0, 0, "collection error"), (0, 0, "again")]),
                      max_rounds=2)
    assert result.ok is False


def test_a_round_with_zero_passed_does_not_stop_the_loop(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    gen = FakeGen(["c1", "c2"])
    run_loop(spec, tmp_path / "out.py", generate=gen,
             run_tests=fake_runner([(0, 0, "nothing ran"), (4, 0, "ok")]),
             max_rounds=3)
    assert len(gen.prompts) == 2, "0건은 통과가 아니므로 다음 라운드를 돌아야 한다"


def test_real_pass_still_stops_the_loop(tmp_path):
    spec = tmp_path / "s.md"
    spec.write_text("x")
    gen = FakeGen(["c1", "c2"])
    run_loop(spec, tmp_path / "out.py", generate=gen,
             run_tests=fake_runner([(4, 0, "ok")]), max_rounds=3)
    assert len(gen.prompts) == 1


# ── SPEC_FEEDBACK 을 코드 블록 안에서 받는다 ─────────────────────────────────
#
# nebius CLI 의 code 모드는 ```python 블록만 추출한다. 블록 밖에 쓴 SPEC_FEEDBACK 은
# 루프에 도달하기 전에 버려진다. 그래서 주석 형태로 블록 안에서 받는다.

def test_extracts_feedback_written_as_a_comment():
    text = "print('x')\n# SPEC_FEEDBACK: return type was never stated\n"
    assert "return type was never stated" in extract_spec_feedback(text)


def test_extracts_multiline_comment_feedback():
    text = """print('x')
# SPEC_FEEDBACK:
# - the timezone was unspecified
# - the error path was unclear
"""
    fb = extract_spec_feedback(text)
    assert "timezone was unspecified" in fb
    assert "error path was unclear" in fb


def test_comment_markers_are_stripped_from_feedback_text():
    """피드백 본문에 주석 기호가 남으면 사람이 읽기 나쁘다."""
    text = "code\n# SPEC_FEEDBACK:\n# - point one\n"
    fb = extract_spec_feedback(text)
    assert not fb.lstrip().startswith("#")
    assert "point one" in fb


def test_comment_feedback_is_removed_from_saved_code(tmp_path):
    out = tmp_path / "out.py"
    spec = tmp_path / "s.md"
    spec.write_text("x")
    run_loop(spec, out,
             generate=FakeGen(["print('hi')\n# SPEC_FEEDBACK: something was vague\n"]),
             run_tests=fake_runner([(1, 0, "ok")]), max_rounds=1)
    saved = out.read_text()
    assert "SPEC_FEEDBACK" not in saved
    assert "print('hi')" in saved


def test_feedback_saying_none_is_not_collected():
    """스펙이 명확했다면 수집할 게 없다 — 'none' 을 피드백으로 쌓지 않는다."""
    assert extract_spec_feedback("code\n# SPEC_FEEDBACK: none\n") == ""


def test_feedback_saying_none_case_insensitive():
    assert extract_spec_feedback("code\n# SPEC_FEEDBACK: None.\n") == ""


def test_retry_prompt_asks_for_comment_form(tmp_path):
    """프롬프트가 블록 안 주석으로 쓰라고 명시해야 한다."""
    spec = tmp_path / "s.md"
    spec.write_text("x")
    gen = FakeGen(["c1", "c2"])
    run_loop(spec, tmp_path / "out.py", generate=gen,
             run_tests=fake_runner([(0, 1, "f"), (1, 0, "ok")]), max_rounds=3)
    retry = gen.prompts[1]
    assert "# SPEC_FEEDBACK:" in retry
    assert "comment" in retry.lower()
