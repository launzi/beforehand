"""Chrome transition 정수 → 사람이 읽는 라벨."""
import pytest
from browsing.transitions import transition_label


@pytest.mark.parametrize("core,label", [
    (0, "link"), (1, "typed"), (2, "bookmark"), (3, "auto_subframe"),
    (4, "manual_subframe"), (5, "generated"), (6, "start_page"),
    (7, "form_submit"), (8, "reload"), (9, "keyword"), (10, "keyword_generated"),
])
def test_known_core_types(core, label):
    assert transition_label(core) == label


def test_masks_qualifier_bits():
    """Chrome 은 상위 비트에 qualifier 를 얹는다. 하위 8비트만 core 다."""
    assert transition_label(0x18000000 | 1) == "typed"


def test_unknown_core_returns_unknown():
    assert transition_label(99) == "unknown"


def test_none_is_unknown():
    assert transition_label(None) == "unknown"


def test_negative_is_unknown():
    assert transition_label(-1) == "unknown"
