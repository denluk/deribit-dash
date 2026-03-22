from __future__ import annotations
from pathlib import Path
import streamlit as st

_LOGO = Path(__file__).parent.parent.parent / "assets" / "AiLer_Labs_logo.jpg"


def show_logo() -> None:
    """Render AiLer Labs logo in the sidebar."""
    if _LOGO.exists():
        st.sidebar.image(str(_LOGO), use_container_width=True)
    else:
        st.sidebar.caption("AiLer Labs")
