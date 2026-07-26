# YieldFabric Python Port v2.0 - Refactored Architecture

A completely refactored Python implementation of YieldFabric GraphQL command execution with clean architecture, separation of concerns, and enterprise-grade design patterns.

## 🎯 What's New in v2.0

### Architecture Improvements
- **Clean Architecture**: Separation of concerns with distinct layers (models, services, executors, core, utils)
- **Service Clients**: Dedicated HTTP client abstraction for Auth and Payments services
- **Executor Pattern**: Specialized executors for different operation types
- **Configuration Management**: Centralized configuration with environment variable support
- **Enhanced Logging**: Structured, colored logging with debug mode
- **Type Safety**: Comprehensive data models with validation
- **Context Managers**: Proper resource management with context manager support

### Code Organization

```
yieldfabric/
├── __init__.py              # Package initialization
├── config.py                # Configuration management
├── cli.py                   # CLI interface
│
├── core/                    # Core business logic
│   ├── output_store.py      # Variable substitution
│   ├── yaml_parser.py       # YAML parsing
│   └── runner.py            # Main orchestrator
│
├── services/                # Service clients
│   ├── base.py              # Base HTTP client
│   ├── auth_service.py      # Auth service client
│   └── payments_service.py  # Payments service client
│
├── executors/               # Command executors
│   ├── base.py              # Base executor
│   ├── payment_executor.py  # Payment operations
│   ├── obligation_executor.py # Obligation operations
│   ├── query_executor.py    # Query operations
│   ├── swap_executor.py     # Swap operations
│   └── treasury_executor.py # Treasury operations
│
├── models/                  # Data models
│   ├── command.py           # Command models
│   ├── user.py              # User models
│   └── response.py          # Response models
│
├── validation/              # Validators
│   ├── yaml_validator.py    # YAML validation
│   ├── service_validator.py # Service health checks
│   └── command_validator.py # Command validation
│
└── utils/                   # Utilities
    ├── logger.py            # Logging utilities
    ├── graphql.py           # GraphQL helpers
    └── shell.py             # Shell command utilities
```

## 🚀 Quick Start

### Installation

```bash
cd yieldfabric-docs/python
pip install -e .
```

### Deploy assets from a setup.yaml (port of `setup_system.sh`)

The `setup` subcommand bootstraps users, groups (+ on-chain account
deploy and owners), tokens, assets, and fiat accounts from a `setup.yaml`
— the same file shape `scripts/setup_system.sh` uses, and a one-for-one
port of its commands.

Like the shell, you can run individual **phases** (and several in order)
instead of the whole bootstrap — append phase names after the file:

```bash
yieldfabric setup setup.yaml                 # full bootstrap (= `all`)
yieldfabric setup setup.yaml tokens assets   # only tokens, then assets
yieldfabric setup setup.yaml validate        # offline structure check
yieldfabric setup setup.yaml status          # summary + service health
```

Phases (run in the given order) mirror `setup_system.sh`'s commands:
`all` (default), `users`, `groups`, `owners`, `tokens`, `assets`,
`fiat`, `status`, `validate`. The file defaults to `./setup.yaml` (or
`$SETUP_FILE`) when omitted, so `yieldfabric setup tokens assets` works
too. `validate` is fully offline; `status` is read-only.

> Note: the top-level `yieldfabric status` / `yieldfabric validate`
> subcommands operate on a **commands.yaml** (the `execute` flow). To
> inspect a **setup.yaml**, use `setup <file> status|validate`.

Provide service URLs and an API key via a `.env` file (auto-loaded from
the current directory). Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
# edit .env → AUTH_SERVICE_URL, PAY_SERVICE_URL, API_KEY

yieldfabric setup ./setup.yaml
```

`.env`:

```bash
AUTH_SERVICE_URL=https://auth.yieldfabric.io
PAY_SERVICE_URL=https://pay.yieldfabric.io
API_KEY=yf_api_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

The CLI exchanges `API_KEY` for a short-lived JWT at boot via
`POST /auth/api-key`, then creates everything in `setup.yaml` under that
identity. The key owner needs `SuperAdmin`/`Admin` so the
create-token/asset/fiat mutations are permitted. Issue a key once with a
one-time user JWT:

Setup retains the returned refresh-token bundle and rotates the same
principal's access JWT when it is expired or within five seconds of expiry.
This keeps long user/group provisioning runs compatible with short access
token TTLs. Principal and chain must remain unchanged across refresh, and an
activation request that returns `401`/`403` is refreshed and retried at most
once instead of being polled repeatedly.

```bash
curl -X POST "$AUTH_SERVICE_URL/auth/api-key/generate" \
     -H "Authorization: Bearer <one-time user JWT>" \
     -H "Content-Type: application/json" \
     -d '{"service_name":"asset-setup","description":"setup CLI"}'
# → {"api_key":"yf_api_…", ...}  ← store as API_KEY
```

Everything can also be passed as flags (flags > env/.env):

```bash
yieldfabric --auth-service-url https://auth.yieldfabric.io \
            --pay-service-url https://pay.yieldfabric.io \
            --api-key yf_api_… \
            --env-file ./prod.env \
            setup ./setup.yaml
```

If `API_KEY` is unset, `setup` falls back to logging in the **first user**
declared in `setup.yaml` (conventionally a `SuperAdmin`) with
email/password — the original `setup_system.sh` behaviour.

### Usage

```bash
# Bootstrap a system (users/groups/tokens/assets/fiat) from setup.yaml
yieldfabric setup setup.yaml

# Run individual phases, in order (mirrors setup_system.sh commands)
yieldfabric setup setup.yaml tokens assets
yieldfabric setup setup.yaml validate   # offline structural check
yieldfabric setup setup.yaml status      # summary + service health

# Execute commands
yieldfabric execute commands.yaml

# Check status
yieldfabric status commands.yaml

# Validate YAML
yieldfabric validate commands.yaml

# Show version
yieldfabric version

# Enable debug mode
yieldfabric --debug execute commands.yaml

# Override service URLs
yieldfabric --pay-service-url https://custom-pay.example.com execute commands.yaml
```

### Head Co → Subsidiary ownership suites

The live YAML suites for group-account ownership are:

- `scripts/tests/group_account_ownership_nested_jwt_suite.yaml` — the complete
  three-authority relationship saga, discovery, one-hop exchange, custodial
  USER-key Automatic execution, external USER-EOA Manual execution, denied
  group/platform-key and persistent-administration surfaces, and live
  revocation matrix.
- `scripts/tests/group_account_ownership_expiry_suite.yaml` — the separate slow
  test for the 60-second TTL floor and hard, zero-leeway child expiry.

Each suite owns the relationship lifecycle and expects a fresh canonical setup:

```bash
cd /Users/arturo/Development/YieldFabric/yieldfabric-docs/python
python3 -m yieldfabric.cli setup ../scripts/setup.yaml
python3 -m yieldfabric.cli execute \
  ../scripts/tests/group_account_ownership_nested_jwt_suite.yaml

# Reset before running the independent slow companion.
python3 -m yieldfabric.cli setup ../scripts/setup.yaml
python3 -m yieldfabric.cli execute \
  ../scripts/tests/group_account_ownership_expiry_suite.yaml
```

`assume_owned_group` never writes the child JWT into YAML outputs. It keeps the
JWT only in the runner process under an opaque `credential_name`; subsequent
payment, obligation, query, and test commands select it with
`parameters.credential`. Named ownership credentials are non-refreshable and
stop resolving locally at their signed `exp`. `validate_credential` is the
intentional exception used by the expiry suite: it can present the retained
expired token to `/protected/jwt` so the suite proves the server-side hard
expiry rather than only the local cache behavior.

The relationship commands exercise a dedicated NFT lifecycle, not the raw
`add_owner` API:

1. `establish_group_owner` by a live child Owner reserves the row.
2. A live parent Owner enqueues/reconciles its immutable credential mint.
3. The child Owner enqueues/reconciles `AddMember` until `active`.

All three POSTs use the human's personal JWT and explicit group IDs. The CLI
mints a separate direct-group credential only when it must poll the resulting
group-owned MQ message. Admin/member-manager access alone is intentionally
insufficient for this durable ownership ceremony.

`user_signing_key` selects an ordinary human USER key. A group key is never an
eligible nested signer. For the external branch, the test EOA lives at
`/tmp/yieldfabric-nested-head-operator.key`; after a clean database rebuild the
CLI re-proves and re-registers that same EOA rather than silently rotating it.
The key path must be a regular file, is forced to mode `0600`, and is created
with exclusive semantics so a symlink or concurrent replacement cannot capture
the private key.
`start_signature_listener` validates the JWT-bound authorization tuple and
recomputes the nonce-bound meta-transaction digest before each Manual
signature. Discovery, relationship, and exchange responses are parsed with
exact field sets and canonical UUID/address/chain/token formats; actor
substitution, expiry drift, unexpected refresh material, and an authorization
binding outside an NFT-backed session all fail before signing.

On successful completion both suites revoke the NFT relationship; the full
suite also removes its temporary external EOA from Head Co. The expiry suite
includes an intentional 61-second wall-clock sleep.

### Programmatic Usage

```python
from yieldfabric import YieldFabricConfig, YieldFabricRunner

# Create configuration
config = YieldFabricConfig(
    pay_service_url="https://pay.yieldfabric.io",
    auth_service_url="https://auth.yieldfabric.io",
    debug=True
)

# Execute commands
with YieldFabricRunner(config) as runner:
    success = runner.execute_file("commands.yaml")
    if success:
        print("All commands executed successfully!")
```

## 📚 Key Components

### 1. Configuration (`config.py`)

Centralized configuration management:

```python
@dataclass
class YieldFabricConfig:
    pay_service_url: str
    auth_service_url: str
    command_delay: int = 3
    debug: bool = False
    request_timeout: int = 10
    # ... more settings
```

### 2. Service Clients (`services/`)

Clean HTTP client abstraction:

```python
# Base client with common functionality
class BaseServiceClient:
    def _post(self, endpoint, data, token): ...
    def _get(self, endpoint, params, token): ...
    def check_health(self): ...

# Specialized clients
class AuthService(BaseServiceClient):
    def login(self, email, password): ...
    def login_with_group(self, email, password, group): ...

class PaymentsService(BaseServiceClient):
    def graphql_mutation(self, mutation, variables, token): ...
    def get_balance(self, denomination, obligor, group_id, token): ...
```

### 3. Executors (`executors/`)

Specialized command executors:

```python
class PaymentExecutor(BaseExecutor):
    def execute(self, command): ...
    def _execute_deposit(self, command): ...
    def _execute_withdraw(self, command): ...
    def _execute_instant(self, command): ...
    def _execute_accept(self, command): ...
```

### 4. Output Store (`core/output_store.py`)

Advanced variable substitution:

```python
class OutputStore:
    def store(self, command_name, field_name, value): ...
    def get(self, command_name, field_name): ...
    def substitute(self, value): ...  # Handles $var.field, $(shell), JSON
    def substitute_params(self, params): ...
```

### 5. Runner (`core/runner.py`)

Main orchestrator:

```python
class YieldFabricRunner:
    def execute_file(self, yaml_file): ...
    def execute_command(self, command): ...
    def show_status(self, yaml_file): ...
```

## 🔧 Advanced Features

### Custom Executors

Extend the base executor to add custom operations:

```python
from yieldfabric.executors.base import BaseExecutor
from yieldfabric.models import Command, CommandResponse

class CustomExecutor(BaseExecutor):
    def execute(self, command: Command) -> CommandResponse:
        # Your custom logic here
        pass
```

### Custom Service Clients

Create custom service clients:

```python
from yieldfabric.services.base import BaseServiceClient

class CustomService(BaseServiceClient):
    def custom_operation(self, params, token):
        response = self._post("/custom-endpoint", params, token)
        return response.json()
```

### Configuration from File

Load configuration from a file:

```python
import json
from yieldfabric import YieldFabricConfig

with open('config.json') as f:
    config_dict = json.load(f)

config = YieldFabricConfig.from_dict(config_dict)
```

## 🎨 Design Patterns Used

1. **Service Layer Pattern**: Services encapsulate external API interactions
2. **Strategy Pattern**: Different executors for different command types
3. **Builder Pattern**: Configuration and command builders
4. **Template Method**: Base executor defines execution flow
5. **Factory Pattern**: Executor selection based on command type
6. **Singleton Pattern**: Global output store and logger instances
7. **Context Manager**: Proper resource cleanup

## 🧪 Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=yieldfabric --cov-report=html

# Run specific test
pytest tests/test_executors/test_payment_executor.py
```

## 🔍 Debugging

Enable debug mode to see detailed execution logs:

```bash
# Via command line
yieldfabric --debug execute commands.yaml

# Via environment variable
export DEBUG=true
yieldfabric execute commands.yaml

# Programmatically
config = YieldFabricConfig(debug=True)
```

## 📊 Comparison: v1.0 vs v2.0

| Feature | v1.0 | v2.0 |
|---------|------|------|
| Architecture | Monolithic | Layered/Clean |
| Service Clients | Direct requests | Abstracted clients |
| Executors | Single file | Specialized classes |
| Configuration | Environment only | Centralized config |
| Logging | Basic colored output | Structured logger |
| Models | Dictionaries | Dataclasses |
| Validation | Basic | Multi-level |
| Testing | Limited | Test-ready |
| Extensibility | Difficult | Easy |
| Type Safety | Minimal | Comprehensive |

## 🛠️ Migration from v1.0

### API Changes

```python
# v1.0
from yieldfabric.main import YieldFabricCommandRunner
runner = YieldFabricCommandRunner(pay_url, auth_url)
runner.execute_all_commands("commands.yaml")

# v2.0
from yieldfabric import YieldFabricConfig, YieldFabricRunner
config = YieldFabricConfig(pay_service_url=pay_url, auth_service_url=auth_url)
with YieldFabricRunner(config) as runner:
    runner.execute_file("commands.yaml")
```

### YAML Compatibility

YAML files from v1.0 are fully compatible with v2.0. No changes required!

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Implement your changes with tests
4. Ensure all tests pass
5. Submit a pull request

## 📝 License

MIT License

## 🙏 Acknowledgments

- Original bash scripts by YieldFabric team
- Python port v1.0 contributors
- Refactoring and v2.0 architecture

## 📮 Support

- GitHub Issues: https://github.com/yieldfabric/yieldfabric-docs/issues
- Documentation: See `docs/` directory
- Examples: See `examples/` directory

---

**YieldFabric Python Port v2.0** - Enterprise-grade architecture for blockchain payment operations
