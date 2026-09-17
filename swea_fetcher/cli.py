"""진입점: `swea-fetch <target> <topic>` / `init` / `logout` / `check` / `doctor` / `push`.

파이프라인 로직은 service.py 에 있고, 여기서는 인자 파싱·출력·종료 코드만 다룬다.
모든 도메인 예외는 SweaFetchError.exit_code 로 종료 코드에 매핑하고 e.hint 를 조치 문구로 출력한다.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import traceback
from pathlib import Path

from . import auth, checker, config, doctor, service, update
from .errors import CheckFailed, ConfigMissing, InvalidInput, LoginFailed, SweaFetchError
from .models import ProblemInfo, SaveResult
from .service import FetchOptions, FetchOutcome

log = logging.getLogger("swea_fetcher.cli")

SUBCOMMANDS = ("fetch", "init", "logout", "check", "doctor", "push")
EXIT_UNEXPECTED = 10


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
    f.add_argument("topic", help="주제 폴더 이름 (예: BFS, Queue, IM_test). test/IM_test 처럼 중첩 가능")
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

    c = sub.add_parser("check", help="풀이 실행 후 output.txt 와 비교")
    c.add_argument("topic", help="주제 폴더 이름 (test/IM_test 처럼 중첩 가능)")
    c.add_argument("num", type=int, help="문제 번호")
    c.add_argument("--timeout", type=float, default=checker.DEFAULT_TIMEOUT, help="실행 제한 시간(초), 기본 10")
    c.add_argument("--push", action="store_true", help="검증 통과 시에만 문제 폴더를 git 커밋 + 푸시 (M7). 실패면 푸시하지 않음")
    c.add_argument("-v", "--verbose", action="store_true", help="상세 로그(DEBUG)")

    g = sub.add_parser("push", help="문제 폴더만 git 커밋 + 푸시 (루트가 git 저장소여야 함. force push 없음)")
    g.add_argument("topic", help="주제 폴더 이름 (test/IM_test 처럼 중첩 가능)")
    g.add_argument("num", type=int, help="문제 번호")
    g.add_argument("-m", "--message", default=None, help="커밋 메시지. 생략하면 템플릿(SWEA_COMMIT_TEMPLATE) 사용")
    g.add_argument("--no-push", action="store_true", help="커밋만 하고 푸시하지 않음")
    g.add_argument("-v", "--verbose", action="store_true", help="상세 로그(DEBUG)")

    d = sub.add_parser("doctor", help="진단 정보 출력 (문의할 때 이 출력을 이슈에 붙여 주세요. 비밀번호·쿠키는 포함되지 않음)")
    d.add_argument("--offline", action="store_true", help="네트워크 없이 로컬 정보만 (로그인 상태·최신 버전 생략)")
    d.add_argument("-v", "--verbose", action="store_true", help="상세 로그(DEBUG)")

    for sp in (f, i, lo, c, d, g):
        sp.add_argument("--no-update-check", action="store_true", help="이번 실행에서 새 버전 확인을 하지 않습니다")
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
        # 기본 모드에선 진행 메시지(service)만 INFO 로 보이게 하고 하위 모듈은 WARNING 이상만
        for name in ("swea_fetcher.auth", "swea_fetcher.client", "swea_fetcher.parser", "swea_fetcher.storage", "swea_fetcher.lookup"):
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
    """service.fetch_problem 호출 + 출력. 도메인 예외는 main 이 처리한다."""
    settings = config.load_settings()
    opts = FetchOptions(force=force, skeleton_only=skeleton_only, dry_run=dry_run, refresh_index=refresh_index, num_override=num)

    def progress(msg: str) -> None:
        if msg.startswith("[알림]"):
            print(msg)

    outcome = service.fetch_problem(settings, target, topic, opts, progress)
    if outcome.result is None:
        _print_dry_run(outcome, settings, force, skeleton_only)
    else:
        _print_result(outcome.info, outcome.result, settings, skeleton_only)
    return 0


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


def _print_dry_run(outcome: FetchOutcome, settings: config.Settings, force: bool, skeleton_only: bool) -> None:
    info, pv = outcome.info, outcome.preview or {}
    print(f"[DRY-RUN] {info.num}. {info.title}  (page_kind={info.page_kind}, contestProbId={info.contest_prob_id})")
    print(f"  저장 예정: {pv['problem_dir']}{os.sep}")
    labels = {"create": "(생성 예정)", "create_empty": "(빈 파일 생성 예정)", "keep": "(기존 파일 유지)", "overwrite": "(덮어쓰기 예정)", "conflict": "(이미 있음)"}
    for fp in pv["files"]:
        if fp.source is not None:
            print(f"    {fp.name:<12}← {fp.source} ({fp.size} B)   미리보기: {fp.preview}")
        else:
            print(f"    {fp.name:<12}{labels.get(fp.action, fp.action)}")
    conflicts = [fp.name for fp in pv["files"] if fp.action in ("conflict", "overwrite")]
    if conflicts and not skeleton_only:
        print(f"  [주의] 이미 있음: {', '.join(conflicts)} → " + ("--force 로 덮어쓰게 됩니다" if force else "실제 실행 시 AlreadyExists (--force 필요)"))


# --- init ---------------------------------------------------------------------------


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
    service.write_env(config_dir, root, user_id)
    print(f"[OK] 설정 저장: {env_file} (비밀번호는 Windows 자격 증명 관리자 '{config.KEYRING_SERVICE}' 에 저장)")
    if had_plain:
        print("[OK] .env 의 평문 비밀번호를 자격 증명 관리자로 옮겼습니다")

    if no_check:
        return 0
    print("로그인 확인 중...")
    msg = service.verify_login(config.load_settings(config_dir))  # 실패 시 예외 → main 이 메시지 출력, 설정은 유지
    print(f"[OK] {msg}")
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
    """session.json, login_state.json 삭제. --all 이면 .env 와 자격 증명도. 파일이 없어도 정상 종료."""
    config_dir = Path(config_dir) if config_dir is not None else config.CONFIG_DIR
    if all_ and not _confirm("계정 정보(.env 와 자격 증명 관리자의 비밀번호)가 삭제됩니다. 계속할까요?"):
        print("취소했습니다.")
        return 0
    try:
        removed = service.logout(config_dir, all_=all_)
    except ConfigMissing as e:  # keyring 접근 불가 — 파일만이라도 지운다
        print(f"[경고] 자격 증명 관리자 접근 실패: {e}", file=sys.stderr)
        removed = service.logout(config_dir, all_=False)
    print(f"[OK] 삭제: {', '.join(removed) if removed else '삭제할 파일 없음'}")
    return 0


# --- check --------------------------------------------------------------------------


def run_check(topic: str, num: int, timeout: float, push: bool = False) -> int:
    """풀이 실행 → 비교 → 결과 출력. 실패면 CheckFailed (exit 6). push=True 면 통과 시에만 커밋+푸시 (M7)."""
    settings = config.load_settings()
    from . import storage  # 지연 import — resolve_problem_dir 만 필요

    try:
        problem_dir = storage.resolve_problem_dir(settings.root, topic, num)
    except ValueError as e:
        raise InvalidInput(str(e)) from e
    if not problem_dir.is_dir():
        raise InvalidInput(f"문제 폴더가 없습니다: {problem_dir}")

    res = checker.run_and_compare(problem_dir, settings, timeout=timeout)
    status = "통과" if res.passed else ("시간 초과" if res.timed_out else "실패")
    print(f"[{'OK' if res.passed else 'FAIL'}] {num} {status}  ({res.elapsed:.2f}s)  {problem_dir}")
    if res.note:
        print(f"  {res.note}")
    if not res.passed or res.stderr:
        if res.stderr.strip():
            print("--- stderr ---")
            print(res.stderr.rstrip())
        print("--- 기대 vs 실제 ---")
        print(checker.format_diff(res.diff) if res.diff else "(출력 없음)")
    if not res.passed:
        raise CheckFailed(f"{num} 검증 실패 ({status})", hint="검증 실패 — 푸시하지 않음" if push else "")
    if push:
        return run_push(topic, num, message=None, push=True)
    return 0


def run_push(topic: str, num: int, message: str | None, push: bool) -> int:
    """문제 폴더만 커밋(+푸시). 전제 조건 미충족·git 실패는 GitError (exit 7)."""
    settings = config.load_settings()
    result = service.push_problem(settings, topic, num, message=message, push=push)
    print(f"[OK] {result.note}" + (f"  — {result.message}" if result.committed else ""))
    return 0


# --- main -------------------------------------------------------------------------------


def run_doctor(offline: bool) -> int:
    print(doctor.report(offline=offline))
    return 0


def _print_update_notice() -> None:
    """명령 끝에 한 줄 (하루 1회 조회, 실패는 무음). doctor 는 자체 항목이 있어 생략."""
    line = update.notice(config.CONFIG_DIR)
    if line:
        print(line, file=sys.stderr)


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
        return _dispatch(args, verbose)
    finally:
        if args.command != "doctor" and not getattr(args, "no_update_check", False):
            try:
                _print_update_notice()
            except Exception:  # noqa: BLE001 — 알림은 본 작업 결과에 영향을 주지 않는다
                pass


def _dispatch(args: argparse.Namespace, verbose: bool) -> int:
    try:
        if args.command == "init":
            return run_init(no_check=args.no_check, migrate=args.migrate)
        if args.command == "logout":
            return run_logout(all_=args.all)
        if args.command == "check":
            return run_check(args.topic, args.num, args.timeout, push=args.push)
        if args.command == "push":
            return run_push(args.topic, args.num, message=args.message, push=not args.no_push)
        if args.command == "doctor":
            return run_doctor(offline=args.offline)
        return run_fetch(
            args.target, args.topic, args.num, args.force, verbose,
            skeleton_only=args.skeleton_only, dry_run=args.dry_run, refresh_index=args.refresh_index,
        )
    except SweaFetchError as e:
        print(f"[오류] {e}", file=sys.stderr)
        hint = _hint_for(e)
        if hint:
            print(f"  → {hint}", file=sys.stderr)
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


def _hint_for(e: SweaFetchError) -> str:
    """예외의 hint 에 cli 전용 보강(연속 실패 횟수, --refresh-index 안내)을 붙인다."""
    hint = e.hint
    if type(e) is LoginFailed:
        n = auth._read_failures(config.CONFIG_DIR / config.LOGIN_STATE_FILE_NAME)
        hint = f"{hint} — 현재 도구 기록 연속 실패 {n}회"
    if isinstance(e, InvalidInput) and "찾지 못했습니다" in str(e) and "문제 번호" in str(e):
        hint = "클럽에 새 문제 상자가 생긴 직후라면 --refresh-index 를 붙여 다시 시도하세요\n" + hint
    return hint.replace("\n", "\n    ")


if __name__ == "__main__":
    sys.exit(main())
