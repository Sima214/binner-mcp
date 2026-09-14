"""Shared pytest fixtures for Binner MCP proxy tests."""
import pytest
from binner_mcp.api.client import BinnerAPIProxy


@pytest.fixture
def proxy() -> BinnerAPIProxy:
    """Fixture providing an unauthenticated mock BinnerAPIProxy."""
    return BinnerAPIProxy(
        base_url="http://mock-binner:8090",
        username="test_user",
        password="test_password",
        timeout=2.0,
    )


# Live instance probe
_proxy_check = BinnerAPIProxy(base_url="http://127.0.0.1:8090", timeout=2.0)
_live_available = _proxy_check.ping()


def is_live_available() -> bool:
    """Check if the live Binner instance is running."""
    return _live_available


@pytest.fixture(scope="module")
def live_proxy() -> BinnerAPIProxy:
    """Fixture providing an authenticated BinnerAPIProxy to the live local instance."""
    if not _live_available:
        pytest.skip("Live Binner instance not reachable at http://127.0.0.1:8090")
    proxy = BinnerAPIProxy(
        base_url="http://127.0.0.1:8090",
        username="admin",
        password="admin",
        timeout=10.0,
    )
    proxy.login()
    return proxy
