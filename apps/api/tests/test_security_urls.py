import socket

import pytest

from app.security.urls import UnsafeUrlError, ensure_public_url, ensure_salesforce_instance_url


def resolving_to(monkeypatch, *addresses):
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 0)) for a in addresses]

    monkeypatch.setattr("app.security.urls.socket.getaddrinfo", fake)


class TestEnsurePublicUrl:
    def test_a_public_https_url_is_accepted(self, monkeypatch):
        resolving_to(monkeypatch, "93.184.216.34")
        assert ensure_public_url("https://hooks.example.com/revops?x=1") == "https://hooks.example.com/revops?x=1"

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "127.1.2.3",
            "10.0.0.5",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "169.254.169.254",  # cloud metadata
            "100.64.0.1",  # carrier-grade NAT
            "0.0.0.0",
            "224.0.0.1",
            "::1",
            "fe80::1",
            "fc00::1",
            "::ffff:127.0.0.1",  # an IPv4 address written as IPv6
            "::ffff:10.0.0.1",
        ],
    )
    def test_a_host_that_resolves_to_a_non_public_address_is_refused(self, monkeypatch, address):
        resolving_to(monkeypatch, address)
        with pytest.raises(UnsafeUrlError, match="non-public address"):
            ensure_public_url("https://sneaky.example.com/")

    def test_one_private_address_among_public_ones_is_enough_to_refuse(self, monkeypatch):
        resolving_to(monkeypatch, "93.184.216.34", "10.0.0.1")
        with pytest.raises(UnsafeUrlError):
            ensure_public_url("https://mixed.example.com/")

    @pytest.mark.parametrize(
        "url",
        ["http://127.0.0.1/", "https://127.0.0.1:8080/", "https://[::1]/", "https://169.254.169.254/latest/meta-data/"],
    )
    def test_ip_literals_are_checked_too(self, url):
        with pytest.raises(UnsafeUrlError):
            ensure_public_url(url)

    def test_plain_http_is_refused_by_default(self, monkeypatch):
        resolving_to(monkeypatch, "93.184.216.34")
        with pytest.raises(UnsafeUrlError, match="https"):
            ensure_public_url("http://hooks.example.com/")

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://example.com/",
            "file:///etc/passwd",
            "gopher://example.com/",
            "javascript:alert(1)",
            "//example.com/",
            "example.com",
            "",
        ],
    )
    def test_other_schemes_and_non_urls_are_refused(self, monkeypatch, url):
        resolving_to(monkeypatch, "93.184.216.34")
        with pytest.raises(UnsafeUrlError):
            ensure_public_url(url)

    @pytest.mark.parametrize(
        "url", ["https://user:pass@example.com/", "https://user@example.com/", "https://:pass@example.com/"]
    )
    def test_embedded_credentials_are_refused(self, monkeypatch, url):
        resolving_to(monkeypatch, "93.184.216.34")
        with pytest.raises(UnsafeUrlError, match="user name or password"):
            ensure_public_url(url)

    @pytest.mark.parametrize("url", ["https://example.com:notaport/", "https://example.com:99999/"])
    def test_a_bad_port_is_refused(self, monkeypatch, url):
        resolving_to(monkeypatch, "93.184.216.34")
        with pytest.raises(UnsafeUrlError, match="not a valid URL"):
            ensure_public_url(url)

    def test_a_resolver_that_returns_nothing_is_refused(self, monkeypatch):
        monkeypatch.setattr("app.security.urls.socket.getaddrinfo", lambda *args, **kwargs: [])
        with pytest.raises(UnsafeUrlError):
            ensure_public_url("https://empty.example.com/")

    def test_the_url_that_was_checked_is_the_one_returned(self, monkeypatch):
        resolving_to(monkeypatch, "93.184.216.34")
        assert ensure_public_url("  https://example.com/hook \n") == "https://example.com/hook"

    def test_a_host_that_does_not_resolve_is_refused(self, monkeypatch):
        def fail(*args, **kwargs):
            raise socket.gaierror("no such host")

        monkeypatch.setattr("app.security.urls.socket.getaddrinfo", fail)
        with pytest.raises(UnsafeUrlError, match="does not resolve"):
            ensure_public_url("https://nowhere.invalid/")

    def test_the_message_does_not_reveal_the_address(self, monkeypatch):
        resolving_to(monkeypatch, "10.20.30.40")
        with pytest.raises(UnsafeUrlError) as exc:
            ensure_public_url("https://internal.example.com/")
        assert "10.20.30.40" not in str(exc.value)

    def test_the_opt_in_setting_allows_local_targets_and_plain_http(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "webhook_allow_private_targets", True)
        assert ensure_public_url("http://127.0.0.1:9000/hook") == "http://127.0.0.1:9000/hook"
        with pytest.raises(UnsafeUrlError, match="no host"):
            ensure_public_url("http:///path")  # still has to be a URL with a host
        with pytest.raises(UnsafeUrlError):
            ensure_public_url("ftp://127.0.0.1/")  # and still http(s)

    def test_explicit_arguments_override_the_setting(self, monkeypatch):
        resolving_to(monkeypatch, "127.0.0.1")
        assert ensure_public_url("http://localhost/", allow_private=True, allow_http=True)
        assert ensure_public_url(
            "https://localhost/", allow_private=True, allow_http=True
        )  # https is still fine when http is allowed too
        with pytest.raises(UnsafeUrlError):
            ensure_public_url("http://localhost/", allow_private=False, allow_http=True)


class TestSalesforceInstanceUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://acme.my.salesforce.com",
            "https://acme.my.salesforce.com/",
            "https://acme--sandbox.sandbox.my.salesforce.com",
            "https://na1.salesforce.com",
            "https://acme.lightning.force.com",
            "https://ACME.My.Salesforce.COM",
        ],
    )
    def test_salesforce_hosts_are_accepted_without_a_trailing_slash(self, url):
        assert ensure_salesforce_instance_url(url) == url.rstrip("/")

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com",
            "https://salesforce.com.evil.example.com",
            "https://evilsalesforce.com",
            "https://notsalesforce.com",
            "https://salesforce.com",  # the bare apex: only subdomains are Salesforce instances
            "http://acme.my.salesforce.com",
            "https://acme.my.salesforce.com@evil.example.com",
            "https://user:pw@acme.my.salesforce.com",
            "https://127.0.0.1",
            "https://acme.my.salesforce.com.",
            "",
        ],
    )
    def test_everything_else_is_refused(self, url):
        if url == "https://acme.my.salesforce.com.":
            assert ensure_salesforce_instance_url(url)  # a trailing dot is the same host
            return
        with pytest.raises(UnsafeUrlError):
            ensure_salesforce_instance_url(url)

    def test_the_allowed_domains_are_configurable(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "salesforce_allowed_domains", ".salesforce.mil, crm.example.org")
        assert ensure_salesforce_instance_url("https://x.salesforce.mil")
        assert ensure_salesforce_instance_url("https://org.crm.example.org")
        with pytest.raises(UnsafeUrlError):
            ensure_salesforce_instance_url("https://x.salesforce.com")
