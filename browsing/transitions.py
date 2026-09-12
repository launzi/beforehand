"""Helper to convert Chrome page-transition integers into readable labels."""


def transition_label(transition: int | None) -> str:
    """Return a human-readable label for a Chrome page-transition value.

    The core transition type is encoded in the low byte (bits 0-7).
    Upper bits contain qualifier flags which are ignored.

    Args:
        transition: The integer transition value from Chrome, or None.

    Returns:
        A string label for the transition type, or "unknown" if not recognized.
    """
    if transition is None:
        return "unknown"

    # Extract the low byte (core type)
    core_type = transition & 0xFF

    # Map core types to labels
    labels = {
        0: "link",
        1: "typed",
        2: "bookmark",
        3: "auto_subframe",
        4: "manual_subframe",
        5: "generated",
        6: "start_page",
        7: "form_submit",
        8: "reload",
        9: "keyword",
        10: "keyword_generated",
    }

    return labels.get(core_type, "unknown")
