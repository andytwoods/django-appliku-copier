"""Check and truncate Docker container log files on Appliku servers."""
import argparse
import sys

from colorama import Fore, Style, init as colorama_init

from appliku_cli.api import ApplikuAPIError, ApplikuClient
from appliku_cli.credentials import load_credentials

colorama_init(autoreset=True)

DEFAULT_WARN_MB = 100
DEFAULT_WIPE_MB = 1000  # prompt to wipe above 1 GB by default


def _ok(msg: str) -> str:   return f"{Fore.GREEN}{msg}{Style.RESET_ALL}"
def _warn(msg: str) -> str: return f"{Fore.YELLOW}{msg}{Style.RESET_ALL}"
def _err(msg: str) -> str:  return f"{Fore.RED}{msg}{Style.RESET_ALL}"
def _bold(msg: str) -> str: return f"{Style.BRIGHT}{msg}{Style.RESET_ALL}"
def _dim(msg: str) -> str:  return f"{Style.DIM}{msg}{Style.RESET_ALL}"


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _run(client: ApplikuClient, server_id: int, cmd: str, timeout: int = 60) -> str:
    """Run a command on the server via the Appliku API and return its stdout."""
    result = client.run_server_command(server_id, cmd, username="root", sudo=True)
    run_id = result["id"]
    text, _status = client.poll_server_command(run_id, timeout=timeout)
    # Strip Appliku's connection header and trailing finish line; keep only command output.
    # Header ends after the "??? Connection to ..." line; output ends before "+++ Finished".
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("??? Connection"):
            start = i + 1
            break
    end = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("+++ Finished"):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def _parse_log_sizes(output: str) -> list[tuple[int, str]]:
    """Parse `find -printf '%s %p'` output → [(bytes, path), ...] sorted desc."""
    entries = []
    for line in output.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            try:
                entries.append((int(parts[0]), parts[1].strip()))
            except ValueError:
                continue
    return sorted(entries, reverse=True)


def _container_names(client: ApplikuClient, server_id: int) -> dict[str, str]:
    """Return {short_id: container_name} for all containers on the server."""
    out = _run(client, server_id, "docker ps -a --format '{{.ID}} {{.Names}}'")
    names: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            names[parts[0]] = parts[1]
    return names


def _resolve_name(path: str, id_to_name: dict[str, str]) -> str:
    full_id = path.split("/")[-2]  # …/containers/{full_id}/{full_id}-json.log
    return id_to_name.get(full_id[:12], full_id[:12])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check Docker container log file sizes on Appliku servers "
            "and optionally truncate large ones."
        )
    )
    parser.add_argument(
        "--warn-mb", type=int, default=DEFAULT_WARN_MB,
        help=f"Report logs above this size in MB (default: {DEFAULT_WARN_MB})",
    )
    parser.add_argument(
        "--wipe-mb", type=int, default=DEFAULT_WIPE_MB,
        help=f"Prompt to wipe logs above this size in MB (default: {DEFAULT_WIPE_MB})",
    )
    parser.add_argument(
        "--auto-wipe", action="store_true",
        help="Wipe logs above --wipe-mb without prompting",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Print raw command output for troubleshooting",
    )
    args = parser.parse_args()

    warn_bytes = args.warn_mb * 1024 * 1024
    wipe_bytes = args.wipe_mb * 1024 * 1024

    credentials = load_credentials()
    if not credentials.team_path:
        client_no_team = ApplikuClient(api_key=credentials.api_key)
        teams = client_no_team.list_teams()
        if not teams:
            print(_err("No teams found on your Appliku account."))
            sys.exit(1)
        credentials.team_path = teams[0]["team_path"]

    client = ApplikuClient(api_key=credentials.api_key, team_path=credentials.team_path)

    try:
        servers = client.list_servers()
    except ApplikuAPIError as exc:
        print(_err(f"Failed to list servers: {exc}"))
        sys.exit(1)

    if not servers:
        print(_warn("No servers found."))
        return

    for server in servers:
        server_id = server.get("id")
        srv_name = server.get("name", str(server_id))

        print()
        print(_bold("═" * 64))
        print(_bold(f"  {srv_name}"))
        print(_bold("═" * 64))

        if not server_id:
            print(_warn("  Server has no ID — skipping."))
            continue

        print(_dim("  Fetching log sizes…"))
        try:
            out = _run(
                client, server_id,
                "find /var/lib/docker/containers -name '*-json.log' -printf '%s %p\\n' 2>/dev/null",
                timeout=30,
            )
        except ApplikuAPIError as exc:
            print(_err(f"  API error: {exc}"))
            continue

        if not out:
            print(_warn("  No output from server (command may have failed or no log files exist)."))
            continue

        if args.debug:
            print(_dim(f"  Raw output ({len(out)} chars):"))
            print(_dim(f"  {repr(out[:500])}"))

        entries = _parse_log_sizes(out)
        total = len(entries)
        over_warn = sum(1 for size, _ in entries if size >= warn_bytes)
        over_wipe = sum(1 for size, _ in entries if size >= wipe_bytes)

        print(f"  Log files found: {_bold(str(total))}   "
              f"over {args.warn_mb} MB: {_warn(str(over_warn)) if over_warn else _ok('0')}   "
              f"over {args.wipe_mb} MB: {_err(str(over_wipe)) if over_wipe else _ok('0')}")

        if not entries:
            print(_ok("  No log files found."))
            continue

        # Resolve container IDs → names in one API call
        try:
            id_to_name = _container_names(client, server_id)
        except ApplikuAPIError:
            id_to_name = {}

        # Report
        to_wipe: list[tuple[int, str]] = []
        shown_any = False

        for size_bytes, path in entries:
            if size_bytes < warn_bytes:
                break
            shown_any = True
            name = _resolve_name(path, id_to_name)
            size_str = _fmt_bytes(size_bytes)

            if size_bytes >= wipe_bytes:
                print(f"  {_err('[HUGE]')}   {size_str:>10}  {name}")
                to_wipe.append((size_bytes, path))
            else:
                print(f"  {_warn('[LARGE]')}  {size_str:>10}  {name}")

        if not shown_any:
            continue  # summary line already printed above

        if not to_wipe:
            print()
            print(_warn(f"  No logs above wipe threshold ({args.wipe_mb} MB)."))
            continue

        # Wipe prompt
        print()
        if args.auto_wipe:
            confirmed = True
        else:
            print(_warn(f"  {len(to_wipe)} log(s) exceed {args.wipe_mb} MB:"))
            for size_bytes, path in to_wipe:
                name = _resolve_name(path, id_to_name)
                print(f"    {_fmt_bytes(size_bytes):>10}  {name}")
            print()
            answer = input(_warn("  Wipe them all? [y/N] ")).strip().lower()
            confirmed = answer == "y"

        if not confirmed:
            print(_warn("  Skipped."))
            continue

        for size_bytes, path in to_wipe:
            name = _resolve_name(path, id_to_name)
            try:
                _run(client, server_id, f"truncate -s 0 {path}", timeout=15)
                print(_ok(f"  ✓ Wiped {name}  ({_fmt_bytes(size_bytes)} freed)"))
            except ApplikuAPIError as exc:
                print(_err(f"  ✗ Failed to wipe {name}: {exc}"))

    print()
    print(_bold("═" * 64))
