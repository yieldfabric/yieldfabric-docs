"""
CLI interface for YieldFabric.

Two primary subcommands:
  setup    — bootstrap users/groups/tokens/assets from a setup.yaml
             (equivalent to `setup_system.sh`)
  execute  — run a commands.yaml through the command dispatcher
             (equivalent to `execute_commands.sh`)

Plus utility commands: status, validate, version.
"""

import argparse
import os
import sys

from .config import YieldFabricConfig
from .utils.env import load_dotenv
from .core.key_manager import KeyManager
from .core.runner import YieldFabricRunner
from .core.setup_runner import YieldFabricSetupRunner
from .services import AuthService
from .utils.logger import get_logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="YieldFabric Python CLI — replaces setup_system.sh and execute_commands.sh",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  yieldfabric setup ../scripts/setup.yaml                 # full bootstrap
  yieldfabric setup ../scripts/setup.yaml tokens assets   # only tokens then assets
  yieldfabric setup ../scripts/setup.yaml validate        # offline structure check
  yieldfabric setup ../scripts/setup.yaml status          # summary + service health
  yieldfabric execute ../scripts/commands.yaml
  yieldfabric status ../scripts/commands.yaml             # NOTE: status of a commands.yaml
  yieldfabric validate ../scripts/commands.yaml           # NOTE: validates a commands.yaml
  yieldfabric version

Setup phases (run in order; mirror setup_system.sh's commands):
  all (default), users, groups, owners, tokens, assets, fiat, status, validate
  To validate/inspect a setup.yaml use `setup <file> validate|status`
  (the top-level status/validate subcommands operate on a commands.yaml).

Environment Variables (also read from ./.env, or --env-file):
  API_KEY             Backend-service API key (yf_api_…) for non-interactive
                      auth. Preferred over email/password. Exchanged for a
                      JWT via POST /auth/api-key at boot.
  PAY_SERVICE_URL     Payments service URL (default: http://localhost:3002)
  AUTH_SERVICE_URL    Auth service URL    (default: http://localhost:3000)
  AGENTS_SERVICE_URL  Agents service URL  (default: http://localhost:3001) —
                      hosts the deal-flow GraphQL used by deal-lifecycle commands
  COMMAND_DELAY       Delay between commands in seconds (default: 0)
  DEBUG               Enable debug logging (default: false)
        """,
    )
    parser.add_argument(
        "command",
        choices=[
            "setup", "execute", "status", "validate", "version",
            "register-key",
        ],
        help="subcommand to run",
    )
    parser.add_argument(
        "yaml_file",
        nargs="?",
        help="YAML file (setup: setup.yaml, execute/status/validate: commands.yaml); "
             "ignored for register-key and version",
    )
    parser.add_argument(
        "phases",
        nargs="*",
        help="for `setup` only: one or more phases to run IN ORDER — "
             "all, users, groups, owners, tokens, assets, fiat, status, validate "
             "(default: all). e.g. `setup setup.yaml tokens assets`. "
             "Mirrors setup_system.sh's commands. Ignored by other subcommands.",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    parser.add_argument("--pay-service-url", help="override payments service URL")
    parser.add_argument("--auth-service-url", help="override auth service URL")
    parser.add_argument(
        "--agents-service-url",
        help="override agents service URL (deal-flow GraphQL; default :3001)",
    )
    parser.add_argument(
        "--api-key",
        help="backend-service API key (yf_api_…); overrides API_KEY env",
    )
    parser.add_argument(
        "--env-file",
        help="path to a .env file to load (default: ./.env if present)",
    )
    parser.add_argument(
        "--command-delay",
        type=int,
        help="override command delay in seconds (execute only)",
    )

    # register-key-specific options.
    parser.add_argument(
        "--email",
        help="user email for register-key (default: USER_EMAIL or ISSUER_EMAIL env)",
    )
    parser.add_argument(
        "--password",
        help="user password for register-key (default: USER_PASSWORD or ISSUER_PASSWORD env)",
    )
    parser.add_argument(
        "--key-file",
        help="path to private key file (default: ./issuer_external_key.txt). "
             "If the file exists, reuse; if not, generate + register + save.",
    )
    parser.add_argument(
        "--key-name",
        default=os.environ.get("KEY_NAME", "Python CLI external key"),
        help="display name for the key (default: from KEY_NAME env)",
    )
    parser.add_argument(
        "--register-with-wallet",
        action="store_true",
        default=os.environ.get("REGISTER_WITH_WALLET", "").lower() in ("1", "true", "yes"),
        help="also register the key as an owner of the user's default wallet",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip ownership verification (still sign; backend may not require verify)",
    )
    return parser


def _apply_overrides(config: YieldFabricConfig, args: argparse.Namespace):
    if args.debug:
        config.debug = True
    if args.pay_service_url:
        config.pay_service_url = args.pay_service_url
    if args.auth_service_url:
        config.auth_service_url = args.auth_service_url
    if args.agents_service_url:
        config.agents_service_url = args.agents_service_url
    if args.command_delay:
        config.command_delay = args.command_delay
    if args.api_key:
        config.api_key = args.api_key


def main() -> int:
    args = _build_parser().parse_args()

    # Load .env BEFORE reading config from the environment, so API_KEY /
    # PAY_SERVICE_URL / AUTH_SERVICE_URL declared there are picked up by
    # from_env(). An explicit --env-file is required to exist; the
    # implicit ./.env is loaded only if present. Existing process env
    # always wins over the file.
    load_dotenv(args.env_file, override=False)

    config = YieldFabricConfig.from_env()
    _apply_overrides(config, args)

    logger = get_logger(debug=config.debug)

    # ---- version ---------------------------------------------------------
    if args.command == "version":
        from . import __version__

        logger.info(f"YieldFabric Python CLI v{__version__}")
        logger.info(f"Auth service: {config.auth_service_url}")
        logger.info(f"Pay service:  {config.pay_service_url}")
        return 0

    # ---- register-key ----------------------------------------------------
    if args.command == "register-key":
        return _cmd_register_key(args, config, logger)

    # ---- setup -----------------------------------------------------------
    # `setup [file] [phase ...]` mirrors `setup_system.sh [file] [command ...]`:
    #   • the file defaults to ./setup.yaml (or $SETUP_FILE) when omitted;
    #   • a leading phase name that isn't an existing path is treated as a
    #     phase, so `setup tokens assets` works just like the shell;
    #   • zero phases → full setup; multiple phases run in the given order.
    if args.command == "setup":
        file_arg = args.yaml_file
        phases = list(args.phases or [])
        if (
            file_arg
            and YieldFabricSetupRunner.is_known_phase(file_arg)
            and not os.path.exists(file_arg)
        ):
            phases.insert(0, file_arg)
            file_arg = None
        if not file_arg:
            file_arg = os.environ.get("SETUP_FILE") or "setup.yaml"
        if not os.path.exists(file_arg):
            logger.error(f"❌ setup file not found: {file_arg}")
            return 1
        with YieldFabricSetupRunner(config) as runner:
            return 0 if runner.run_phases(file_arg, phases or ["all"]) else 1

    # ---- execute / status / validate (operate on a commands.yaml) --------
    if not args.yaml_file:
        logger.error("❌ yaml_file argument is required")
        return 1
    if not os.path.exists(args.yaml_file):
        logger.error(f"❌ YAML file not found: {args.yaml_file}")
        return 1

    with YieldFabricRunner(config) as runner:
        if args.command == "execute":
            return 0 if runner.execute_file(args.yaml_file) else 1

        if args.command == "status":
            return 0 if runner.show_status(args.yaml_file) else 1

        if args.command == "validate":
            is_valid, errors = runner.yaml_validator.validate(args.yaml_file)
            if is_valid:
                logger.success("✅ YAML file is valid")
                return 0
            logger.error("❌ YAML validation failed:")
            for err in errors:
                logger.error(f"  - {err}")
            return 1

    logger.error(f"❌ unknown command: {args.command}")
    return 1


def _cmd_register_key(args, config, logger) -> int:
    """
    `yieldfabric register-key` — port of loan_management/ensure_issuer_key.py.

    Idempotent:
      - If --key-file exists, load + verify address + resolve key_id.
      - Otherwise generate a new key, register with auth service, and
        persist the private key (0o600) to --key-file.
    """
    email = args.email or os.environ.get("USER_EMAIL") or os.environ.get("ISSUER_EMAIL")
    password = (
        args.password or os.environ.get("USER_PASSWORD") or os.environ.get("ISSUER_PASSWORD")
    )
    if not email or not password:
        logger.error(
            "❌ register-key requires --email/--password or USER_EMAIL/USER_PASSWORD "
            "(or ISSUER_EMAIL/ISSUER_PASSWORD) env"
        )
        return 1

    key_file = (
        args.key_file
        or os.environ.get("ISSUER_EXTERNAL_KEY_FILE")
        or "./issuer_external_key.txt"
    )

    auth = AuthService(config)
    logger.info(f"  🔐 logging in as {email}")
    token = auth.login(email, password)
    if not token:
        logger.error("❌ login failed")
        return 1

    user_id = auth.get_user_id_from_profile(token)
    if not user_id:
        logger.error("❌ could not get user_id from /auth/users/me")
        return 1

    km = KeyManager(auth, token=token, user_id=user_id, debug=config.debug)
    try:
        result = km.ensure_external_key(
            key_file,
            key_name=args.key_name,
            register_with_wallet=args.register_with_wallet,
            verify_ownership=not args.no_verify,
        )
    except Exception as e:
        logger.error(f"❌ register-key failed: {e}")
        return 1

    logger.success(
        f"✅ key {'registered' if result.newly_created else 'reused'}: "
        f"address={result.address} key_id={result.key_id}"
    )
    if result.newly_created:
        logger.warning(f"⚠️  private key saved to {key_file} — keep it secret")
    return 0


if __name__ == "__main__":
    sys.exit(main())
