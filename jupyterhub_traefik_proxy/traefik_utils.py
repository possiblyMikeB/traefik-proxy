import os
import string
from tempfile import NamedTemporaryFile
from traitlets import Unicode
from urllib.parse import unquote

import escapism
import toml

from contextlib import contextmanager
from collections import namedtuple


class KVStorePrefix(Unicode):
    def validate(self, obj, value):
        u = super().validate(obj, value)
        if not u.endswith("/"):
            u = u + "/"

        proxy_class = type(obj).__name__
        if "Consul" in proxy_class and u.startswith("/"):
            u = u[1:]

        return u


def generate_rule(routespec):
    routespec = unquote(routespec)
    if routespec.startswith("/"):
        # Path-based route, e.g. /proxy/path/
        # rule = "PathPrefix:" + routespec
        rule = f'PathPrefix(`{routespec}`)'
    else:
        # Host-based routing, e.g. host.tld/proxy/path/
        host, path_prefix = routespec.split("/", 1)
        path_prefix = "/" + path_prefix
        # rule = "Host:" + host + ";PathPrefix:" + path_prefix
        rule = f'Host(`{host}`) && PathPrefix(`{path_prefix}`)'
    return rule


def generate_alias(routespec, server_type=""):
    safe = string.ascii_letters + string.digits + "-"
    if routespec == '/':
        routespec = '/public' # has no effect on routing; only naming
    return server_type + escapism.escape(routespec.replace('/','-'), safe=safe)


def generate_backend_entry(
    proxy, backend_alias, separator="/", url=False, weight=False
):
    backend_entry = ""
    if separator is "/":
        backend_entry = proxy.kv_traefik_prefix
    backend_entry += separator.join(["http", "services", backend_alias, "loadbalancer"])
    if url is True:
        backend_entry += separator + separator.join(["servers", "0", "url"])
    elif weight is True:
        # XXX: UPDATE: Will be using `weight` for serverstransport assignment
        backend_entry += separator + "serverstransport"

    return backend_entry


def generate_frontend_backend_entry(proxy, frontend_alias):
    return proxy.kv_traefik_prefix + "http/routers/" + frontend_alias + "/service"


def generate_frontend_rule_entry(proxy, frontend_alias, separator="/"):
    frontend_rule_entry = separator.join(
        ["http", "routers", frontend_alias]
    )
    if separator == "/":
        frontend_rule_entry = (
            proxy.kv_traefik_prefix + frontend_rule_entry + separator + "rule"
        )

    return frontend_rule_entry


def generate_route_keys(proxy, routespec, desig="", separator="/"):
    backend_alias = generate_alias(routespec, desig)
    frontend_alias = backend_alias # doesn't matter in traefik v2 

    RouteKeys = namedtuple(
        "RouteKeys",
        [
            "backend_alias",
            "backend_url_path",
            "backend_weight_path",
            "frontend_alias",
            "frontend_backend_path",
            "frontend_rule_path"
            
        ],
    )

    if separator != ".":
        backend_url_path = generate_backend_entry(proxy, backend_alias, url=True)
        frontend_rule_path = generate_frontend_rule_entry(proxy, frontend_alias)
        backend_weight_path = generate_backend_entry(proxy, backend_alias, weight=True)
        frontend_backend_path = generate_frontend_backend_entry(proxy, frontend_alias)
    else:
        backend_url_path = generate_backend_entry(
            proxy, backend_alias, separator=separator
        )
        frontend_rule_path = generate_frontend_rule_entry(
            proxy, frontend_alias, separator=separator
        )
        backend_weight_path = ""
        frontend_backend_path = ""

    return RouteKeys(
        backend_alias,
        backend_url_path,
        backend_weight_path,
        frontend_alias,
        frontend_backend_path,
        frontend_rule_path,
    )


# atomic writing adapted from jupyter/notebook 5.7
# unlike atomic writing there, which writes the canonical path
# and only use the temp file for recovery,
# we write the temp file and then replace the canonical path
# to ensure that traefik never reads a partial file


@contextmanager
def atomic_writing(path):
    """Write temp file before copying it into place

    Avoids a partial file ever being present in `path`,
    which could cause traefik to load a partial routing table.
    """
    fileobj = NamedTemporaryFile(
        prefix=os.path.abspath(path) + "-tmp-", mode="w", delete=False
    )
    try:
        with fileobj as f:
            yield f
        os.replace(fileobj.name, path)
    finally:
        try:
            os.unlink(fileobj.name)
        except FileNotFoundError:
            # already deleted by os.replace above
            pass


def persist_static_conf(file, static_conf_dict):
    with open(file, "w") as f:
        toml.dump(static_conf_dict, f)


def persist_routes(file, routes_dict):
    with atomic_writing(file) as config_fd:
        toml.dump(routes_dict, config_fd)


def load_routes(file):
    try:
        with open(file, "r") as config_fd:
            return toml.load(config_fd)
    except:
        raise
