import httpx
import pytest
from fake_cloud import FakeServer

from inkbridge.transport.private_cloud import PCClient


@pytest.fixture()
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture()
def client(server: FakeServer) -> PCClient:
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    c = PCClient("http://cloud.test", http=http)
    c.login("user@test", "pw")
    return c
