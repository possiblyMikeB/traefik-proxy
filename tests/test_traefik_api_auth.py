"""Tests for the authentication to the traefik proxy api (dashboard)"""
import pytest
import utils

from urllib.parse import urlparse
from jupyterhub.utils import exponential_backoff
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "username, password, expected_rc",
    [("api_admin", "admin", 200), ("api_admin", "1234", 401), ("", "", 401)],
)
async def test_traefik_api_auth(
    etcd, clean_etcd, proxy, username, password, expected_rc
):
    # proxy = etcd_proxy
    traefik_port = urlparse(proxy.public_url).port

    await exponential_backoff(
        utils.check_host_up, "Traefik not reacheable", ip="localhost", port=traefik_port
    )

    try:
        if not username and not password:
            resp = await AsyncHTTPClient().fetch(proxy.traefik_api_url + "/dashboard")
        else:
            resp = await AsyncHTTPClient().fetch(
                proxy.traefik_api_url + "/dashboard/",
                auth_username=username,
                auth_password=password,
            )
        rc = resp.code
    except ConnectionRefusedError:
        rc = None
    except Exception as e:
        rc = e.response.code
    finally:
        assert rc == expected_rc
