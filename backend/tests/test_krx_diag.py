"""KRX 로그인 실패 진단 로그: 나가는 IP·응답 앞부분 기록, 10분에 1회만 호출."""
import logging

import requests

from app.providers import krx


class _Resp:
    def __init__(self, text, status=200, ctype="text/html"):
        self.text, self.status_code, self.headers = text, status, {"content-type": ctype}
        self.url, self.history = krx.KRX_LOGIN_URL, []


def test_diagnose_logs_ip_and_body_once(monkeypatch, caplog):
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, **kw: calls.append(url) or _Resp("1.2.3.4"))
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: calls.append(url) or _Resp(""))
    monkeypatch.setattr(requests.Session, "post", lambda self, url, **kw: calls.append(url) or _Resp("\n\n<html>차단</html>"))
    monkeypatch.setattr(krx, "_last_diag", None)
    monkeypatch.setenv("KRX_PW", "secret-pw")

    with caplog.at_level(logging.ERROR, logger="app.providers.krx"):
        krx._diagnose_login()
        krx._diagnose_login()                  # 10분 안 두 번째 호출은 건너뜀

    assert len(calls) == 4                     # ipify + 준비 GET 2회 + 로그인 POST, 한 번만
    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "egress_ip=1.2.3.4" in msg and "<html>차단</html>" in msg
    assert "secret-pw" not in msg
