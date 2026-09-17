"""공통 픽스처. 네트워크는 절대 나가지 않고, 실제 ~/.swea-fetch 도 건드리지 않는다."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import pytest
import requests

from swea_fetcher import auth
from swea_fetcher.config import Settings
from swea_fetcher.models import ProblemInfo

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# 테스트용 더미 값 (실제 계정 아님)
DUMMY_ID = "dummy_user"
DUMMY_PW = "dummy-pw-1234"
CONTEST_PROB_ID = "AZq-gSmq_RfHBISS"


# --- 환경 격리 -------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_env():
    """SWEA_* 환경변수를 테스트 전후로 격리한다 (load_dotenv 가 os.environ 을 오염시키므로)."""
    saved = dict(os.environ)
    for k in list(os.environ):
        if k.startswith("SWEA_"):
            del os.environ[k]
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _reset_login_guard():
    auth._reset_process_guard()
    yield
    auth._reset_process_guard()


class FakeKeyringErrors:
    class KeyringError(Exception):
        pass

    class PasswordDeleteError(KeyringError):
        pass


class FakeKeyring:
    """keyring 모듈 대역. 메모리 dict 에 저장하고 호출을 기록한다. `fail` 을 세우면 KeyringError."""

    errors = FakeKeyringErrors

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.fail: Exception | None = None

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def get_password(self, service: str, user: str) -> str | None:
        self.calls.append(("get", service, user))
        self._check()
        return self.store.get((service, user))

    def set_password(self, service: str, user: str, password: str) -> None:
        self.calls.append(("set", service, user))
        self._check()
        self.store[(service, user)] = password

    def delete_password(self, service: str, user: str) -> None:
        self.calls.append(("delete", service, user))
        self._check()
        if (service, user) not in self.store:
            raise FakeKeyringErrors.PasswordDeleteError("no such password")
        del self.store[(service, user)]

    def get_keyring(self):  # _selftest 용
        return self


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    """실제 Windows 자격 증명 관리자를 절대 건드리지 않도록 config._keyring 을 대체한다."""
    from swea_fetcher import config

    kr = FakeKeyring()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    return kr


@pytest.fixture(autouse=True)
def _isolate_config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """config.CONFIG_DIR 기본값을 tmp 로 돌려 실제 ~/.swea-fetch 를 읽지 않게 한다."""
    from swea_fetcher import config

    d = tmp_path / "_default_cfg"
    d.mkdir()
    monkeypatch.setattr(config, "CONFIG_DIR", d)


# --- 파일 픽스처 -----------------------------------------------------------------


def load_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def solver_html() -> str:
    return load_fixture("problem_solver_page.html")


@pytest.fixture(scope="session")
def club_html() -> str:
    return load_fixture("problem_with_attachments.html")


@pytest.fixture(scope="session")
def error_html() -> str:
    return load_fixture("error_page.html")


@pytest.fixture(scope="session")
def login_html() -> str:
    return load_fixture("login_page.html")


@pytest.fixture(scope="session")
def detail_html() -> str:
    return load_fixture("problem_detail_regular.html")


# --- Settings ------------------------------------------------------------------


@pytest.fixture
def root_dir(tmp_path: Path) -> Path:
    d = tmp_path / "swea"
    d.mkdir()
    return d


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture
def settings(root_dir: Path, config_dir: Path) -> Settings:
    return Settings(root=root_dir, user_id=DUMMY_ID, password=DUMMY_PW, config_dir=config_dir)


@pytest.fixture
def problem_info() -> ProblemInfo:
    return ProblemInfo(
        contest_prob_id=CONTEST_PROB_ID,
        num=25730,
        title="항아리 게임",
        input_url=f"https://swexpertacademy.com/main/common/contestProb/contestProbDown.do?downType=in&contestProbId={CONTEST_PROB_ID}",
        output_url=f"https://swexpertacademy.com/main/common/contestProb/contestProbDown.do?downType=out&contestProbId={CONTEST_PROB_ID}",
        input_filename="input7_sample.txt",
        output_filename="output7_sample.txt",
        page_kind="solver",
    )


# --- 가짜 HTTP --------------------------------------------------------------------


class FakeResponse:
    """requests.Response 의 테스트에 필요한 부분만 흉내 낸다."""

    def __init__(
        self,
        status_code: int = 200,
        text: str | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        json_data: Any = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._json = json_data
        if content is not None:
            self.content = content
            self.text = content.decode("utf-8", errors="replace")
        elif text is not None:
            self.text = text
            self.content = text.encode("utf-8")
        elif json_data is not None:
            import json as _json

            self.text = _json.dumps(json_data)
            self.content = self.text.encode("utf-8")
        else:
            self.text = ""
            self.content = b""
        self.encoding: str | None = None

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        import json as _json

        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)  # type: ignore[arg-type]


def login_redirect() -> FakeResponse:
    return FakeResponse(
        302,
        text="",
        headers={"Location": "https://swexpertacademy.com/main/identity/anonymous/loginPage.do"},
    )


class FakeSession:
    """응답(또는 예외) 큐를 순서대로 돌려주는 가짜 세션. 호출 기록을 남긴다."""

    def __init__(self, responses: list[FakeResponse | Exception] | None = None) -> None:
        self.responses: list[FakeResponse | Exception] = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.cookies = requests.cookies.RequestsCookieJar()
        self.headers: dict[str, str] = {}
        self.handler: Callable[[str, str, dict[str, Any]], FakeResponse | Exception] | None = None

    def queue(self, *responses: FakeResponse | Exception) -> "FakeSession":
        self.responses.extend(responses)
        return self

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method.upper(), "url": url, **kwargs})
        if self.handler is not None:
            result = self.handler(method.upper(), url, kwargs)
        else:
            if not self.responses:
                raise AssertionError(f"예상하지 못한 요청: {method} {url}")
            result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch):
    """테스트가 실서버(SWEA/GitHub)에 닿지 않도록 requests 의 실제 전송과 업데이트 조회를 막는다."""
    from swea_fetcher import update

    def blocked(*_a, **_k):
        raise RuntimeError("테스트에서는 네트워크를 쓰지 않습니다")

    monkeypatch.setattr(update, "fetch_latest", blocked)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", blocked)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch):
    """client 의 재시도 대기를 없앤다."""
    from swea_fetcher import client

    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
