import pytest
import services.settings as st

@pytest.fixture(autouse=True)
def _bot_on_by_default(monkeypatch):
    monkeypatch.setattr(st, "_read_setting", lambda: None)
    st._cache.update(value=None, at=0.0)