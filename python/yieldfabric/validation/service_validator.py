"""
Service health validator
"""

from typing import Optional

from ..services import AgentsService, AuthService, PaymentsService
from ..utils.logger import get_logger


class ServiceValidator:
    """Validator for service health checks."""

    def __init__(
        self,
        auth_service: AuthService,
        payments_service: PaymentsService,
        debug: bool = False,
        agents_service: Optional[AgentsService] = None,
    ):
        """
        Initialize validator.

        Args:
            auth_service: Auth service client
            payments_service: Payments service client
            debug: Enable debug logging
            agents_service: Optional agents service client. When provided,
                its health is reported as a NON-FATAL pre-flight signal —
                only suites with deal-lifecycle commands need agents up, so
                a down agents service warns but doesn't fail validation for
                suites that don't touch it.
        """
        self.auth_service = auth_service
        self.payments_service = payments_service
        self.agents_service = agents_service
        self.logger = get_logger(debug=debug)

    def validate_services(self) -> bool:
        """
        Validate that required services are available.

        Returns:
            True if all REQUIRED services (auth + payments) are healthy.
            Agents health is advisory only (see __init__).
        """
        auth_healthy = self.auth_service.check_health()
        payments_healthy = self.payments_service.check_health()

        if not auth_healthy:
            self.logger.error(f"❌ Auth service is not reachable at {self.auth_service.base_url}")
            self.logger.warning("Please check your connection or start the auth service")
        else:
            self.logger.success(f"✅ Auth service is healthy at {self.auth_service.base_url}")

        if not payments_healthy:
            self.logger.error(f"❌ Payments service is not reachable at {self.payments_service.base_url}")
            self.logger.warning("Please check your connection or start the payments service")
        else:
            self.logger.success(f"✅ Payments service is healthy at {self.payments_service.base_url}")

        # Advisory: agents hosts the deal-flow GraphQL + the deal-period
        # scheduler. Warn (don't fail) when it's down — only deal suites
        # need it, and they'll surface a clear per-command error if so.
        if self.agents_service is not None:
            if self.agents_service.check_health():
                self.logger.success(
                    f"✅ Agents service is healthy at {self.agents_service.base_url}"
                )
            else:
                self.logger.warning(
                    f"⚠️  Agents service is not reachable at {self.agents_service.base_url} "
                    "— deal-lifecycle commands (propose_deal / sign_deal / "
                    "activate_deal / set_automation_key / deal_periods) will fail until it's up"
                )

        return auth_healthy and payments_healthy
