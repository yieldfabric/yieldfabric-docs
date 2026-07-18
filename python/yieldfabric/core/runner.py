"""
Core runner class for YieldFabric
"""

import time
from typing import List, Optional

from ..config import YieldFabricConfig
from ..models import Command, CommandResponse
from ..services import AgentsService, AuthService, PaymentsService
from ..executors import (
    AssertExecutor,
    ComposedExecutor,
    DealExecutor,
    GroupAdminExecutor,
    ObligationExecutor,
    PaymentExecutor,
    PolicyExecutor,
    ProvisioningExecutor,
    QueryExecutor,
    RepoExecutor,
    SwapExecutor,
    TreasuryExecutor,
    WaitExecutor,
)
from ..validation import YAMLValidator, ServiceValidator
from ..core.output_store import OutputStore
from ..core.token_manager import TokenManager
from ..core.yaml_parser import YAMLParser
from ..utils.logger import get_logger


class YieldFabricRunner:
    """Main runner class for executing YieldFabric commands."""
    
    def __init__(self, config: Optional[YieldFabricConfig] = None):
        """
        Initialize runner.
        
        Args:
            config: Optional configuration object. If None, creates from environment.
        """
        self.config = config or YieldFabricConfig.from_env()
        self.logger = get_logger(debug=self.config.debug)
        
        # Initialize services
        self.auth_service = AuthService(self.config)
        self.payments_service = PaymentsService(self.config)
        self.agents_service = AgentsService(self.config)
        self.token_manager = TokenManager(self.auth_service, self.config)
        
        # Initialize core components
        self.output_store = OutputStore(debug=self.config.debug)
        self.yaml_parser = YAMLParser(debug=self.config.debug)
        
        # Initialize executors
        self.payment_executor = PaymentExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.obligation_executor = ObligationExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.query_executor = QueryExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.swap_executor = SwapExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.treasury_executor = TreasuryExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.group_admin_executor = GroupAdminExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.composed_executor = ComposedExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.wait_executor = WaitExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.repo_executor = RepoExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.assert_executor = AssertExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.policy_executor = PolicyExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        self.provisioning_executor = ProvisioningExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )
        # Deal-lifecycle executor — constructs its own AgentsService
        # (config.agents_service_url) for the dealFlow GraphQL on :3001.
        self.deal_executor = DealExecutor(
            self.auth_service, self.payments_service,
            self.output_store, self.config, self.token_manager
        )

        # Initialize validators
        self.yaml_validator = YAMLValidator(debug=self.config.debug)
        self.service_validator = ServiceValidator(
            self.auth_service, self.payments_service,
            debug=self.config.debug,
            agents_service=self.agents_service,
        )
    
    def execute_file(self, yaml_file: str) -> bool:
        """
        Execute all commands from a YAML file.
        
        Args:
            yaml_file: Path to YAML file
            
        Returns:
            True if all commands executed successfully
        """
        self.logger.cyan("🚀 Executing all commands from YAML file...")
        self.logger.separator()
        
        # Validate YAML structure
        is_valid, errors = self.yaml_validator.validate(yaml_file)
        if not is_valid:
            self.logger.error("❌ YAML validation failed:")
            for error in errors:
                self.logger.error(f"  - {error}")
            return False
        
        # Validate services
        if not self.service_validator.validate_services():
            return False
        
        # Parse commands
        commands = self.yaml_parser.parse_file(yaml_file)
        
        if not commands:
            self.logger.error("❌ No commands found in YAML file")
            return False
        
        self.logger.success(f"✅ Found {len(commands)} commands to execute")
        self.logger.separator()
        
        # Execute commands
        success_count = 0
        executed_count = 0
        total_count = len(commands)
        halted_command = None

        for i, command in enumerate(commands):
            self.logger.section(f"Command {i+1}/{total_count}: {command.name}")

            # Substitute variables in parameters
            substituted_params = self.output_store.substitute_params(command.parameters.to_dict())
            command.parameters = type(command.parameters).from_dict(substituted_params)

            # Substitute the user fields too, so a command can act as a
            # DYNAMIC group (e.g. `group: "Property Account $(cat …nonce)"` or a
            # `$cmd.field` ref). Literals (a plain email/password) contain no
            # `$`/`$(…)` and pass through unchanged, so this is a no-op for the
            # common case and only matters for delegation-by-dynamic-group.
            if command.user.id:
                command.user.id = self.output_store.substitute(command.user.id)
            if command.user.password:
                command.user.password = self.output_store.substitute(command.user.password)
            if command.user.group:
                command.user.group = self.output_store.substitute(command.user.group)

            # Execute command
            response = self.execute_command(command)
            executed_count += 1

            # Negative-test support: a command with `expect_failure: true` PASSES when it
            # fails/errors (optionally requiring `expect_error` as an error substring) and
            # FAILS if it unexpectedly succeeds. A correctly-behaving negative test is NOT
            # a break; an unexpected success / error-mismatch IS a break.
            command_broke = False
            if command.parameters.get("expect_failure"):
                actual_err = "" if response.success else " ".join(response.errors or [])
                expect_error = command.parameters.get("expect_error")
                if response.success:
                    self.logger.error(f"❌ {command.name}: expected failure but command SUCCEEDED")
                    command_broke = True
                elif expect_error and str(expect_error).lower() not in actual_err.lower():
                    self.logger.error(
                        f"❌ {command.name}: failed as expected but error mismatch — "
                        f"wanted '{expect_error}', got '{actual_err[:160]}'"
                    )
                    command_broke = True
                else:
                    self.logger.success(
                        f"✅ {command.name}: expected-failure satisfied ({actual_err[:120] or 'errored'})"
                    )
                    success_count += 1
            elif response.success:
                success_count += 1
            else:
                # Executors return their actionable diagnostics on the
                # CommandResponse. Surface them before the generic halt line;
                # otherwise a timeout (for example wait_for_accept_all) looks
                # like an unexplained failure even though the reason is known.
                for error in response.errors or []:
                    self.logger.error(f"    ❌ {error}")
                command_broke = True

            self.logger.separator()

            # Stop-on-break (default): halt at the first UNEXPECTED failure so the operator
            # can inspect on-chain / service state at the break point instead of cascading
            # through dependent steps (which then fail for misleading downstream reasons).
            # A correctly-behaving negative test does not trip this. Set
            # `continue_on_error: true` on the runner config to run the whole suite anyway.
            if command_broke and not getattr(self.config, "continue_on_error", False):
                halted_command = f"{i+1}/{total_count} '{command.name}'"
                self.logger.error(
                    f"🛑 Halting at command {halted_command} — it failed. "
                    f"({total_count - executed_count} later command(s) skipped; "
                    f"set continue_on_error: true to run them all)"
                )
                break

            # Wait between commands only if explicitly configured to
            # > 0. Default is 0 — callers should use `wait: true` on
            # commands for event-based sequencing instead of blind
            # delays. Kept non-zero behaviour for backward compat with
            # shell harness COMMAND_DELAY.
            if i + 1 < total_count and self.config.command_delay > 0:
                self.logger.waiting(self.config.command_delay)
                time.sleep(self.config.command_delay)

        # Summary
        self.logger.section("Execution Summary")
        self.logger.info(f"Total commands: {total_count}")
        self.logger.info(f"Executed: {executed_count}")
        self.logger.success(f"Successful: {success_count}")

        if success_count < executed_count:
            self.logger.error(f"Failed: {executed_count - success_count}")
        if halted_command is not None:
            self.logger.warning(
                f"⏹  Halted early at command {halted_command}; "
                f"{total_count - executed_count} command(s) not run"
            )

        if success_count == total_count:
            self.logger.success("✅ All commands executed successfully!")
            return True
        else:
            self.logger.warning("⚠️  Some commands failed")
            return False
    
    def execute_command(self, command: Command) -> CommandResponse:
        """
        Execute a single command.
        
        Args:
            command: Command to execute
            
        Returns:
            CommandResponse object
        """
        command_type = command.type.lower()
        
        # Route to appropriate executor. Keep this table in sync with the
        # shell harness `execute_commands.sh` dispatch so YAML files that
        # work in one work in the other.
        if command_type in [
            "deposit", "withdraw", "instant", "accept", "accept_all", "retry_message"
        ]:
            return self.payment_executor.execute(command)

        elif command_type in ["create_obligation", "accept_obligation",
                              "transfer_obligation", "cancel_obligation"]:
            return self.obligation_executor.execute(command)

        elif command_type in ["balance", "obligations", "list_groups"]:
            return self.query_executor.execute(command)

        elif command_type in ["create_swap", "create_obligation_swap",
                              "create_payment_swap", "complete_swap", "cancel_swap"]:
            return self.swap_executor.execute(command)

        elif command_type in ["repurchase_swap", "expire_collateral", "expire_swap",
                              "cancel_roll", "initiate_roll", "complete_roll"]:
            return self.repo_executor.execute(command)

        elif command_type == "assert":
            return self.assert_executor.execute(command)

        elif command_type in ["mint", "burn", "total_supply"]:
            return self.treasury_executor.execute(command)

        elif command_type in [
            "add_owner", "remove_owner", "add_member",
            "add_account_member", "remove_account_member",
            "get_account_owners", "get_account_members",
        ]:
            return self.group_admin_executor.execute(command)

        elif command_type == "composed_operation":
            return self.composed_executor.execute(command)

        elif command_type in [
            # Deal lifecycle + auto-pay (the dealFlow GraphQL on agents :3001).
            "propose_deal", "sign_deal", "activate_deal",
            "set_automation_key", "revoke_automation_key",
            "set_loan_collect_key", "revoke_loan_collect_key",
            "deal_automation_status", "deal_periods",
            # Drive a deferred on-chain step's /execute as its assignee
            # (one-time setup steps; recurring payments are scheduler-driven).
            "execute_step",
        ]:
            return self.deal_executor.execute(command)

        elif command_type in [
            "whoami",
            "add_data_policy",
            "approve_data_policy",
            "execute_under_policy",
            "remove_data_policy",
            "commit_oracle_document",
            "sign_oracle_document",
            "data_policies",
            "data_policy_approval",
        ]:
            return self.policy_executor.execute(command)

        elif command_type in [
            "wait_for_workflow",
            "wait_for_swap",
            "wait_for_message",
            "wait_for_signatures_cleared",
            "wait_for_accept_all",
            "sleep",
            "advance_chain_time",
            "mine_block",
        ]:
            return self.wait_executor.execute(command)

        elif command_type in [
            # Provisioning + compliance (creation + claims lifecycle + gating).
            "create_group", "deploy_account", "deploy_token", "deploy_class",
            "update_claim_requirements", "claim_requirements", "is_verified",
            "register_identity",
            "issue_claim", "accept_claim", "decline_claim", "revoke_claim",
            "reissue_claim", "issued_by_me", "issued_to_me",
        ]:
            return self.provisioning_executor.execute(command)

        else:
            self.logger.error(f"❌ Unknown command type: {command_type}")
            return CommandResponse.error_response(
                command.name, command.type,
                [f"Unknown command type: {command_type}"]
            )
    
    def show_status(self, yaml_file: str) -> bool:
        """
        Show status of commands and services.
        
        Args:
            yaml_file: Path to YAML file
            
        Returns:
            True if status check passed
        """
        self.logger.section("YieldFabric Status Check")
        
        # Check services
        self.logger.subsection("Service Status")
        services_ok = self.service_validator.validate_services()
        self.logger.separator()
        
        # Check YAML file
        self.logger.subsection("YAML File Status")
        is_valid, errors = self.yaml_validator.validate(yaml_file)
        
        if is_valid:
            commands = self.yaml_parser.parse_file(yaml_file)
            self.logger.success(f"✅ YAML file is valid")
            self.logger.info(f"   Found {len(commands)} commands")
            
            for i, command in enumerate(commands):
                self.logger.info(f"   {i+1}. {command.name} ({command.type})")
        else:
            self.logger.error("❌ YAML file has errors:")
            for error in errors:
                self.logger.error(f"  - {error}")
        
        self.logger.separator()
        
        return services_ok and is_valid
    
    def close(self):
        """Close service connections."""
        self.auth_service.close()
        self.payments_service.close()
        self.agents_service.close()
        self.deal_executor.agents_service.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
