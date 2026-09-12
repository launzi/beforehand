"""
Helper for converting Chrome page-transition integers into readable labels.
"""

def transition_label(transition: int | None) -> str:
    """
    Convert a Chrome page-transition integer to a human-readable label.

    The core transition type is stored in the low byte (bits 0-7).
    Upper bits contain qualifier flags and are ignored.

    Args:
        transition: The transition integer from Chrome, or None.

    Returns:
        A string label for the transition type, or "unknown" if not recognized.
    """
    if transition is None:
        return "unknown"

    # Extract the core type from the low byte
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

#