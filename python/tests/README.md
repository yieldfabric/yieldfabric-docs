# yieldfabric Python tests

This is where **end-to-end flow tests** live. Each test exercises a multi-step
business flow (deposit → instant → accept, swap lifecycle, obligation
issuance, etc.) against a live auth + payments backend using the framework's
v2 service clients.

Contract-level single-mutation tests live in the Rust tree at
`yieldfabric-payments/tests/` — see that directory's README.

---

## Layout

```
tests/
├── README.md              (this file)
├── test_core/             (empty — framework internals; not populated yet)
├── test_executors/        (empty)
├── test_services/         (empty)
├── test_utils/            (empty)
├── test_validation/       (empty)
├── test_unit/             ← offline unit tests (unittest.mock only; no backend)
│   ├── test_yf_*.py       (the `yf` command-line client: settings, session,
│   │                       settlement classifier, one test per command)
│   ├── test_redact.py     (credential masking in debug logs)
│   └── yf_helpers.py      (shared fixtures for those)
└── test_e2e/              ← all flow tests live here
    ├── __init__.py
    ├── conftest.py        (SEEDED_USERS, provision_user, config fixture)
    └── test_*.py          (one file per flow)
```

### `test_unit/`

Offline. Service methods are replaced with `unittest.mock` objects (there
is no requests-mock / responses dependency), the `yf` session file is
redirected into `tmp_path` via `YF_CONFIG_DIR`, and stdout/stderr are
captured with `capsys`. Run with `make test-unit` — it puts `.:..` on
`PYTHONPATH` because `test_manual_signature_attempt.py` imports the sibling
`loan_management` package from the `yieldfabric-docs` checkout; a bare
`pytest tests/test_unit` errors at collection on that file.

### `test_e2e/conftest.py`

Provides two critical fixtures:

- **`config`** (session-scoped) — a `YieldFabricConfig` pointing at localhost.
  Skips every test if auth or payments isn't reachable.
- **Seeded credentials** via `SEEDED_USERS` dict. Sourced from
  `yieldfabric-docs/scripts/setup.yaml`. Flow tests that need on-chain
  settlement must use these — fresh users created via `provision_user()`
  fail async with "ERC20: transfer amount exceeds balance" or missing
  `CryptoOperations` permission.
- **`provision_user(role="SuperAdmin")`** helper — for tests that only
  exercise resolver contract (not on-chain). Defaults to SuperAdmin because
  the MQ consumer needs `CryptoOperations`; override for permission-boundary
  tests.

---

## Running

```sh
cd /Users/arturo/Development/YieldFabric/yieldfabric-docs/python
PYTHONPATH=. python3 -m pytest tests/test_e2e/ -v
```

Skip-clean behaviour: if the local backend isn't up (auth at
`http://localhost:3000`, payments at `http://localhost:3002`), every test
skips with a clear reason — no failures, no environment dependency errors.

## Environment knobs

```sh
AUTH_SERVICE_URL=http://localhost:3000   # default
PAY_SERVICE_URL=http://localhost:3002    # default
```

## Prereqs for the happy-path flow tests

- Auth + payments services up locally.
- `setup_system.sh` has been run at some point against this backend so that
  the seeded users from `scripts/setup.yaml` exist (issuer@, investor@,
  payer@, etc.) and hold on-chain balance in `aud-token-asset`.
- The backend's MQ consumer is running (otherwise mutations submit OK but
  never settle, and polling-based tests will time out).

---

## Adding a new flow test

1. Pick a scenario from `yieldfabric-docs/scripts/*.yaml` (the hand-validated
   harness) — `commands.yaml`, `swap_deal.yaml`, `settle_annuity_aud.yaml`,
   `nc_acacia.yaml` are good starting points.
2. Create `test_e2e/test_<flow_name>.py`. Import `SEEDED_USERS` and the
   `config` fixture from `conftest.py`.
3. Use the v2 `AuthService` and `PaymentsService` clients (see
   `test_instant_payment_flow.py` for the pattern). Build GraphQL mutations
   via `GraphQLMutation.<NAME>` constants from
   `yieldfabric.utils.graphql`.
4. For mutations that queue to MQ and later settle on-chain, poll the
   next step (e.g. `accept` after `instant`) rather than sleeping blind —
   see `_accept_with_retry` in `test_instant_payment_flow.py`.

## Known drift / gotchas

- `commands.yaml` passwords differ from `setup.yaml` — always source
  credentials from `setup.yaml` (that's what `SEEDED_USERS` does).
- Asset IDs on the live backend are lower-hyphen-suffixed forms of the
  YAML ids (`aud-token-asset`, not `AUD`). Use
  `{ assets { all { id } } }` introspection to discover what's seeded.
- The v1 flat-layout modules at the package root (`main.py`, `auth.py`,
  `executors.py`) hard-code production URLs and are NOT used by these
  tests. We use the v2 `yieldfabric/` sub-package.
