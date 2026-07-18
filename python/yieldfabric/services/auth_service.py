"""
Auth service client
"""

import time
from typing import List, Optional

from .base import BaseServiceClient
from ..config import YieldFabricConfig
from ..utils.jwt import extract_claim


class AuthService(BaseServiceClient):
    """Client for Auth Service."""
    
    def __init__(self, config: YieldFabricConfig):
        """
        Initialize Auth Service client.
        
        Args:
            config: YieldFabric configuration
        """
        super().__init__(config.auth_service_url, config)
    
    def login_session(self, email: str, password: str) -> Optional[dict]:
        """
        Login user and keep the full token bundle.
        
        Args:
            email: User email
            password: User password
            
        Returns:
            Normalized token bundle or None if login fails
        """
        self.logger.info(f"  🔐 Logging in user: {email}")
        
        payload = {
            "email": email,
            "password": password,
            "services": ["vault", "payments"]
        }
        
        try:
            response = self._post("/auth/login/with-services", payload)
            data = response.json()
            
            self.logger.debug(f"    📡 Login response: {data}")
            
            token = data.get('token') or data.get('access_token') or data.get('jwt')
            refresh_token = data.get('refresh_token') or data.get('refreshToken')
            expires_in = data.get('expires_in') or data.get('expiresIn')
            
            if token:
                session = {
                    "access_token": token,
                    "refresh_token": refresh_token,
                    "expires_in": expires_in,
                    "raw": data,
                }

                target_chain = self.config.chain_id
                current_chain = extract_claim(
                    token, "default_chain_id", "chain_id", "chainId"
                )
                if target_chain and str(current_chain or "") != target_chain:
                    if not refresh_token:
                        self.logger.error(
                            "    ❌ Login cannot pin the session to chain "
                            f"{target_chain}: no refresh token was returned"
                        )
                        return None
                    self.logger.info(
                        f"    🔀 Pinning session to chain {target_chain}"
                    )
                    pinned = self.refresh_access_token(
                        refresh_token, chain_id=target_chain
                    )
                    if not pinned:
                        return None
                    session = pinned

                self.logger.success("    ✅ Login successful")
                return session
            else:
                self.logger.error("    ❌ No token in response")
                return None
        
        except Exception as e:
            self.logger.error(f"    ❌ Login failed: {e}")
            return None

    def login(self, email: str, password: str) -> Optional[str]:
        """
        Login user and get JWT token.

        Compatibility wrapper for call sites that only need the access
        token. YAML execution uses TokenManager.login_session so refresh
        tokens are retained.
        """
        session = self.login_session(email, password)
        return session.get("access_token") if session else None

    def refresh_access_token(
        self,
        refresh_token: str,
        *,
        chain_id: str = "31337",
    ) -> Optional[dict]:
        """
        Exchange a refresh token for a fresh access token.

        The auth service rotates refresh tokens, so callers should keep
        the returned refresh_token when present.
        """
        self.logger.debug("  🔁 Refreshing access token")

        payload = {
            "refresh_token": refresh_token,
            "chain_id": chain_id,
        }

        try:
            response = self._post("/auth/refresh", payload)
            data = response.json()

            self.logger.debug(f"    📡 Refresh response: {data}")

            token = data.get('access_token') or data.get('token') or data.get('jwt')
            if not token:
                self.logger.error("    ❌ No access token in refresh response")
                return None

            return {
                "access_token": token,
                "refresh_token": data.get('refresh_token') or data.get('refreshToken'),
                "expires_in": data.get('expires_in') or data.get('expiresIn'),
                "raw": data,
            }

        except Exception as e:
            self.logger.error(f"    ❌ Token refresh failed: {e}")
            return None

    def authenticate_api_key_session(self, api_key: str) -> Optional[dict]:
        """
        Exchange a backend-service API key for a short-lived token bundle.

        POST /auth/api-key with {"api_key": "yf_api_…"}. The auth service
        mints a permission-complete user JWT for the key owner, carrying the
        owner's permissions + entity_scope (same AuthResponse shape as
        /auth/login), so the
        returned token is usable for vault/payments/keys operations —
        unlike the bare password JWT. Issue a key once via
        POST /auth/api-key/generate (with a one-time user JWT).

        Args:
            api_key: The `yf_api_…` secret.

        Returns:
            Normalized token bundle or None if the key is invalid / the call
            fails. Keeping the refresh token lets non-interactive setup
            activate the key owner's lazy chain account and then refresh the
            JWT's wallet snapshot without re-presenting another credential.
        """
        self.logger.info("  🔑 Authenticating with API key")

        try:
            payload = {"api_key": api_key}
            if self.config.chain_id:
                payload["chain_id"] = self.config.chain_id
            response = self._post("/auth/api-key", payload)
            data = response.json()

            self.logger.debug(f"    📡 API-key auth response: {data}")

            token = data.get('token') or data.get('access_token') or data.get('jwt')

            if token:
                self.logger.success("    ✅ API-key authentication successful")
                return {
                    "access_token": token,
                    "refresh_token": data.get('refresh_token') or data.get('refreshToken'),
                    "expires_in": data.get('expires_in') or data.get('expiresIn'),
                    "raw": data,
                }
            else:
                self.logger.error("    ❌ No token in API-key auth response")
                return None

        except Exception as e:
            self.logger.error(f"    ❌ API-key authentication failed: {e}")
            return None

    def authenticate_api_key(self, api_key: str) -> Optional[str]:
        """Compatibility wrapper returning only the API-key access token."""
        session = self.authenticate_api_key_session(api_key)
        return session.get("access_token") if session else None

    def generate_api_key(
        self,
        token: str,
        *,
        service_name: str,
        description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Mint a `yf_api_…` key for the caller via
        POST /auth/api-key/generate (authenticated with the caller's own
        user JWT). The returned key is owned by the caller's entity — so a
        payer minting a key here gets one scoped to themselves, which is
        exactly what `setDealAutomationKey` needs (the scheduler later
        exchanges it for an account-bearing JWT to fire the payer's
        periods).

        Returns the `yf_api_…` secret, or None on failure. The secret is
        shown ONCE here; the caller hands it straight to the credential
        store and never persists it client-side.
        """
        self.logger.info(f"  🔑 generate_api_key service={service_name}")
        payload: dict = {"service_name": service_name}
        if description is not None:
            payload["description"] = description
        try:
            response = self._post("/auth/api-key/generate", payload, token=token)
            data = response.json()
            api_key = data.get("api_key")
            if api_key:
                self.logger.success("    ✅ API key generated")
                return api_key
            self.logger.error("    ❌ No api_key in generate response")
            return None
        except Exception as e:
            self.logger.error(f"    ❌ generate_api_key failed: {e}")
            return None

    def get_groups(self, token: str) -> List[dict]:
        """
        Get list of groups for user.
        
        Args:
            token: JWT token
            
        Returns:
            List of group dictionaries
        """
        self.logger.debug("  🏢 Fetching user groups")
        
        try:
            response = self._get("/auth/groups", token=token)
            groups = response.json()
            
            if isinstance(groups, list):
                self.logger.debug(f"    ✅ Found {len(groups)} groups")
                return groups
            else:
                self.logger.warning("    ⚠️  Unexpected response format")
                return []
        
        except Exception as e:
            self.logger.error(f"    ❌ Failed to fetch groups: {e}")
            return []
    
    def get_user_groups(self, token: str) -> List[dict]:
        """
        Get list of groups the user is a member of.
        
        Args:
            token: JWT token
            
        Returns:
            List of group dictionaries
        """
        self.logger.debug("  🏢 Fetching user groups (member of)")
        
        try:
            response = self._get("/auth/groups/user", token=token)
            groups = response.json()
            
            if isinstance(groups, list):
                self.logger.debug(f"    ✅ Found {len(groups)} groups")
                return groups
            else:
                self.logger.warning("    ⚠️  Unexpected response format")
                return []
        
        except Exception as e:
            self.logger.error(f"    ❌ Failed to fetch user groups: {e}")
            return []
    
    def get_group_id_by_name(self, token: str, group_name: str) -> Optional[str]:
        """
        Get group ID by name.
        
        Args:
            token: JWT token
            group_name: Name of the group
            
        Returns:
            Group ID or None if not found
        """
        self.logger.info(f"  🔍 Looking up group ID for: {group_name}")
        
        groups = self.get_groups(token)
        
        for group in groups:
            if group.get("name") == group_name:
                group_id = group.get("id")
                self.logger.success(f"    ✅ Found group ID: {group_id[:8] if group_id else 'N/A'}...")
                return group_id
        
        self.logger.error(f"    ❌ Group not found: {group_name}")
        return None
    
    def create_delegation_session(
        self,
        user_token: str,
        group_id: str,
        group_name: str,
    ) -> Optional[dict]:
        """
        Create a delegation JWT and retain its paired refresh token.
        
        Args:
            user_token: User JWT token
            group_id: ID of the group
            group_name: Name of the group (for logging)
            
        Returns:
            Normalized delegation token bundle or None if creation fails.
        """
        self.logger.info(f"  🎫 Creating delegation JWT for group: {group_name}")
        self.logger.debug(f"    Group ID: {group_id[:8] if group_id else 'N/A'}...")
        
        payload = {
            "group_id": group_id,
            "delegation_scope": self.config.delegation_scopes,
            "expiry_seconds": self.config.jwt_expiry_seconds
        }
        
        try:
            response = self._post("/auth/delegation/jwt", payload, token=user_token)
            data = response.json()
            
            self.logger.debug(
                f"    Delegation response keys: {sorted(data.keys())}"
            )
            
            delegation_token = (
                data.get('delegation_jwt') or
                data.get('token') or
                data.get('delegation_token') or
                data.get('jwt')
            )
            
            if delegation_token:
                self.logger.success("    ✅ Delegation JWT created successfully")
                return {
                    "access_token": delegation_token,
                    "refresh_token": data.get('refresh_token') or data.get('refreshToken'),
                    "expires_in": data.get('expiry_seconds') or data.get('expires_in'),
                    "group_id": data.get('group_id') or group_id,
                    "chain_id": data.get('chain_id'),
                    "raw": data,
                }
            else:
                self.logger.error("    ❌ Failed to create delegation JWT")
                self.logger.warning(f"    Response: {data}")
                return None
        
        except Exception as e:
            self.logger.error(f"    ❌ Failed to create delegation JWT: {e}")
            return None

    def create_delegation_token(
        self,
        user_token: str,
        group_id: str,
        group_name: str,
    ) -> Optional[str]:
        """Compatibility wrapper returning only the delegation access JWT."""
        session = self.create_delegation_session(user_token, group_id, group_name)
        return session.get("access_token") if session else None
    
    def login_with_group(self, email: str, password: str, group_name: str) -> Optional[str]:
        """
        Login user and create delegation token for a specific group.

        Args:
            email: User email
            password: User password
            group_name: Name of the group for delegation

        Returns:
            Delegation JWT token or regular token if delegation fails
        """
        # First, login to get user token
        token = self.login(email, password)
        if not token:
            return None

        # Get group ID
        self.logger.cyan(f"  🏢 Group delegation requested for: {group_name}")
        group_id = self.get_group_id_by_name(token, group_name)

        if not group_id:
            self.logger.warning("    ⚠️  Group not found, using regular token")
            return token

        # Create delegation token
        delegation_token = self.create_delegation_token(token, group_id, group_name)

        if delegation_token:
            self.logger.success("    ✅ Group delegation successful")
            return delegation_token
        else:
            self.logger.warning("    ⚠️  Delegation failed, using regular token")
            return token

    # ------------------------------------------------------------------
    # Group-admin operations (auth-service REST endpoints).
    # These mirror the shell functions in executors_additional.sh:
    #   execute_add_owner / execute_remove_owner
    #   execute_add_account_member / execute_remove_account_member
    #   execute_get_account_owners / execute_get_account_members
    # All expect a group_id resolved via get_group_id_by_name first.
    # ------------------------------------------------------------------

    def get_user_group_id_by_name(self, token: str, group_name: str) -> Optional[str]:
        """
        Resolve group name → group id, searching groups the user is a
        MEMBER of (GET /auth/groups/user). Some admin operations require
        this narrower view rather than the full groups list.
        """
        groups = self.get_user_groups(token)
        for group in groups:
            if group.get("name") == group_name:
                return group.get("id")
        self.logger.error(f"    ❌ Group not found in user's groups: {group_name}")
        return None

    def add_group_owner(self, token: str, group_id: str, new_owner: str) -> dict:
        """POST /auth/groups/{id}/add-owner — add an on-chain owner."""
        self.logger.info(
            f"  📤 add_group_owner group_id={group_id[:8]}... new_owner={new_owner}"
        )
        return self._post_json_safe(
            f"/auth/groups/{group_id}/add-owner",
            {"new_owner": new_owner},
            token=token,
            description="add_group_owner",
        )

    def remove_group_owner(self, token: str, group_id: str, old_owner: str) -> dict:
        """POST /auth/groups/{id}/remove-owner — remove an on-chain owner."""
        self.logger.info(
            f"  📤 remove_group_owner group_id={group_id[:8]}... old_owner={old_owner}"
        )
        return self._post_json_safe(
            f"/auth/groups/{group_id}/remove-owner",
            {"old_owner": old_owner},
            token=token,
            description="remove_group_owner",
        )

    def add_account_member(
        self,
        token: str,
        group_id: str,
        obligation_id: str,
        obligation_address: Optional[str] = None,
    ) -> dict:
        """
        POST /auth/groups/{id}/add-account-member — grant a group wallet
        permission to hold the given obligation/NFT. `obligation_address`
        is optional; the backend falls back to its configured default
        confidential-obligation address when None.
        """
        payload: dict = {"obligation_id": obligation_id}
        if obligation_address:
            payload["obligation_address"] = obligation_address
        self.logger.info(
            f"  📤 add_account_member group_id={group_id[:8]}... obligation_id={obligation_id}"
        )
        return self._post_json_safe(
            f"/auth/groups/{group_id}/add-account-member",
            payload,
            token=token,
            description="add_account_member",
        )

    def remove_account_member(
        self,
        token: str,
        group_id: str,
        obligation_id: str,
        obligation_address: Optional[str] = None,
    ) -> dict:
        """POST /auth/groups/{id}/remove-account-member."""
        payload: dict = {"obligation_id": obligation_id}
        if obligation_address:
            payload["obligation_address"] = obligation_address
        self.logger.info(
            f"  📤 remove_account_member group_id={group_id[:8]}... obligation_id={obligation_id}"
        )
        return self._post_json_safe(
            f"/auth/groups/{group_id}/remove-account-member",
            payload,
            token=token,
            description="remove_account_member",
        )

    def get_account_owners(self, token: str, group_id: str) -> dict:
        """GET /auth/groups/{id}/account-owners — returns {account_address, owners: [...]}"""
        return self._get_json_safe(
            f"/auth/groups/{group_id}/account-owners",
            token=token,
            description="get_account_owners",
            default={"status": "error", "owners": []},
        )

    def get_account_members(self, token: str, group_id: str) -> dict:
        """GET /auth/groups/{id}/account-members — returns {account_address, members: [...]}"""
        return self._get_json_safe(
            f"/auth/groups/{group_id}/account-members",
            token=token,
            description="get_account_members",
            default={"status": "error", "members": []},
        )

    # ------------------------------------------------------------------
    # Setup-phase operations.
    # Mirror `setup_system.sh` — create users, groups, add members, and
    # deploy group on-chain accounts. All handle 409 Conflict as idempotent
    # "already exists" (matching the shell's retry-safe behaviour).
    # ------------------------------------------------------------------

    def create_user(
        self,
        email: str,
        password: str,
        role: str,
        admin_token: Optional[str] = None,
    ) -> dict:
        """
        POST /auth/users — idempotent wrt email.

        Returns a dict:
            {"status": "created", "user_id": "..."}
            {"status": "exists"}   (HTTP 409)
            {"status": "error", "message": "..."}

        `admin_token` is optional: the first user can be created without
        auth; subsequent users typically need an admin JWT (though the
        auth service may allow creation without auth in dev — the shell
        passes a token when available and falls back to unauthenticated).
        """
        self.logger.info(f"  👤 create_user email={email} role={role}")
        import requests as _requests
        try:
            headers = {"Content-Type": "application/json"}
            if admin_token:
                headers["Authorization"] = f"Bearer {admin_token}"
            response = self.session.post(
                f"{self.base_url}/auth/users",
                json={"email": email, "password": password, "role": role},
                headers=headers,
                timeout=self.config.request_timeout,
            )
            if response.status_code == 200:
                data = response.json()
                user_id = (data.get("user") or {}).get("id") or data.get("id")
                return {"status": "created", "user_id": user_id}
            if response.status_code == 409:
                return {"status": "exists"}
            return {
                "status": "error",
                "message": f"HTTP {response.status_code}: {response.text[:200]}",
            }
        except _requests.RequestException as e:
            return {"status": "error", "message": str(e)}

    def create_group(
        self,
        creator_token: str,
        name: str,
        description: str,
        group_type: str = "project",
        *,
        deploy: bool = False,
    ) -> dict:
        """
        POST /auth/groups — create a group as the caller identified by
        `creator_token`. The creator is the group's initial owner.

        Returns:
            {"status": "created", "group_id": "...", "account_activation": {...}}
            {"status": "exists"}          (HTTP 409)
            {"status": "error", "message"}
        """
        self.logger.info(f"  🏢 create_group name={name} type={group_type}")
        import requests as _requests
        try:
            response = self.session.post(
                f"{self.base_url}/auth/groups",
                json={
                    "name": name,
                    "description": description,
                    "group_type": group_type,
                    # Setup owns the chain-qualified lazy activation lifecycle.
                    # Keeping create off-chain avoids holding this request open
                    # while a public-chain DeployAccount transaction settles.
                    "deploy": deploy,
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {creator_token}",
                },
                timeout=self.config.request_timeout,
            )
            if response.status_code in (200, 202):
                data = response.json()
                return {
                    "status": "created",
                    "group_id": data.get("id"),
                    "account_activation": data.get("account_activation"),
                    "http_status": response.status_code,
                }
            if response.status_code == 409:
                return {"status": "exists"}
            return {
                "status": "error",
                "message": f"HTTP {response.status_code}: {response.text[:200]}",
            }
        except _requests.RequestException as e:
            return {"status": "error", "message": str(e)}

    def add_group_member(
        self,
        actor_token: str,
        group_id: str,
        user_id: str,
        role: str,
    ) -> dict:
        """
        POST /auth/groups/{id}/members — add a user to a group with a
        named role. Valid roles: owner, admin, member, viewer, policymember.

        `policymember` is the RESTRICTED role: the auth service mints it a
        delegation scoped to [PolicyExecution, CryptoOperations] only (capped
        at 1h), and it is NOT an on-chain account owner — so it may EXECUTE a
        group's data policy but cannot approve it or otherwise act for the
        group. Mirrors `GroupMemberRole::PolicyMember`
        (yieldfabric-auth/src/types.rs).
        """
        if role not in ("owner", "admin", "member", "viewer", "policymember"):
            return {"status": "error", "message": f"invalid role: {role}"}

        self.logger.info(f"  ➕ add_group_member group={group_id[:8]}... user={user_id[:8]}... role={role}")
        import requests as _requests
        try:
            response = self.session.post(
                f"{self.base_url}/auth/groups/{group_id}/members",
                json={"user_id": user_id, "role": role},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {actor_token}",
                },
                timeout=self.config.request_timeout,
            )
            if response.status_code == 200:
                return {"status": "added"}
            if response.status_code == 409:
                return {"status": "exists"}
            return {
                "status": "error",
                "message": f"HTTP {response.status_code}: {response.text[:200]}",
            }
        except _requests.RequestException as e:
            return {"status": "error", "message": str(e)}

    def group_account_status(self, token: str, group_id: str) -> Optional[str]:
        """
        GET /auth/groups/{id}/account-status — returns the status string
        (e.g. "deployed", "not_deployed") or None if the response is
        malformed / endpoint errored.
        """
        try:
            response = self._get(
                f"/auth/groups/{group_id}/account-status",
                token=token,
            )
            data = response.json()
            return (data.get("account_status") or {}).get("status")
        except Exception as e:
            self.logger.error(f"    ❌ group_account_status failed: {e}")
            return None

    def group_account_info(self, token: str, group_id: str) -> dict:
        """
        GET /auth/groups/{id}/account-status — the full `account_status`
        object (`status`, `account_address`, `chain_id`, ...). Used to
        resolve a deployed group's on-chain account address when a JWT
        claim is unavailable. Returns {} on any failure.
        """
        try:
            response = self._get(
                f"/auth/groups/{group_id}/account-status",
                token=token,
            )
            data = response.json()
            info = data.get("account_status")
            return info if isinstance(info, dict) else {}
        except Exception as e:
            self.logger.debug(f"group_account_info failed: {e}")
            return {}

    def get_user_chain_accounts(self, token: str, user_id: str) -> List[dict]:
        """
        GET /entities/user/{user_id}/chain-accounts — the user's on-chain
        (smart-)account deployments. Each item carries `is_default`,
        `account_address`, and `chain_id`.

        MUST be read with the user's OWN token — the endpoint forbids
        reading another user's accounts. Returns [] on any failure or
        when nothing is deployed yet (the caller polls). Mirrors the
        `print_user_account_address` read in setup_system.sh.
        """
        try:
            response = self._get(
                f"/entities/user/{user_id}/chain-accounts",
                token=token,
            )
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.debug(f"get_user_chain_accounts failed: {e}")
            return []

    def activate_chain_account(
        self, token: str, entity_kind: str, entity_id: str, chain_id: str
    ) -> dict:
        """Start or reconcile one explicit per-chain smart-account activation.

        The endpoint is idempotent within its durable attempt. Callers may
        safely re-POST while it reports ``provisioning``; a terminal retryable
        failure advances to a new attempt on the next POST.
        """
        try:
            response = self._post(
                f"/entities/{entity_kind}/{entity_id}/chain-accounts/{chain_id}/activation",
                {},
                token=token,
                timeout=330,
            )
            data = response.json()
            return data if isinstance(data, dict) else {}
        except Exception as e:
            response = getattr(e, "response", None)
            if response is not None:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
            self.logger.error(
                f"activate_chain_account({entity_kind}, {chain_id}) failed: {e}"
            )
            return {}

    def get_chain_account_activation(
        self, token: str, entity_kind: str, entity_id: str, chain_id: str
    ) -> dict:
        """Read one activation resource without advancing its attempt."""
        try:
            response = self._get(
                f"/entities/{entity_kind}/{entity_id}/chain-accounts/{chain_id}/activation",
                token=token,
            )
            data = response.json()
            return data if isinstance(data, dict) else {}
        except Exception as e:
            self.logger.debug(
                f"get_chain_account_activation({entity_kind}, {chain_id}) failed: {e}"
            )
            return {}

    def wait_for_chain_account_activation(
        self,
        token: str,
        entity_kind: str,
        entity_id: str,
        chain_id: str,
        *,
        attempts: int = 12,
        interval: float = 2.0,
    ) -> dict:
        """Activate and wait for auth-side readiness.

        GET supplies the normal polling cadence. Every third observation
        re-POSTs so auth can reconcile an MQ execution that completed after an
        ambiguous handoff; a terminal failure is re-POSTed immediately to
        allocate its next durable attempt.
        """
        state = self.activate_chain_account(
            token, entity_kind, entity_id, str(chain_id)
        )
        for observation in range(max(1, attempts)):
            if state.get("status") == "ready":
                return state
            if observation >= attempts - 1:
                break
            time.sleep(interval)
            if state.get("status") == "failed_retryable" or observation % 3 == 2:
                state = self.activate_chain_account(
                    token, entity_kind, entity_id, str(chain_id)
                )
            else:
                state = self.get_chain_account_activation(
                    token, entity_kind, entity_id, str(chain_id)
                )
        return state

    def sign_vault(
        self,
        token: str,
        *,
        contact_id: str,
        data: str,
        data_format: str = "hex",
    ) -> dict:
        """
        POST /key-operations/vault/sign — sign `data` with the entity's
        server-custodied signing key (oldest active `Signing` keypair).

        `contact_id` is the entity to sign FOR — a user/group UUID or an
        on-chain account address. `data` is the value to sign verbatim; for
        an EIP-191 personal_sign signature (what `approveDataPolicy` recovers)
        pass the EIP-191 message-hash as bare hex with `data_format="hex"`
        (see `yieldfabric.utils.crypto.eip191_message_hash`). The endpoint
        signs the 32-byte digest it is handed — it does NOT apply the EIP-191
        prefix itself, mirroring the wallet-SDK's server-held signing path.

        Returns the raw JSON body: `{"success", "result": <0x-less hex sig>,
        "result_format", ...}`. No client-side key material is involved.
        """
        payload = {
            "contact_id": contact_id,
            "data": data,
            "data_format": data_format,
        }
        try:
            response = self._post(
                "/key-operations/vault/sign", payload, token=token
            )
            return response.json()
        except Exception as e:
            self.logger.error(f"    ❌ sign_vault failed: {e}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------
    # External-key management (loan_management parity).
    #
    # Port of `loan_management/modules/register_external_key.py` REST
    # calls. The crypto primitives (generate key / sign message) live
    # in `yieldfabric.utils.crypto`; this class handles only the HTTP.
    # ------------------------------------------------------------------

    def get_user_id_from_profile(self, token: str) -> Optional[str]:
        """
        GET /auth/users/me — returns the logged-in user's UUID.

        Needed when we only have a JWT (e.g. after login) and need the
        user_id for downstream endpoints like `register_external_key`
        or `deploy-account`, neither of which extract it from the
        bearer themselves.
        """
        try:
            response = self._get("/auth/users/me", token=token)
            data = response.json()
            user = data.get("user") if isinstance(data, dict) else None
            if isinstance(user, dict):
                uid = user.get("id")
                return str(uid).strip() if uid else None
        except Exception as e:
            self.logger.debug(f"get_user_id_from_profile failed: {e}")
        return None

    def register_external_key(
        self,
        token: str,
        *,
        user_id: str,
        key_name: str,
        public_key: str,
        register_with_wallet: bool = False,
        expires_at: Optional[str] = None,
    ) -> dict:
        """
        POST /keys/external — register an external (client-generated)
        key for `user_id`. `public_key` is a 0x-prefixed Ethereum
        address. Returns the key pair record (includes `id` used by
        `register_key_with_specific_wallet`).
        """
        payload: dict = {
            "user_id": user_id,
            "key_name": key_name,
            "public_key": public_key,
            "register_with_wallet": register_with_wallet,
        }
        if expires_at is not None:
            payload["expires_at"] = expires_at
        try:
            response = self._post("/keys/external", payload, token=token)
            return response.json()
        except Exception as e:
            raise RuntimeError(f"register_external_key failed: {e}") from e

    def verify_external_key_ownership(
        self,
        token: str,
        *,
        public_key: str,
        message: str,
        signature: str,
        signature_format: str = "hex",
    ) -> dict:
        """
        POST /keys/external/verify-ownership — confirm (before
        registering) that the signer actually holds `public_key`.

        This call is what the frontend makes before POST /keys/external
        so the user gets a clear error if the ownership proof is
        malformed. The backend returns {"valid": bool, "message": ...}.
        """
        payload = {
            "public_key": public_key,
            "message": message,
            "signature": signature,
            "signature_format": signature_format,
        }
        try:
            response = self._post(
                "/keys/external/verify-ownership", payload, token=token
            )
            return response.json()
        except Exception as e:
            raise RuntimeError(f"verify_external_key_ownership failed: {e}") from e

    def get_user_keys(self, token: str, user_id: str) -> List[dict]:
        """
        GET /keys/users/{user_id}/keys — list every key pair registered
        to this user. Returns [] on any failure.
        """
        try:
            response = self._get(f"/keys/users/{user_id}/keys", token=token)
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            self.logger.debug(f"get_user_keys failed: {e}")
            return []

    def get_key_id_by_address(
        self, token: str, user_id: str, address: str
    ) -> Optional[str]:
        """
        Look up a key's UUID id by its on-chain address. Normalises both
        sides to lowercase + 0x-prefixed before comparing, so a caller
        can pass any common casing. Returns None if the key isn't
        registered to this user.
        """
        want = (address or "").strip().lower()
        if not want:
            return None
        if not want.startswith("0x"):
            want = "0x" + want
        for k in self.get_user_keys(token, user_id):
            pk = (k.get("public_key") or "").strip().lower()
            if pk and not pk.startswith("0x"):
                pk = "0x" + pk
            if pk == want:
                kid = k.get("id")
                return str(kid) if kid else None
        return None

    def register_key_with_specific_wallet(
        self, token: str, *, key_id: str, wallet_address: str
    ) -> dict:
        """
        POST /keys/register-with-specific-wallet — register an already
        existing key as an owner of a specific wallet (e.g. a loan
        wallet). Returns the backend's response dict.
        """
        payload = {"key_id": key_id, "wallet_address": (wallet_address or "").strip()}
        try:
            response = self._post(
                "/keys/register-with-specific-wallet", payload, token=token
            )
            return response.json()
        except Exception as e:
            raise RuntimeError(f"register_key_with_specific_wallet failed: {e}") from e

    def deploy_group_account(self, token: str, group_id: str) -> dict:
        """
        Compatibility wrapper for POST /auth/groups/{id}/deploy-account.

        New callers should use ``wait_for_chain_account_activation`` with
        entity kind ``group`` and an explicit JWT-selected chain. The legacy
        route delegates to that lifecycle but cannot expose chain context in
        its URL.
        """
        self.logger.info(f"  🚀 deploy_group_account group={group_id[:8]}...")
        try:
            response = self._post(
                f"/auth/groups/{group_id}/deploy-account",
                data={},
                token=token,
            )
            return response.json()
        except Exception as e:
            self.logger.error(f"    ❌ deploy_group_account failed: {e}")
            return {"status": "error", "message": str(e)}
