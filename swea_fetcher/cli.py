"""진입점: `swea-fetch <target> <topic>` / `swea-fetch init` / `swea-fetch logout`.

파이프라인: settings → contestProbId 추출 → 세션 → 문제 페이지 → 파싱 → 첨부 다운로드 → 저장.
모든 도메인 예외는 SweaFetchError.exit_code 로 종료 코드에 매핑한다.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import getpass
import logging
import os
import sys
import traceback
from pathlib import Path

from . import auth, client, config, lookup, parser, storage
from .errors import (
    AlreadyExists,
    AttachmentNotFound,
    ConfigMissing,
    InvalidInput,
    LoginFailed,
    LoginLocked,
    MfaRequired,
    NetworkError,
    ParseError,
    ProblemNotFound,
    SweaFetchError,
)
from .models import ProblemInfo, SaveResult

log = logging.getLogger("swea_fetcher.cli")

SUBCOMMANDS = ("fetch", "init", "logout")
EXIT_UNEXPECTED = 10

TARGET_EXAMPLES = (
    "25730",
    "https://swexpertacademy.com/main/common/contestProb/contestProbDown.do?downType=in&contestProbId=AZq-gSmq_RfHBISS",
    "https://swexpertacademy.com/main/code/problem/problemDetail.do?contestProbId=AZq-gSmq_RfHBISS",
    "AZq-gSmq_RfHBISS",
)


# --- 인자 파싱 ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="swea-fetch",
        description="SWEA 문제의 샘플 입출력을 받아 swea/{주제}/{번호}/ 에 저장합니다.",
        epilog="서브커맨드를 생략하면 fetch 로 동작합니다: swea-fetch <target> <topic>",
    )
    sub = p.add_subparsers(dest="command")

    f = sub.add_parser("fetch", help="문제 저장 (기본)")
    f.add_argument(
        "target",
        help="문제 번호(예: 25730 — 문제 화면 상단에 보이는 숫자) 가 가장 쉽습니다. "
        "그 외 첨부파일 링크 URL, problemDetail.do URL, contestProbId 단독도 가능",
    )
    f.add_argument("topic", help="주제 폴더 이름 (예: BFS, Queue, IM_test)")
    f.add_argument("--num", type=int, default=None, help="페이지에서 번호를 못 찾았을 때 문제 번호를 직접 지정")
    f.add_argument("--force", action="store_true", help="input.txt / output.txt 를 덮어씁니다. {번호}.py 는 어떤 경우에도 덮어쓰지 않습니다")
    f.add_argument("--skeleton-only", action="store_true", help="첨부를 받지 않고 폴더 + {번호}.py + 빈 input.txt 만 만듭니다 (샘플 첨부가 없는 문제용)")
    f.add_argument("--dry-run", action="store_true", help="저장하지 않고 무엇을 어디에 저장할지만 보여줍니다")
    f.add_argument("--refresh-index", action="store_true", help="번호 색인 캐시를 무시하고 다시 찾습니다 (클럽에 새 문제 상자가 추가됐는데 번호로 못 찾을 때)")
    f.add_argument("-v", "--verbose", action="store_true", help="상세 로그(DEBUG)")

    i = sub.add_parser("init", help="계정 설정 (.env + 비밀번호는 Windows 자격 증명 관리자) + 로그인 확인")
    i.add_argument("--no-check", action="store_true", help="로그인 확인 생략")
    i.add_argument("--migrate", action="store_true", help="프롬프트 없이 .env 의 평문 SWEA_PW 를 자격 증명 관리자로 옮기고 .env 에서 제거")
    i.add_argument("-v", "--verbose", action="store_true", help="상세 로그(DEBUG)")

    lo = sub.add_parser("logout", help="저장된 세션 삭제")
    lo.add_argument("--all", action="store_true", help=".env 와 자격 증명 관리자의 비밀번호까지 삭제 — 자리 반납용")
    lo.add_argument("-v", "--verbose", action="store_true", help="상세 로그(DEBUG)")
    return p


def normalize_argv(argv: list[str]) -> list[str]:
    """첫 인자가 서브커맨드/도움말이 아니면 'fetch' 를 앞에 끼워 넣는다."""
    if not argv:
        return argv
    first = argv[0]
    if first in SUBCOMMANDS or first in ("-h", "--help"):
        return argv
    return ["fetch", *argv]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s" if verbose else "%(message)s",
        stream=sys.stderr,
        force=True,
    )
    if not verbose:
        # 기본 모드에선 cli 의 진행 메시지만 INFO 로 보이게 하고 하위 모듈은 WARNING 이상만
        for name in ("swea_fetcher.auth", "swea_fetcher.client", "swea_fetcher.parser", "swea_fetcher.storage"):
            logging.getLogger(name).setLevel(logging.WARNING)


# --- fetch ------------------------------------------------------------------------


def run_fetch(
    target: str,
    topic: str,
    num: int | None,
    force: bool,
    verbose: bool = False,
    skeleton_only: bool = False,
    dry_run: bool = False,
    refresh_index: bool = False,
) -> int:
    """파이프라인 실행. 성공 시 0. 도메인 예외는 main 이 처리한다."""
    settings = config.load_settings()
    by_number = target.strip().isdigit()
    cid = None if by_number else parser.extract_contest_prob_id(target)

    log.info("로그인 세션 확인")
    session = auth.get_session(settings)

    if by_number:
        log.info("문제 번호 %s 로 찾는 중 (공개 목록 → Solving Club 상자)", target.strip())
        cid = lookup.find_by_number(session, settings, int(target.strip()), refresh=refresh_index)

    log.info("문제 페이지 가져오는 중 (contestProbId=%s)", cid)
    html, kind = client.fetch_problem_page(session, settings, cid)
    log.debug("page_kind=%s, html=%d bytes", kind, len(html))
    info = parser.parse(html, kind, cid, require_attachments=not skeleton_only)

    if num is not None:
        if info.num is not None and info.num != num:
            log.warning("페이지의 번호 %s 대신 --num %s 를 사용합니다", info.num, num)
        info = dataclasses.replace(info, num=num)
    if info.num is None:
        raise InvalidInput("문제 번호를 페이지에서 찾지 못했습니다. --num 으로 지정하세요")

    topic = _resolve_topic(settings.root, topic)

    in_bytes = out_bytes = None
    if not skeleton_only:
        log.info("첨부 다운로드")
        in_bytes = client.download(session, info.input_url, settings)
        out_bytes = client.download(session, info.output_url, settings)

    if dry_run:
        _print_dry_run(info, topic, settings, in_bytes, out_bytes, force, skeleton_only)
        return 0

    try:
        if skeleton_only:
            result = storage.save_skeleton(settings.root, topic, info, settings)
        else:
            result = storage.save_problem(settings.root, topic, info, in_bytes, out_bytes, settings, force=force)
    except ValueError as e:
        raise InvalidInput(str(e)) from e

    log.info("저장 완료")
    _print_result(info, result, settings, skeleton_only)
    return 0


def _resolve_topic(root: Path, topic: str) -> str:
    """주제 폴더 이름 안내. 대소문자만 다른 기존 폴더가 있으면 그 이름을 쓰고, 비슷한 폴더는 알리기만 한다."""
    topic = topic.strip()
    try:
        dirs = sorted(d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))
    except OSError:
        return topic
    if topic in dirs:
        return topic
    same_ci = [d for d in dirs if d.lower() == topic.lower()]
    if same_ci:
        print(f"[알림] 기존 폴더 '{same_ci[0]}' 를 사용합니다 (입력: '{topic}')")
        return same_ci[0]
    close = difflib.get_close_matches(topic, dirs, n=3, cutoff=0.6)
    if close:
        print(f"[알림] 비슷한 폴더가 있습니다: {', '.join(close)} — 새 폴더 '{topic}' 를 만듭니다")
    return topic


def _preview(data: bytes | None, limit_lines: int = 3, limit_chars: int = 60) -> str:
    """앞 limit_lines 줄을 ' / ' 로 이어 붙인 미리보기 (한 줄 limit_chars 자 제한)."""
    if data is None:
        return ""
    text = storage.normalize_text(data)
    all_lines = text.splitlines()
    s = " / ".join(ln.strip() for ln in all_lines[:limit_lines])
    if len(all_lines) > limit_lines:
        s += " ..."
    return s if len(s) <= limit_chars else s[: limit_chars - 3] + "..."


def _print_dry_run(
    info: ProblemInfo,
    topic: str,
    settings: config.Settings,
    in_bytes: bytes | None,
    out_bytes: bytes | None,
    force: bool,
    skeleton_only: bool,
) -> None:
    """저장 없이 계획만 출력. 충돌 검사는 존재 여부만 본다 (쓰기 없음)."""
    try:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, info.num)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    print(f"[DRY-RUN] {info.num}. {info.title}  (page_kind={info.page_kind}, contestProbId={info.contest_prob_id})")
    print(f"  저장 예정: {problem_dir}{os.sep}")
    input_path = problem_dir / settings.input_name
    output_path = problem_dir / settings.output_name
    py_path = problem_dir / f"{info.num}.py"
    keep = "(기존 파일 유지)"
    if skeleton_only:
        print(f"    {settings.input_name:<12}{keep if input_path.exists() else '(빈 파일 생성 예정)'}")
    else:
        print(f"    {settings.input_name:<12}← {info.input_filename} ({len(in_bytes or b'')} B)   미리보기: {_preview(in_bytes)}")
        print(f"    {settings.output_name:<12}← {info.output_filename} ({len(out_bytes or b'')} B)   미리보기: {_preview(out_bytes)}")
    print(f"    {py_path.name:<12}{keep if py_path.exists() else '(생성 예정)'}")
    existing = [p for p in (input_path, output_path) if p.exists()]
    if existing and not skeleton_only:
        names = ", ".join(p.name for p in existing)
        print(f"  [주의] 이미 있음: {names} → " + ("--force 로 덮어쓰게 됩니다" if force else "실제 실행 시 AlreadyExists (--force 필요)"))


def _fmt_size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "?"
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB"


def _print_result(info: ProblemInfo, result: SaveResult, settings: config.Settings, skeleton_only: bool = False) -> None:
    written = set(result.written)
    skipped = set(result.skipped)
    if skeleton_only:
        print(f"[OK] {info.num}. {info.title} → {result.problem_dir} (뼈대만 — 샘플은 문제 페이지에서 직접 {settings.input_name} 에 붙여넣으세요)")
        rows = [(settings.input_name, "(빈 파일 생성)" if result.problem_dir / settings.input_name in written else "(기존 파일 유지)")]
    else:
        print(f"[OK] {info.num}. {info.title} → {result.problem_dir}")
        rows = [
            (settings.input_name, f"({_fmt_size(result.problem_dir / settings.input_name)}, 원본 {info.input_filename})"),
            (settings.output_name, f"({_fmt_size(result.problem_dir / settings.output_name)}, 원본 {info.output_filename})"),
        ]
    py = result.problem_dir / f"{info.num}.py"
    if py in written:
        rows.append((py.name, "(뼈대 생성)"))
    elif py in skipped:
        rows.append((py.name, "(기존 파일 유지)"))
    width = max(len(name) for name, _ in rows)
    for name, note in rows:
        print(f"     {name.ljust(width)}  {note}")


# --- init ---------------------------------------------------------------------------


def _quote_env(value: str) -> str:
    """python-dotenv 규칙: #, =, 공백, 따옴표가 있으면 큰따옴표로 감싼다."""
    if any(ch in value for ch in ' #="\'') or value != value.strip():
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        val = input(f"{prompt}{suffix}: ").strip()
        if val:
            return val
        if default:
            return default
        print("값을 입력하세요.")


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} [y/N]: ").strip().lower() in ("y", "yes")


def run_init(no_check: bool = False, config_dir: Path | None = None, migrate: bool = False) -> int:
    """.env 를 대화식으로 작성한다. 비밀번호는 getpass 로 받아 자격 증명 관리자(keyring)에만 저장한다.

    migrate=True 면 프롬프트 없이 .env 의 SWEA_PW 를 keyring 으로 옮기고 .env 에서 제거한다.
    """
    config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    env_file = config_dir / config.ENV_FILE_NAME

    if migrate:
        return _run_migrate(config_dir)

    if env_file.exists() and not _confirm(f"{env_file} 가 이미 있습니다. 덮어쓸까요?"):
        print("변경하지 않았습니다.")
        return 0

    default_root = Path.home() / "Desktop" / "swea"
    while True:
        root = Path(_ask("SWEA_ROOT (풀이 저장소 폴더)", str(default_root) if default_root.is_dir() else None)).expanduser()
        if root.is_dir():
            break
        print(f"폴더가 없습니다: {root} — 다시 입력하세요.")

    user_id = _ask("SWEA_ID (로그인 ID/이메일)")

    while True:
        pw1 = getpass.getpass("SWEA_PW (입력해도 화면에 표시되지 않습니다): ")
        pw2 = getpass.getpass("SWEA_PW 다시 입력: ")
        if pw1 and pw1 == pw2:
            break
        print("비밀번호가 비어 있거나 일치하지 않습니다. 다시 입력하세요.")

    config.save_password(user_id, pw1)  # keyring 실패 시 ConfigMissing → .env 는 쓰지 않음
    del pw1, pw2

    had_plain = bool(config.read_env_file(config_dir).get(config.PASSWORD_KEY))
    lines = [
        f"SWEA_ROOT={_quote_env(str(root))}",
        f"SWEA_ID={_quote_env(user_id)}",
        "SWEA_INPUT_NAME=input.txt",
        "SWEA_OUTPUT_NAME=output.txt",
    ]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] 설정 저장: {env_file} (비밀번호는 Windows 자격 증명 관리자 '{config.KEYRING_SERVICE}' 에 저장)")
    if had_plain:
        print("[OK] .env 의 평문 비밀번호를 자격 증명 관리자로 옮겼습니다")

    if no_check:
        return 0
    return _check_login(config_dir)


def _check_login(config_dir: Path) -> int:
    print("로그인 확인 중...")
    settings = config.load_settings(config_dir)
    auth.get_session(settings)  # 실패 시 예외 → main 이 메시지 출력, 설정은 유지
    print("[OK] 로그인 확인 완료. 세션 저장됨")
    return 0


def _run_migrate(config_dir: Path) -> int:
    """.env 의 SWEA_PW → keyring. 값은 어디에도 출력하지 않는다."""
    values = config.read_env_file(config_dir)
    user_id = (values.get("SWEA_ID") or "").strip()
    plain = values.get(config.PASSWORD_KEY) or ""
    if not user_id:
        raise ConfigMissing(".env 에 SWEA_ID 가 없어 옮길 수 없습니다. `swea-fetch init` 을 실행하세요")
    if not plain:
        already = bool(config.get_password(user_id))
        print("[OK] .env 에 평문 비밀번호가 없습니다." + (" 자격 증명 관리자에 이미 저장돼 있습니다." if already else " 옮길 것이 없습니다."))
        return 0
    config.save_password(user_id, plain)
    del plain
    config.strip_password_from_env_file(config_dir)
    print(f"[OK] .env 의 평문 비밀번호를 자격 증명 관리자('{config.KEYRING_SERVICE}' / {user_id})로 옮기고 .env 에서 제거했습니다")
    return 0


# --- logout -------------------------------------------------------------------------


def run_logout(all_: bool = False, config_dir: Path | None = None) -> int:
    """session.json, login_state.json 삭제. --all 이면 .env 도 삭제. 파일이 없어도 정상 종료."""
    config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
    targets = [config_dir / config.SESSION_FILE_NAME, config_dir / config.LOGIN_STATE_FILE_NAME]
    if all_:
        if not _confirm("계정 정보(.env 와 자격 증명 관리자의 비밀번호)가 삭제됩니다. 계속할까요?"):
            print("취소했습니다.")
            return 0
        user_id = (config.read_env_file(config_dir).get("SWEA_ID") or "").strip()
        if user_id:
            try:
                if config.delete_password(user_id):
                    print(f"[OK] 자격 증명 관리자에서 '{user_id}' 비밀번호 삭제")
            except ConfigMissing as e:
                print(f"[경고] 자격 증명 관리자 접근 실패: {e}", file=sys.stderr)
        targets.append(config_dir / config.ENV_FILE_NAME)

    removed = []
    for path in targets:
        try:
            path.unlink()
            removed.append(path.name)
        except FileNotFoundError:
            pass
    print(f"[OK] 삭제: {', '.join(removed) if removed else '삭제할 파일 없음'}")
    return 0


# --- 오류 안내 ------------------------------------------------------------------------


def _advice(e: SweaFetchError) -> str:
    if isinstance(e, ConfigMissing):
        return "`swea-fetch init` 을 먼저 실행하세요"
    if isinstance(e, LoginLocked):
        return f"브라우저에서 직접 로그인이 되는지 확인 후 {config.CONFIG_DIR / config.LOGIN_STATE_FILE_NAME} 을 삭제하세요"
    if isinstance(e, MfaRequired):
        return "계정에 2단계 인증이 켜져 있어 자동 로그인이 불가합니다. MFA 해제 또는 M3 수동 세션 주입 기능이 필요합니다"
    if isinstance(e, LoginFailed):
        n = auth._read_failures(config.CONFIG_DIR / config.LOGIN_STATE_FILE_NAME)
        return (
            ".env 의 SWEA_ID / SWEA_PW 를 확인하세요 (`swea-fetch init` 으로 재작성 가능). "
            f"현재 연속 실패 {n}회 — 5회면 계정이 잠깁니다"
        )
    if isinstance(e, InvalidInput):
        hint = ""
        if "찾지 못했습니다" in str(e) and "문제 번호" in str(e):
            hint = "  클럽에 새 문제 상자가 생긴 직후라면 --refresh-index 를 붙여 다시 시도하세요\n"
        return hint + "입력 예시 (문제 번호가 가장 쉽습니다):\n" + "\n".join(f"  swea-fetch {ex} BFS" for ex in TARGET_EXAMPLES)
    if isinstance(e, ProblemNotFound):
        return "contestProbId 가 맞는지, 해당 문제에 접근 권한이 있는지 확인하세요"
    if isinstance(e, ParseError):
        return "--num 으로 번호를 지정하거나, -v 로 실행한 결과를 제보해 주세요"
    if isinstance(e, AttachmentNotFound):
        found = ", ".join(e.found) if e.found else "없음"
        return (
            f"페이지에서 찾은 첨부: {found}\n"
            "  샘플 입출력 첨부가 없는 문제입니다. `--skeleton-only` 를 붙여 다시 실행하면 "
            "폴더 + {번호}.py + 빈 input.txt 만 만듭니다 (샘플은 본문에서 직접 복사)"
        )
    if isinstance(e, AlreadyExists):
        files = "\n".join(f"  {p}" for p in e.existing)
        return f"이미 있는 파일:\n{files}\n  덮어쓰려면 --force 를 붙이세요 ({{번호}}.py 는 유지됩니다)"
    if isinstance(e, NetworkError):
        return "네트워크 연결을 확인한 뒤 다시 시도하세요"
    return ""


# --- main -------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = normalize_argv(list(sys.argv[1:] if argv is None else argv))
    ap = build_parser()
    if not argv:
        ap.print_help()
        return 2
    args = ap.parse_args(argv)
    verbose = bool(getattr(args, "verbose", False))
    _setup_logging(verbose)

    try:
        if args.command == "init":
            return run_init(no_check=args.no_check, migrate=args.migrate)
        if args.command == "logout":
            return run_logout(all_=args.all)
        return run_fetch(
            args.target, args.topic, args.num, args.force, verbose,
            skeleton_only=args.skeleton_only, dry_run=args.dry_run, refresh_index=args.refresh_index,
        )
    except SweaFetchError as e:
        print(f"[오류] {e}", file=sys.stderr)
        advice = _advice(e)
        if advice:
            print(f"  → {advice}", file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("\n중단했습니다.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 — 예상 못한 오류는 exit 10
        if verbose:
            traceback.print_exc()
        else:
            print(f"[오류] 내부 오류: {type(e).__name__}: {e}", file=sys.stderr)
            print("  → -v 로 다시 실행하면 상세 출력이 나옵니다", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    sys.exit(main())
