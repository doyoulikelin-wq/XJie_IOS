from __future__ import annotations

import inspect

from app.routers import auth


def test_new_account_flows_do_not_default_to_ai_chat_consent() -> None:
    """All account creation paths require an explicit later consent action."""

    source = inspect.getsource(auth)

    assert "allow_ai_chat=True" not in source
    assert source.count("allow_ai_chat=False") >= 3
