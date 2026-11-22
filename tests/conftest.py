import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _never_a_real_toast(monkeypatch):
    """No test may show a Windows toast on this PC: the WinRT call is replaced by one that records nothing."""
    from nobadfind import notify

    def refuse(title, body):
        raise OSError("tests never show a real toast")
    monkeypatch.setattr(notify, "_winrt_toast", refuse)
