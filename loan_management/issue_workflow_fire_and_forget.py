#!/usr/bin/env python3

"""
Test script for the workflow-based Issue Composed Contract API endpoint
This script processes loans from a CSV file and creates composed contracts
FIRE-AND-FORGET VERSION: Sends all requests without waiting for workflow completion
Adapted to process top 10 loans from wisr_loans_20250831.csv
"""

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("❌ Error: 'requests' library is required. Install it with: pip install requests")
    sys.exit(1)

# ANSI color codes
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
PURPLE = '\033[0;35m'
CYAN = '\033[0;36m'
NC = '\033[0m'  # No Color


def echo_with_color(color: str, message: str, file=sys.stdout):
    """Print a colored message"""
    print(f"{color}{message}{NC}", file=file)


def load_env_files(script_dir: Path, repo_root: Path):
    """Load environment variables from .env files"""
    env_files = [
        repo_root / ".env",
        repo_root / ".env.local",
        script_dir / ".env"
    ]
    
    for env_file in env_files:
        if env_file.exists():
            try:
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            # Remove quotes if present
                            value = value.strip('"\'')
                            os.environ[key.strip()] = value
            except Exception as e:
                echo_with_color(YELLOW, f"  ⚠️  Warning: Could not load {env_file}: {e}")


def check_service_running(service_name: str, service_url: str) -> bool:
    """Check if a service is running and reachable"""
    echo_with_color(BLUE, f"  🔍 Checking if {service_name} is running...")
    
    try:
        if service_url.startswith(('http://', 'https://')):
            # Try health endpoint first, then base URL
            try:
                response = requests.get(f"{service_url}/health", timeout=5)
                if response.status_code < 500:
                    echo_with_color(GREEN, f"    ✅ {service_name} is reachable")
                    return True
            except:
                pass
            
            try:
                response = requests.get(service_url, timeout=5)
                if response.status_code < 500:
                    echo_with_color(GREEN, f"    ✅ {service_name} is reachable")
                    return True
            except:
                pass
            
            echo_with_color(RED, f"    ❌ {service_name} is not reachable at {service_url}")
            return False
        else:
            # Assume it's a port number
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', int(service_url)))
            sock.close()
            
            if result == 0:
                echo_with_color(GREEN, f"    ✅ {service_name} is running on port {service_url}")
                return True
            else:
                echo_with_color(RED, f"    ❌ {service_name} is not running on port {service_url}")
                return False
    except Exception as e:
        echo_with_color(RED, f"    ❌ Error checking {service_name}: {e}")
        return False


def login_user(auth_service_url: str, email: str, password: str) -> Optional[str]:
    """Login user and return JWT token"""
    echo_with_color(BLUE, f"  🔐 Logging in user: {email}", file=sys.stderr)
    
    services_json = ["vault", "payments"]
    payload = {
        "email": email,
        "password": password,
        "services": services_json
    }
    
    try:
        response = requests.post(
            f"{auth_service_url}/auth/login/with-services",
            json=payload,
            timeout=30
        )
        
        echo_with_color(BLUE, "    📡 Login response received", file=sys.stderr)
        
        if response.status_code == 200:
            data = response.json()
            token = data.get('token') or data.get('access_token') or data.get('jwt')
            
            if token and token != "null":
                echo_with_color(GREEN, "    ✅ Login successful", file=sys.stderr)
                return token
            else:
                echo_with_color(RED, "    ❌ No token in response", file=sys.stderr)
                echo_with_color(YELLOW, f"    Response: {response.text}", file=sys.stderr)
                return None
        else:
            echo_with_color(RED, f"    ❌ Login failed: HTTP {response.status_code}", file=sys.stderr)
            echo_with_color(YELLOW, f"    Response: {response.text}", file=sys.stderr)
            return None
    except Exception as e:
        echo_with_color(RED, f"    ❌ Login failed: {e}", file=sys.stderr)
        return None


def issue_composed_contract_workflow(
    pay_service_url: str,
    jwt_token: str,
    name: str,
    description: str,
    obligations_json: list
) -> dict:
    """Issue a composed contract workflow (fire-and-forget - no polling)"""
    request_body = {
        "name": name,
        "description": description,
        "obligations": obligations_json
    }
    
    try:
        response = requests.post(
            f"{pay_service_url}/api/composed_contract/issue_workflow",
            json=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}"
            },
            timeout=30
        )
        
        if not response.text:
            return {"error": "Empty response body", "status_code": response.status_code}
        
        try:
            return response.json()
        except:
            return {"error": response.text, "status_code": response.status_code}
    except Exception as e:
        return {"error": str(e)}


def convert_currency_to_wei(currency_str: str) -> str:
    """Convert currency string to wei-like format (18 decimals)
    Input: "$31,817.59" -> Output: "31817590000000000000000"
    """
    # Remove $ and commas
    cleaned = re.sub(r'[\$,]', '', currency_str)
    # Convert to float, multiply by 10^18, convert to int, then string
    amount = float(cleaned)
    wei_amount = int(amount * 10**18)
    return str(wei_amount)


def convert_date_to_iso(date_str: str) -> str:
    """Convert date from M/D/YY format to ISO format
    Input: "2/12/32" -> Output: "2032-02-12T23:59:59Z"
    Assumes 2-digit years are in 2000-2099 range for loan maturity dates
    """
    parts = date_str.split('/')
    if len(parts) != 3:
        raise ValueError(f"Invalid date format: {date_str}")
    
    month, day, year = parts
    
    # Convert 2-digit year to 4-digit
    year_int = int(year)
    if len(year) == 1:
        year = f"200{year_int}"
    elif len(year) == 2:
        year = f"20{year_int}"
    
    # Format with leading zeros
    month = f"{int(month):02d}"
    day = f"{int(day):02d}"
    
    return f"{year}-{month}-{day}T23:59:59Z"


def safe_get(row: list, index: int, default: str = "") -> str:
    """Safely get a value from a CSV row, stripping quotes"""
    if index < len(row):
        return row[index].strip('"')
    return default


def extract_loan_data(row: list) -> dict:
    """Extract all loan data from CSV row into a dictionary
    CSV column indices based on header:
    0: Loan ID, 1: Initial Amount, 2: Rate, 3: Settlement, 4: Maturity, 5: Term, 6: # PMT left,
    7: Prin. Out, 8: Accrued, 9: Fee, 10: Unpaid Int, 11: Current Value, 12: Arrears, 13: Arrears Bal,
    14: # days late, 15: State, 16: Secured, 17: SecurityType, 18: VedaCreditScore,
    19: IncomeAmount, 20: MortgageAmount, 21: MortgageFrequency, 22: RentAmount, 23: RentFrequency,
    24: OtherLoanAmount, 25: OtherLoanFrequency, 26: TotalAssets, 27: TotalLiabilities,
    28: EmploymentMonths, 29: EmploymentStatus, 30: PreviousEmploymentMonths,
    31: CurrentAddressState, 32: CurrentAddressPostcode, 33: ResidencyMonths, 34: ResidencyStatus,
    35: MaritalStatus, 36: Age, 37: LoanPurpose, 38: IsJointApplication, 39: Credit Sense Supplied,
    40: BrokerId, 41: AddedDateLocal, 42: ApprovedDateLocal, 43: Occupation, 44: Date Of Birth,
    45: Net Surplus Ratio, 46: Surplus, 47: Loan Amount Requested, 48: Term Requested,
    49: Rate Discount, 50: Assignment Date, 51: Next Pay Date, 52: Payment Frequency,
    53: PMT, 54: Referrer/Broker, 55: Asset Code, 56: Vehicle Category, 57: Residual,
    58: Vehicle Age (years), 59: Manufacturer, 60: LVR, 61: Hardship, 62: Extension Receivable,
    63: Remaining loan term, 64: Updated Maturity Date, 65: Total Term
    """
    data = {
        # Basic loan information (required fields)
        "loanId": safe_get(row, 0),
        "initialAmount": safe_get(row, 1),
        "rate": safe_get(row, 2),
        "settlement": safe_get(row, 3),
        "maturity": safe_get(row, 4),
        "term": safe_get(row, 5),
        "pmtLeft": safe_get(row, 6),
        "principalOutstanding": safe_get(row, 7),
        "accrued": safe_get(row, 8),
        "fee": safe_get(row, 9),
        "unpaidInt": safe_get(row, 10),
        "currentValue": safe_get(row, 11),
        "arrears": safe_get(row, 12),
        "arrearsBal": safe_get(row, 13),
        "daysLate": safe_get(row, 14),
        
        # Location and address data
        "state": safe_get(row, 15),
        "currentAddressState": safe_get(row, 31),
        "currentAddressPostcode": safe_get(row, 32),
        "residencyMonths": safe_get(row, 33),
        "residencyStatus": safe_get(row, 34),
        
        # Credit information
        "vedaCreditScore": safe_get(row, 18),
        "incomeAmount": safe_get(row, 19),
        "mortgageAmount": safe_get(row, 20),
        "mortgageFrequency": safe_get(row, 21),
        "rentAmount": safe_get(row, 22),
        "rentFrequency": safe_get(row, 23),
        "otherLoanAmount": safe_get(row, 24),
        "otherLoanFrequency": safe_get(row, 25),
        "totalAssets": safe_get(row, 26),
        "totalLiabilities": safe_get(row, 27),
        "employmentMonths": safe_get(row, 28),
        "employmentStatus": safe_get(row, 29),
        "previousEmploymentMonths": safe_get(row, 30),
        "maritalStatus": safe_get(row, 35),
        "age": safe_get(row, 36),
        "loanPurpose": safe_get(row, 37),
        "isJointApplication": safe_get(row, 38),
        "creditSenseSupplied": safe_get(row, 39),
        
        # Additional loan details
        "secured": safe_get(row, 16),
        "securityType": safe_get(row, 17),
        "brokerId": safe_get(row, 40),
        "addedDateLocal": safe_get(row, 41),
        "approvedDateLocal": safe_get(row, 42),
        "occupation": safe_get(row, 43),
        "dateOfBirth": safe_get(row, 44),
        "netSurplusRatio": safe_get(row, 45),
        "surplus": safe_get(row, 46),
        "loanAmountRequested": safe_get(row, 47),
        "termRequested": safe_get(row, 48),
        "rateDiscount": safe_get(row, 49),
        "assignmentDate": safe_get(row, 50),
        "nextPayDate": safe_get(row, 51),
        "paymentFrequency": safe_get(row, 52),
        "pmt": safe_get(row, 53),
        "referrerBroker": safe_get(row, 54),
        "assetCode": safe_get(row, 55),
        "vehicleCategory": safe_get(row, 56),
        "residual": safe_get(row, 57),
        "vehicleAge": safe_get(row, 58),
        "manufacturer": safe_get(row, 59),
        "lvr": safe_get(row, 60),
        "hardship": safe_get(row, 61),
        "extensionReceivable": safe_get(row, 62),
        "remainingLoanTerm": safe_get(row, 63),
        "updatedMaturityDate": safe_get(row, 64),
        "totalTerm": safe_get(row, 65),
    }
    
    # Remove empty values to keep JSON clean
    return {k: v for k, v in data.items() if v}


def main():
    """Main function"""
    # Get script directory
    script_dir = Path(__file__).parent.resolve()
    repo_root = script_dir.parent.parent
    
    # Load environment variables from .env files
    load_env_files(script_dir, repo_root)
    
    # Show usage if help is requested
    if len(sys.argv) > 1 and sys.argv[1] in ('-h', '--help'):
        print("Usage: issue_workflow_fire_and_forget.py [username] [password] [csv_file]")
        print("   or: issue_workflow_fire_and_forget.py [csv_file]")
        print()
        print("Arguments:")
        print("  username    User email for authentication (default: issuer@yieldfabric.com)")
        print("  password    User password for authentication (default: issuer_password)")
        print("  csv_file    Path to CSV file with loan data (default: wisr_loans_20250831.csv)")
        print()
        print("Note: If the first argument is a CSV file (ends with .csv or exists as a file),")
        print("      it will be treated as the CSV file path, and username/password will use")
        print("      environment variables or defaults.")
        print()
        print("Environment variables (used as fallback if arguments not provided):")
        print("  USER_EMAIL         User email for authentication")
        print("  PASSWORD           User password for authentication")
        print("  PAY_SERVICE_URL    Payments service URL (default: https://pay.test.yieldfabric.com)")
        print("  AUTH_SERVICE_URL   Auth service URL (default: https://auth.yieldfabric.com)")
        print("  DENOMINATION      Token denomination (default: aud-token-asset)")
        print("  COUNTERPART       Counterparty email (default: issuer@yieldfabric.com)")
        print()
        print("Description:")
        print("  FIRE-AND-FORGET VERSION: Processes the top 10 loans from the CSV file and")
        print("  sends creation requests for composed contracts WITHOUT waiting for workflow")
        print("  completion. This is faster for bulk operations but doesn't verify completion.")
        print()
        print("Examples:")
        print("  python3 issue_workflow_fire_and_forget.py")
        print("  python3 issue_workflow_fire_and_forget.py wisr_loans_20250831.csv")
        print("  python3 issue_workflow_fire_and_forget.py user@example.com mypassword")
        print("  python3 issue_workflow_fire_and_forget.py user@example.com mypassword /path/to/loans.csv")
        print("  USER_EMAIL=user@example.com PASSWORD=mypassword python3 issue_workflow_fire_and_forget.py")
        return 0
    
    # Parse command-line arguments - match bash script behavior
    # Usage: ./issue_workflow_fire_and_forget.py [username] [password] [csv_file]
    # Or: ./issue_workflow_fire_and_forget.py [csv_file]
    
    args = sys.argv[1:]
    
    # Store environment variables before we potentially overwrite them
    env_user_email = os.environ.get('USER_EMAIL', '')
    env_password = os.environ.get('PASSWORD', '')
    
    # Smart argument detection: if first arg looks like a CSV file, treat it as such
    csv_file = None
    user_email = None
    password = None
    
    if len(args) >= 1:
        first_arg = args[0]
        csv_path = Path(first_arg)
        
        # Check if first argument is a CSV file (ends with .csv or exists as file)
        if first_arg.endswith('.csv') or csv_path.exists():
            csv_file = first_arg
        elif '@' in first_arg:
            # Looks like an email address
            user_email = first_arg
            if len(args) >= 2:
                password = args[1]
                if len(args) >= 3:
                    csv_file = args[2]
        else:
            # Assume it's a username even if it doesn't look like an email
            user_email = first_arg
            if len(args) >= 2:
                password = args[1]
                if len(args) >= 3:
                    csv_file = args[2]
    
    # Set defaults if not provided (use environment variables, then hardcoded defaults)
    if not user_email:
        if env_user_email:
            user_email = env_user_email
        else:
            user_email = 'issuer@yieldfabric.com'
    
    if not password:
        if env_password:
            password = env_password
        else:
            password = 'issuer_password'
    
    # CSV file path - use LOANS_CSV from env, else default
    if not csv_file:
        csv_file = os.environ.get("LOANS_CSV", "").strip() or str(
            script_dir / "wisr_loans_20250831.csv"
        )
    
    # Resolve relative paths
    csv_path = Path(csv_file)
    if not csv_path.is_absolute():
        # Try script directory first, then current directory
        if (script_dir / csv_path).exists():
            csv_file = str(script_dir / csv_path)
        elif csv_path.exists():
            csv_file = str(csv_path.resolve())
    
    if not Path(csv_file).exists():
        echo_with_color(RED, f"❌ CSV file not found: {csv_file}")
        return 1
    
    # Configuration
    pay_service_url = os.environ.get('PAY_SERVICE_URL', 'https://pay.test.yieldfabric.com')
    auth_service_url = os.environ.get('AUTH_SERVICE_URL', 'https://auth.yieldfabric.com')
    denomination = os.environ.get('DENOMINATION', 'aud-token-asset')
    counterpart = os.environ.get('COUNTERPART', 'issuer@yieldfabric.com')
    
    echo_with_color(CYAN, "🚀 Starting Issue Composed Contract WorkFlow API Test - FIRE-AND-FORGET MODE")
    echo_with_color(YELLOW, "⚠️  This script sends requests without waiting for workflow completion")
    print()
    
    echo_with_color(BLUE, "📋 Configuration:")
    echo_with_color(BLUE, f"  API Base URL: {pay_service_url}")
    echo_with_color(BLUE, f"  Auth Service: {auth_service_url}")
    echo_with_color(BLUE, f"  User (Initiator): {user_email}")
    echo_with_color(BLUE, f"  Counterparty: {counterpart}")
    echo_with_color(BLUE, f"  Denomination: {denomination}")
    echo_with_color(BLUE, f"  CSV File: {csv_file}")
    print()
    
    # Check services
    if not check_service_running("Auth Service", auth_service_url):
        echo_with_color(RED, f"❌ Auth service is not reachable at {auth_service_url}")
        return 1
    
    if not check_service_running("Payments Service", pay_service_url):
        echo_with_color(RED, f"❌ Payments service is not reachable at {pay_service_url}")
        echo_with_color(YELLOW, "Please start the payments service:")
        print("   Local: cd ../yieldfabric-payments && cargo run")
        echo_with_color(BLUE, f"   REST API endpoint will be available at: {pay_service_url}/api/composed_contract/issue_workflow")
        return 1
    
    # Check if the endpoint exists (basic check)
    try:
        response = requests.post(
            f"{pay_service_url}/api/composed_contract/issue_workflow",
            json={},
            timeout=5
        )
        if response.status_code == 404:
            echo_with_color(YELLOW, "⚠️  Warning: Endpoint returned 404. The server may need to be restarted to pick up the new routes.")
            echo_with_color(YELLOW, "   Make sure the server was built with the latest code including composed_contract_issue workflow.")
            print()
    except:
        pass  # Ignore errors in endpoint check
    
    print()
    
    # Authenticate
    echo_with_color(CYAN, "🔐 Authenticating...")
    jwt_token = login_user(auth_service_url, user_email, password)
    if not jwt_token:
        echo_with_color(RED, f"❌ Failed to get JWT token for user: {user_email}")
        return 1
    
    echo_with_color(GREEN, f"  ✅ JWT token obtained (first 50 chars): {jwt_token[:50]}...")
    print()
    
    # Read CSV and process top 10 loans
    echo_with_color(CYAN, "📖 Reading loans from CSV file...")
    echo_with_color(YELLOW, "⚡ FIRE-AND-FORGET MODE: Sending requests without waiting for completion")
    print()
    
    loan_count = 0
    success_count = 0
    fail_count = 0
    workflow_ids = []  # Store workflow IDs for reference
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            # Skip header
            next(reader, None)
            
            for row in reader:
                if loan_count >= 10:
                    break
                
                loan_count += 1
                
                # Parse loan data
                if len(row) < 8:
                    echo_with_color(YELLOW, f"  ⚠️  Skipping loan {loan_count}: insufficient columns")
                    fail_count += 1
                    continue
                
                # Extract basic required fields
                loan_id = safe_get(row, 0)
                prin_out = safe_get(row, 7)
                maturity = safe_get(row, 4)
                
                if not loan_id or not prin_out or not maturity:
                    echo_with_color(YELLOW, f"  ⚠️  Skipping loan {loan_count}: missing required data")
                    fail_count += 1
                    continue
                
                # Extract all loan data for the data field
                loan_data = extract_loan_data(row)
                
                echo_with_color(CYAN, f"📦 Processing Loan {loan_count}/10: ID={loan_id}")
                
                # Convert currency to wei format
                try:
                    amount_wei = convert_currency_to_wei(prin_out)
                except Exception as e:
                    echo_with_color(RED, f"  ❌ Error converting currency: {e}")
                    fail_count += 1
                    continue
                
                # Convert date to ISO format
                try:
                    maturity_iso = convert_date_to_iso(maturity)
                except Exception as e:
                    echo_with_color(RED, f"  ❌ Error converting date: {e}")
                    fail_count += 1
                    continue
                
                echo_with_color(BLUE, f"  Loan ID: {loan_id}, Amount: {prin_out}, Maturity: {maturity}")
                
                # Build comprehensive data object with all loan information
                obligation_data = {
                    "name": f"Loan {loan_id}",
                    "description": f"Loan obligation for loan ID {loan_id}",
                    **loan_data  # Include all extracted loan data
                }
                
                # Build single obligation JSON for this loan
                obligation = {
                    "counterpart": counterpart,
                    "denomination": denomination,
                    "obligor": user_email,
                    "notional": amount_wei,
                    "expiry": maturity_iso,
                    "data": obligation_data,
                    "initialPayments": {
                        "amount": amount_wei,
                        "denomination": denomination,
                        "payments": [{
                            "oracleAddress": None,
                            "oracleOwner": None,
                            "oracleKeySender": None,
                            "oracleValueSenderSecret": None,
                            "oracleKeyRecipient": None,
                            "oracleValueRecipientSecret": None,
                            "unlockSender": maturity_iso,
                            "unlockReceiver": maturity_iso,
                            "linearVesting": None
                        }]
                    }
                }
                
                obligations_array = [obligation]
                contract_name = f"Loan Contract {loan_id}"
                contract_description = f"Composed contract for loan ID {loan_id}"
                
                # Send request without waiting
                start_response = issue_composed_contract_workflow(
                    pay_service_url,
                    jwt_token,
                    contract_name,
                    contract_description,
                    obligations_array
                )
                
                workflow_id = start_response.get('workflow_id') if isinstance(start_response, dict) else None
                
                if not workflow_id or workflow_id == "null":
                    echo_with_color(RED, f"  ❌ Failed to start workflow for loan {loan_id}")
                    if isinstance(start_response, dict):
                        error_msg = start_response.get('error', 'Unknown error')
                        echo_with_color(RED, f"    Error: {error_msg}")
                    fail_count += 1
                    continue
                
                echo_with_color(GREEN, f"  ✅ Workflow submitted with ID: {workflow_id}")
                workflow_ids.append({"loan_id": loan_id, "workflow_id": workflow_id})
                success_count += 1
                print()
                
    except Exception as e:
        echo_with_color(RED, f"❌ Error reading CSV file: {e}")
        return 1
    
    print()
    echo_with_color(PURPLE, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    echo_with_color(CYAN, "📊 Summary")
    echo_with_color(PURPLE, "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    echo_with_color(BLUE, f"  Total loans processed: {loan_count}")
    echo_with_color(GREEN, f"  Successfully submitted: {success_count}")
    echo_with_color(RED, f"  Failed: {fail_count}")
    print()
    
    if workflow_ids:
        echo_with_color(CYAN, "📋 Workflow IDs (for reference):")
        for item in workflow_ids:
            echo_with_color(BLUE, f"    Loan {item['loan_id']}: Workflow ID {item['workflow_id']}")
        print()
    
    if success_count > 0:
        echo_with_color(GREEN, f"🎉 Successfully submitted {success_count} workflow request(s)! ✨")
        echo_with_color(YELLOW, "⚠️  Note: Workflows are processing in the background. Use the workflow status")
        echo_with_color(YELLOW, "   endpoint to check completion: GET /api/workflows/{workflow_id}")
        return 0
    else:
        echo_with_color(RED, "❌ No workflows were submitted successfully")
        return 1


if __name__ == "__main__":
    sys.exit(main())
