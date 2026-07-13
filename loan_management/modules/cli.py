"""CLI: help text and argument parsing for the issue workflow script."""

import os
import sys
from pathlib import Path

from .config import (
    ACTION_ISSUE_ONLY,
    VALID_ACTION_MODES,
)


def print_usage() -> None:
    """Print help text for the script."""
    print("Usage: issue_workflow.py [username] [password] [csv_file] [action_mode]")
    print("   or: issue_workflow.py [csv_file]")
    print()
    print("Arguments:")
    print("  username     User email for authentication (default: issuer@yieldfabric.com)")
    print("  password     User password for authentication (default: issuer_password)")
    print("  csv_file     Path to CSV file with loan data (default: wisr_loans_20250831.csv)")
    print("  action_mode  One of: issue_only | issue_swap | issue_swap_complete (default: issue_only)")
    print("                issue_only           - Create composed contract with obligations only")
    print("                issue_swap           - Create contract then create swap with SWAP_COUNTERPARTY")
    print("                issue_swap_complete  - Same as issue_swap then acceptor completes each swap (requires ACCEPTOR_EMAIL/PASSWORD)")
    print()
    print("Note: If the first argument is a CSV file (ends with .csv or exists as a file),")
    print("      it will be treated as the CSV file path, and username/password will use")
    print("      environment variables or defaults.")
    print()
    print("Environment variables (used as fallback if arguments not provided):")
    print("  ISSUER_EMAIL        Issuer email for authentication (alias: USER_EMAIL)")
    print("  ISSUER_PASSWORD     Issuer password for authentication (alias: PASSWORD)")
    print("  PAY_SERVICE_URL     Payments service URL (default: https://pay.test.yieldfabric.com)")
    print("  AUTH_SERVICE_URL    Auth service URL (default: https://auth.yieldfabric.com)")
    print("  DENOMINATION        Token denomination (default: aud-token-asset)")
    print("  COUNTERPART         Obligation counterparty email (default: issuer@yieldfabric.com)")
    print("  LOANS_CSV           Path to loans CSV file (default: wisr_loans_20250831.csv)")
    print("  LOAN_COUNT          Max number of loans to process from CSV (default: 10)")
    print("  ACTION_MODE         issue_only | issue_swap | issue_swap_complete (default: issue_only)")
    print("  SWAP_COUNTERPARTY   Swap counterparty when action_mode=issue_swap (default: originator@yieldfabric.com)")
    print("  PAYMENT_AMOUNT      Expected payment from swap counterparty (default: obligation notional)")
    print("  PAYMENT_DENOMINATION Payment denomination for swap (default: DENOMINATION)")
    print("  DEADLINE            Swap deadline ISO date (default: obligation maturity)")
    print("  ACCEPTOR_EMAIL      If set with issue_swap: user that accepts/completes the swap (counterparty)")
    print("  ACCEPTOR_PASSWORD   Password for ACCEPTOR_EMAIL")
    print("  DEPLOY_ISSUER_ACCOUNT   If set (true/1/yes): deploy issuer's on-chain wallet. With issue_swap_complete, defaults to true unless set to false.")
    print("  DEPLOY_ACCEPTOR_ACCOUNT If set (true/1/yes): deploy acceptor's on-chain wallet. With issue_swap_complete, defaults to true unless set to false.")
    print("  DEPLOY_ACCOUNT_PER_LOAN If set (true/1/yes): deploy one new wallet per loan under the issuer entity. Defaults to true for issue_swap / issue_swap_complete.")
    print("  MINT_BEFORE_LOANS      If set (true/1/yes): mint loan amount as ACCEPTOR_EMAIL (investor) per loan. Requires ACCEPTOR_EMAIL, ACCEPTOR_PASSWORD, POLICY_SECRET (issue_swap flows only).")
    print("  BURN_AFTER_LOANS       If set (true/1/yes) with POLICY_SECRET and BURN_AMOUNT: burn tokens after processing loans.")
    print("  BURN_AMOUNT            Amount to burn when BURN_AFTER_LOANS=true (e.g. 5).")
    print("  POLICY_SECRET          Policy secret for mint/burn (required for MINT_BEFORE_LOANS or BURN_AFTER_LOANS).")
    print("  WORKFLOW_POLL_TIMEOUT_SEC   Max seconds to poll workflow status (default: 120). Event-driven: stops when completed/failed.")
    print("  WORKFLOW_POLL_INTERVAL_SEC  Seconds between workflow status polls (default: 1).")
    print("  SWAP_POLL_TIMEOUT_SEC       Max seconds to poll swap completion (default: 120).")
    print("  SWAP_POLL_INTERVAL_SEC      Seconds between swap status polls (default: 2).")
    print()
    print("Description:")
    print("  Processes up to LOAN_COUNT loans from the CSV file (default 10) and creates a composed contract")
    print("  for each loan with a single obligation containing:")
    print("    - Loan ID as contract identifier")
    print("    - Principal Outstanding as payment amount")
    print("    - Maturity date as payment due date")
    print("    - Issuer as obligor")
    print("  With action_mode=issue_swap, also creates a swap with SWAP_COUNTERPARTY (e.g. originator).")
    print("  If ACCEPTOR_EMAIL is set with issue_swap, that user will accept/complete each swap.")
    print("  With action_mode=issue_swap_complete, each swap is created and then accepted (ACCEPTOR_EMAIL/PASSWORD required).")
    print("  With DEPLOY_ISSUER_ACCOUNT=true, the issuer's on-chain wallet is deployed via auth service before running workflows.")
    print("  With DEPLOY_ACCEPTOR_ACCOUNT=true, the acceptor's (counterparty) wallet is deployed so completeSwap can succeed.")
    print("  With DEPLOY_ACCOUNT_PER_LOAN=true, one new wallet is deployed under the issuer entity before each loan (issuer gets multiple wallets, one per loan).")
    print()
    print("Examples:")
    print("  python3 issue_workflow.py")
    print("  python3 issue_workflow.py wisr_loans_20250831.csv")
    print("  python3 issue_workflow.py user@example.com mypassword")
    print("  python3 issue_workflow.py user@example.com mypassword /path/to/loans.csv issue_swap")
    print("  ACTION_MODE=issue_swap SWAP_COUNTERPARTY=originator@yieldfabric.com python3 issue_workflow.py")
    print("  ACTION_MODE=issue_swap ACCEPTOR_EMAIL=originator@yieldfabric.com ACCEPTOR_PASSWORD=secret python3 issue_workflow.py")
    print("  ACTION_MODE=issue_swap_complete ACCEPTOR_EMAIL=originator@yieldfabric.com ACCEPTOR_PASSWORD=secret python3 issue_workflow.py")
    print("  ISSUER_EMAIL=issuer@yieldfabric.com ISSUER_PASSWORD=secret python3 issue_workflow.py")
    print("  DEPLOY_ISSUER_ACCOUNT=true python3 issue_workflow.py   # deploy issuer wallet first")
    print("  DEPLOY_ACCEPTOR_ACCOUNT=true python3 issue_workflow.py   # deploy acceptor (investor) wallet for completeSwap")
    print("  DEPLOY_ACCOUNT_PER_LOAN=false python3 issue_workflow.py   # disable one wallet per loan under issuer (default: on for issue_swap)")
    print("  MINT_BEFORE_LOANS=true ACCEPTOR_EMAIL=... ACCEPTOR_PASSWORD=... POLICY_SECRET=xxx python3 issue_workflow.py   # mint as investor per loan")
    print("  BURN_AFTER_LOANS=true BURN_AMOUNT=5 POLICY_SECRET=xxx python3 issue_workflow.py   # burn after processing")


def parse_cli_args(script_dir: Path) -> tuple:
    """Parse argv and env into (user_email, password, csv_file, action_mode)."""
    args = sys.argv[1:]
    env_user_email = (
        os.environ.get("ISSUER_EMAIL", "").strip() or os.environ.get("USER_EMAIL", "").strip()
    )
    env_password = (
        os.environ.get("ISSUER_PASSWORD", "").strip() or os.environ.get("PASSWORD", "").strip()
    )
    env_action_mode = os.environ.get("ACTION_MODE", "").strip().lower() or ACTION_ISSUE_ONLY

    csv_file = None
    user_email = None
    password = None
    action_mode = None

    if len(args) >= 1:
        first_arg = args[0]
        csv_path = Path(first_arg)
        if first_arg.endswith(".csv") or csv_path.exists():
            csv_file = first_arg
            if len(args) >= 2:
                action_mode = args[1].strip().lower()
        elif "@" in first_arg:
            user_email = first_arg
            if len(args) >= 2:
                password = args[1]
            if len(args) >= 3:
                csv_file = args[2]
            if len(args) >= 4:
                action_mode = args[3].strip().lower()
        else:
            user_email = first_arg
            if len(args) >= 2:
                password = args[1]
            if len(args) >= 3:
                csv_file = args[2]
            if len(args) >= 4:
                action_mode = args[3].strip().lower()

    user_email = user_email or env_user_email or "none"
    password = password or env_password or "none"
    if not action_mode or action_mode not in VALID_ACTION_MODES:
        action_mode = env_action_mode if env_action_mode in VALID_ACTION_MODES else ACTION_ISSUE_ONLY
    if not csv_file:
        csv_file = (
            os.environ.get("LOANS_CSV", "").strip()
            or str(script_dir / "wisr_loans_20250831.csv")
        )
    csv_path = Path(csv_file)
    if not csv_path.is_absolute():
        if (script_dir / csv_path).exists():
            csv_file = str(script_dir / csv_path)
        elif csv_path.exists():
            csv_file = str(csv_path.resolve())
    return (user_email, password, csv_file, action_mode)
