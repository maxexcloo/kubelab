"""Require private HTTPS connectivity and an authenticated SignTools UI."""

import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request


def check_connection(server_url):
    url = urllib.parse.urlsplit(server_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise RuntimeError("SignTools requires an HTTPS URL without embedded credentials")
    addresses = socket.getaddrinfo(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise RuntimeError("SignTools DNS returned no addresses")
    for address in addresses:
        host = ipaddress.ip_address(address[4][0])
        if host.is_global or host.is_loopback or host.is_link_local or host.is_unspecified or host.is_multicast:
            raise RuntimeError("SignTools must resolve exclusively to private or Tailscale addresses")
    try:
        with urllib.request.urlopen(server_url.rstrip("/") + "/", timeout=30):
            pass
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 401:
            return
        raise RuntimeError("SignTools returned an unexpected HTTP status") from None
    raise RuntimeError("SignTools did not require authentication")


if __name__ == "__main__":
    check_connection(os.environ["SECRET_URL"])
    print("Private HTTPS connection verified; the SignTools UI requires authentication.")
