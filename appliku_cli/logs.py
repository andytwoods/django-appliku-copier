"""Check and truncate Docker container log files on Appliku servers."""
import argparse
import subprocess
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


def _ssh(host: str, cmd: str, user: str = "root") -> tuple[str, int]:
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                "-o", "BatchMode=yes",
                f"{user}@{host}",
                cmd,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", 1


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _container_names(host: str) -> dict[str, str]:
    """Return {short_id: container_name} for all containers via docker ps -a."""
    out, rc = _ssh(host, "docker ps -a --format '{{.ID}} {{.Names}}'")
    names: dict[str, str] = {}
    if rc != 0 or not out:
        return names
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            names[parts[0]] = parts[1]
    return names


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


def _server_ip(server: dict) -> str | None:
    for key in ("ip", "ip_address", "host", "hostname"):
        val = (server.get(key) or "").strip()
        if val:
            return val
    return None


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
        ip = _server_ip(server)
        srv_name = server.get("name", ip or "unknown")

        print()
        print(_bold("═" * 64))
        print(_bold(f"  {srv_name}  ({ip or 'no IP'})"))
        print(_bold("═" * 64))

        if not ip:
            print(_warn("  No IP address — cannot SSH. Skipping."))
            continue

        # Fetch log file sizes via SSH
        out, rc = _ssh(
            ip,
            "find /var/lib/docker/containers -name '*-json.log' -printf '%s %p\\n' 2>/dev/null",
        )
        if not out:
            print(_warn("  Could not read log sizes (SSH failed or no logs found)."))
            print(_dim(f"  Tip: ensure your SSH key allows access to root@{ip}"))
            continue

        entries = _parse_log_sizes(out)
        if not entries:
            print(_ok("  No container log files found."))
            continue

        # Resolve short container IDs → names once
        id_to_name = _container_names(ip)

        # Report
        to_wipe: list[tuple[int, str]] = []
        shown_any = False

        for size_bytes, path in entries:
            if size_bytes < warn_bytes:
                break  # list is sorted descending — nothing bigger below
            shown_any = True
            name = _resolve_name(path, id_to_name)
            size_str = _fmt_bytes(size_bytes)

            if size_bytes >= wipe_bytes:
                print(f"  {_err('[HUGE]')}   {size_str:>10}  {name}")
                to_wipe.append((size_bytes, path))
            else:
                print(f"  {_warn('[LARGE]')}  {size_str:>10}  {name}")

        if not shown_any:
            print(_ok(f"  All log files are under {args.warn_mb} MB."))
            continue

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
            _, wipe_rc = _ssh(ip, f"truncate -s 0 {path}")
            if wipe_rc == 0:
                print(_ok(f"  ✓ Wiped {name}  ({_fmt_bytes(size_bytes)} freed)"))
            else:
                print(_err(f"  ✗ Failed to wipe {name}"))

    print()
    print(_bold("═" * 64))
