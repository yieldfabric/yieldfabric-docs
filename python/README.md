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
pip install -e .          # distribution `yieldfabric-cli`, import package `yieldfabric`
```

This installs two console scripts from one package:

| Script | What it is |
|---|---|
| `yf` | the command-line client — one operation per invocation, `--json` for scripts and agents (below) |
| `yieldfabric` | the YAML command-file runner / setup harness (the rest of this README) |

## `yf` — command-line client

`yf` is a thin front end over the service clients in `yieldfabric/services/`
(auth, payments, agents). It talks to the production hosts by default, reads
its configuration from `YF_*` environment variables and flags only, and never
picks up a `.env` from the current directory (pass `--env-file` explicitly if
you keep one).

```bash
yf login --email you@example.com                 # password prompted; session stored
yf whoami                                        # who am I, which chain, which wallet
yf balance --asset USDx
yf send --asset USDx --amount 12.50 --to-wallet <their wallet id> --wait   # human-readable amount; converted to base units exactly
yf accept-all --asset USDx --wait
yf obligation create --asset USDx --counterpart-wallet <wallet id> --wait   # → contract_id, acceptable: true
yf obligation accept --contract CONTRACT-OBLIGATION-… --wait
yf settle <message_id>                           # wait for one submission, print its state
yf group delegate --group "Treasury" --ttl 1800  # delegation JWT → export YF_TOKEN=…
yf kg count --workspace <working_group_id> --term "ACN 123 456 789"
yf kg retrieve --workspace <working_group_id> --query "rent review clause"
yf --json …                                      # any command, machine-readable (`yf whoami --json` works too)
```

Run `yf --help` and `yf <command> --help` for every flag; `make yf-help`
shows the same without installing.

#### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `YF_API_KEY` | – | a `yf_api_…` key; exchanged for a session on every invocation (`--api-key`) |
| `YF_TOKEN` | – | a raw bearer used as-is, e.g. a delegation JWT (`--token`) |
| `YF_CHAIN` | `153` | chain id (`--chain`). `153` is the public **test** chain, `151` is **live** |
| `YF_AUTH_URL` | `https://auth.yieldfabric.com` | auth host (`--auth-url`) |
| `YF_PAYMENTS_URLS` | `{"153": "https://pay.test.yieldfabric.com", "151": "https://pay.live.yieldfabric.com"}` | JSON object `{chain_id: url}`, merged over the defaults; the payments host is chosen by the resolved chain (`--payments-url` overrides for that chain) |
| `YF_AGENTS_URL` | `https://agents.yieldfabric.com` | agents host, used by `kg …` (`--agents-url`) |
| `YF_CONFIG_DIR` | `~/.config/yf` | where `session.json` lives |
| `YF_TIMEOUT` | `30` | HTTP timeout in seconds (`--timeout`) |
| `YF_PASSWORD` | – | password for `yf login --email` (avoids putting it in argv) |
| `YF_DEBUG` | – | `1` = verbose request logging on stderr (`--debug`). Credentials in logged responses are masked (`***redacted***`), but treat debug output as sensitive: do not capture it into shared or CI logs |

Chain precedence: `--chain` > `YF_CHAIN` > the bearer's own chain when
`--token` is used > the chain of the stored login > `153`. Whatever the source,
the session must have been minted for that chain — a session for another chain
is refused up front (`chain_mismatch`, exit 2) because the payments host would
reject it anyway.

#### Credentials and the session file

Resolution order: `--token`/`YF_TOKEN` → `--api-key`/`YF_API_KEY` (stateless,
exchanged per call) → the session stored by `yf login`. `yf login` writes
`$YF_CONFIG_DIR/session.json` (mode `0600`, one record per auth host) holding
the access and refresh token; an access token within 60 s of expiry is renewed
through the refresh endpoint and, because refresh tokens are single-use, the
rotated pair is written back before the command runs. `yf logout` deletes the
record. Tokens are never printed unless `--json --show-tokens` is passed to
`login`.

Credential failures keep the platform's answer rather than collapsing into
one generic refusal: a rejected key, password or refresh token is exit `4`
with the server's reason and `http_status`; a connector key (or a session
minted from one) asked for a chain outside its `allowed_chains` is exit `1`
with `code: chain_not_allowed` and the allowed chains in the message; an
auth host that could not be reached is exit `1` with `code: unreachable`.

**Saved delegations.** `yf group delegate --save` stores the delegation
JWT *beside* the personal login for the auth host (under `delegation` in
the same record), never over it, and it becomes the active session until
it expires. Delegations are not refreshable: once expired, commands fail
with `delegation_expired` (exit 4) and the remedy is `yf group delegate
--save` again — or `yf logout --delegation`, which drops only the saved
delegation and returns you to the personal login. A fresh `yf login`
replaces the whole record, delegation included.

**Personal vs connector keys.** `POST /auth/api-key/generate` mints a
*personal* key by default; a `kind: connector` key (the kind the MCP
connectors take) mints a session that can read but cannot submit chain work
or mint delegations. `yf` reads `session_kind` from the session and refuses
`send`, `accept-all`, `obligation …` and `group delegate` under a connector
session with `connector_cannot_write` (exit 4) rather than surfacing a bare
`403`. `whoami`, `balance`, `settle` and `kg …` work with either kind.

#### `--live`

Chain `151` moves real value. Any command resolved to chain `151` refuses
to run without `--live` (`live_requires_flag`, exit 2), checked before any
request is sent. The guard keys on the payments **host** as well as the
chain: pointing any chain at `pay.live.yieldfabric.com` — or at a host that
`YF_PAYMENTS_URLS` maps to a live chain — through `--payments-url` or
`YF_PAYMENTS_URLS` also needs `--live`. Commands that never touch payments
(`kg …`, `version`, `logout`) skip the guard. This is a guard against
accidents, not what protects the funds: the platform still requires a
session minted for that chain and, for connector keys, a key allowed on it.

#### `--json` contract

With `--json` (before the command or after it — `--live` likewise),
stdout carries exactly one JSON document and every log line goes to stderr. Success:

```json
{"ok": true, "command": "send", "chain_id": "153", "mode": "TEST", "data": {"message_id": "…", "payment_id": "…", "idempotency_key": "…"}}
```

Failure (also on stdout):

```json
{"ok": false, "command": "send", "chain_id": "153", "error": {"code": "live_requires_flag", "message": "…", "http_status": 403, "details": {}}}
```

`command`, `chain_id`/`mode` (absent for commands that are not chain-scoped:
`kg …`, `version`, `logout`) and `error.code` are stable. Without `--json`
the result is printed as flat `key: value` lines on stdout and errors as a
single `error [code]: …` line on stderr.

| Exit | Meaning |
|---|---|
| `0` | ok |
| `1` | the platform answered and refused, or the operation reported failure (GraphQL errors, `success: false`, HTTP 4xx/5xx other than auth, `message_not_found`, `chain_not_allowed`), or a host could not be reached (`unreachable`) |
| `2` | usage / configuration: missing credential, unknown chain, live guard, chain mismatch, bad flags, `bad_message_id` |
| `3` | a wait ran out (`settle`, `--wait`) — the last observed state is in `error.details` |
| `4` | credential rejected (401/403, before **or during** a wait), exchange or login failed, expired saved delegation, or the session cannot perform the operation (connector) |
| `5` | the operation reached the chain and failed there (`state: failed`) |

#### Settlement: `executed` ≠ settled

Every submission (`send`, `accept-all`, `obligation …`) returns a
`message_id` as soon as the platform has accepted it. `yf settle <message_id>`
(and `--wait` on the submitting command) polls the operation's status and
reports one of:

| `state` | Meaning |
|---|---|
| `pending` | not executed yet — or a chain failure not yet recorded as final |
| `executed` | the chain transaction landed; the resulting records are still being written — do not read them yet |
| `settled` | the records are readable (final) |
| `failed` | the chain step failed and the failure is recorded (final) |

The output mirrors the payments MCP `wait_for_settlement` tool
(`message_id, state, executed_at, post_processed_at, error, retry_after_s,
lifecycle_status, post_processing_error_kind, timed_out`) plus `attempts`
and `elapsed`. `obligation create --wait` reports `acceptable: true` only
once settled — that is when `obligation accept` can find the contract.
`accept-all --wait` polls every returned message id and exits `5` if any
failed, `3` if any is still not settled when the wait runs out.

The first read of a wait is decisive: an id the platform does not know for
this session's entity is `message_not_found` (exit 1) immediately, with or
without `--no-wait`, and a rejected bearer is exit 4 — neither spins for
the timeout. A bearer that stops being accepted *during* a wait (an
expired delegation, a revoked key) aborts the wait with exit 4 after two
consecutive refusals.

Idempotency: every submission carries a fresh UUIDv4 `idempotencyKey`
(printed as `idempotency_key`). Pass `--idempotency-key` only to re-submit
the *same* operation; a reused key hands back the earlier submission instead
of a new one.

#### Knowledge (`kg`)

`kg count` is exhaustive — a tally per term, never a rank; a `*_capped`
tally is a floor and the command says so in `warning`. `--mode exact` (the
default) does no stemming (names, identifiers, clause numbers); `phrase`
stems; `fuzzy` is a substring scan and must not be presented as a finding.
`kg retrieve` is ranked (passages with citations, no synthesis); when
`lanes.any_degraded` is true the results are partial and `--effort hard`
re-runs with a larger budget. Both take `--workspace <working_group_id>`
and use the same bearer as everything else. Knowledge is not chain-scoped:
only the agents host is called, the envelope carries no `chain_id`/`mode`,
the live guard does not run, and no payments host is needed for the
resolved chain.

Tests for the client live in `tests/test_unit/test_yf_*.py`
(`make test-unit`); they mock the service methods and never touch the
network.

---

## `yieldfabric` — YAML command runner and setup harness

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
# Offline unit tests (incl. the yf client) — no backend needed
make test-unit                      # PYTHON=/usr/bin/python3 if your default python3 lacks pytest

# Everything (E2E flows skip themselves when no backend is reachable)
make test

# With coverage
make test-coverage
```

`make test*` puts `.:..` on `PYTHONPATH`: one unit test imports the sibling
`loan_management` package from the `yieldfabric-docs` checkout, so a bare
`pytest` from this directory errors at collection.

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
