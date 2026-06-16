"""
GraphQL helper utilities
"""

from typing import Any, Dict, List, Optional


class GraphQLMutation:
    """Helper class for building GraphQL mutations."""
    
    DEPOSIT = """
    mutation Deposit($input: DepositInput!) {
        deposit(input: $input) {
            success
            message
            accountAddress
            depositResult
            messageId
            timestamp
        }
    }
    """
    
    WITHDRAW = """
    mutation Withdraw($input: WithdrawInput!) {
        withdraw(input: $input) {
            success
            message
            accountAddress
            withdrawResult
            messageId
            timestamp
        }
    }
    """
    
    INSTANT = """
    mutation Instant($input: InstantSendInput!) {
        instant(input: $input) {
            success
            message
            accountAddress
            destinationId
            idHash
            messageId
            paymentId
            sendResult
            timestamp
        }
    }
    """
    
    ACCEPT = """
    mutation Accept($input: AcceptInput!) {
        accept(input: $input) {
            success
            message
            accountAddress
            idHash
            acceptResult
            messageId
            timestamp
        }
    }
    """
    
    CREATE_OBLIGATION = """
    mutation CreateObligation($input: CreateObligationInput!) {
        createObligation(input: $input) {
            success
            message
            accountAddress
            obligationResult
            messageId
            contractId
            tokenId
            transactionId
            signature
            timestamp
            idHash
        }
    }
    """

    ACCEPT_OBLIGATION = """
    mutation AcceptObligation($input: AcceptObligationInput!) {
        acceptObligation(input: $input) {
            success
            message
            accountAddress
            obligationId
            acceptResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """
    
    TRANSFER_OBLIGATION = """
    mutation TransferObligation($input: TransferObligationInput!) {
        transferObligation(input: $input) {
            success
            message
            accountAddress
            obligationId
            destinationId
            destinationAddress
            transferResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """
    
    CANCEL_OBLIGATION = """
    mutation CancelObligation($input: CancelObligationInput!) {
        cancelObligation(input: $input) {
            success
            message
            accountAddress
            obligationId
            cancelResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """
    
    CREATE_OBLIGATION_SWAP = """
    mutation CreateObligationSwap($input: CreateObligationSwapInput!) {
        createObligationSwap(input: $input) {
            success
            message
            swapId
            accountAddress
            counterparty
            swapResult
            messageId
            timestamp
        }
    }
    """
    
    CREATE_PAYMENT_SWAP = """
    mutation CreatePaymentSwap($input: CreatePaymentSwapInput!) {
        createPaymentSwap(input: $input) {
            success
            message
            swapId
            accountAddress
            counterparty
            swapResult
            messageId
            timestamp
        }
    }
    """
    
    CREATE_SWAP = """
    mutation CreateSwap($input: CreateSwapInput!) {
        createSwap(input: $input) {
            success
            message
            swapId
            accountAddress
            counterparty
            swapResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """
    
    COMPLETE_SWAP = """
    mutation CompleteSwap($input: CompleteSwapInput!) {
        completeSwap(input: $input) {
            success
            message
            swapId
            accountAddress
            completeResult
            messageId
            timestamp
        }
    }
    """
    
    CANCEL_SWAP = """
    mutation CancelSwap($input: CancelSwapInput!) {
        cancelSwap(input: $input) {
            success
            message
            swapId
            accountAddress
            cancelResult
            messageId
            timestamp
        }
    }
    """

    REPURCHASE_SWAP = """
    mutation RepurchaseSwap($input: RepurchaseSwapInput!) {
        repurchaseSwap(input: $input) {
            success
            message
            accountAddress
            swapId
            repurchaseResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """

    EXPIRE_COLLATERAL = """
    mutation ExpireCollateral($input: ExpireCollateralInput!) {
        expireCollateral(input: $input) {
            success
            message
            accountAddress
            swapId
            expireResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """

    EXPIRE_SWAP = """
    mutation ExpireSwap($input: ExpireSwapInput!) {
        expireSwap(input: $input) {
            success
            message
            accountAddress
            swapId
            expireResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """

    CANCEL_ROLL = """
    mutation CancelRoll($input: CancelRollInput!) {
        cancelRoll(input: $input) {
            success
            message
            accountAddress
            newSwapId
            cancelResult
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """

    INITIATE_ROLL = """
    mutation InitiateRoll($input: RollRepoInput!) {
        initiateRoll(input: $input) {
            success
            message
            accountAddress
            oldSwapId
            newSwapId
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """

    COMPLETE_ROLL = """
    mutation CompleteRoll($input: CompleteRollInput!) {
        completeRoll(input: $input) {
            success
            message
            accountAddress
            newSwapId
            messageId
            transactionId
            signature
            timestamp
        }
    }
    """

    MINT = """
    mutation Mint($input: MintInput!) {
        mint(input: $input) {
            success
            message
            accountAddress
            mintResult
            messageId
            timestamp
        }
    }
    """
    
    BURN = """
    mutation Burn($input: BurnInput!) {
        burn(input: $input) {
            success
            message
            accountAddress
            burnResult
            messageId
            timestamp
        }
    }
    """

    ACCEPT_ALL = """
    mutation AcceptAll($input: AcceptAllInput!) {
        acceptAll(input: $input) {
            success
            message
            totalPayments
            acceptedCount
            failedCount
            acceptedPayments {
                paymentId
                amount
                messageId
                transactionId
            }
            failedPayments {
                paymentId
                amount
                error
            }
            timestamp
        }
    }
    """

    EXECUTE_COMPOSED_OPERATIONS = """
    mutation ExecuteComposedOperations($input: ComposedOperationInput!) {
        executeComposedOperations(input: $input) {
            success
            message
            messageId
            composedId
            accountAddress
            operationCount
            operationResults {
                operationType
                success
                message
                paymentId
                contractId
                amount
                idHash
                destinationId
                obligationId
                swapId
            }
        }
    }
    """
    
    @staticmethod
    def get_mutation(mutation_name: str) -> Optional[str]:
        """Get mutation string by name."""
        mutations = {
            'deposit': GraphQLMutation.DEPOSIT,
            'withdraw': GraphQLMutation.WITHDRAW,
            'instant': GraphQLMutation.INSTANT,
            'accept': GraphQLMutation.ACCEPT,
            'create_obligation': GraphQLMutation.CREATE_OBLIGATION,
            'accept_obligation': GraphQLMutation.ACCEPT_OBLIGATION,
            'transfer_obligation': GraphQLMutation.TRANSFER_OBLIGATION,
            'cancel_obligation': GraphQLMutation.CANCEL_OBLIGATION,
            'create_obligation_swap': GraphQLMutation.CREATE_OBLIGATION_SWAP,
            'create_payment_swap': GraphQLMutation.CREATE_PAYMENT_SWAP,
            'create_swap': GraphQLMutation.CREATE_SWAP,
            'complete_swap': GraphQLMutation.COMPLETE_SWAP,
            'cancel_swap': GraphQLMutation.CANCEL_SWAP,
            'repurchase_swap': GraphQLMutation.REPURCHASE_SWAP,
            'expire_collateral': GraphQLMutation.EXPIRE_COLLATERAL,
            'expire_swap': GraphQLMutation.EXPIRE_SWAP,
            'cancel_roll': GraphQLMutation.CANCEL_ROLL,
            'initiate_roll': GraphQLMutation.INITIATE_ROLL,
            'complete_roll': GraphQLMutation.COMPLETE_ROLL,
            'mint': GraphQLMutation.MINT,
            'burn': GraphQLMutation.BURN,
            'accept_all': GraphQLMutation.ACCEPT_ALL,
            'composed_operation': GraphQLMutation.EXECUTE_COMPOSED_OPERATIONS,
        }
        return mutations.get(mutation_name)
    
    @staticmethod
    def build_payload(mutation: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Build GraphQL payload."""
        return {
            'query': mutation,
            'variables': variables
        }


class DataPolicyGraphQL:
    """
    GraphQL operations for data-driven policies on group ConfidentialAccounts
    (the `pipelineGate` namespace). Strings mirror the frontend exactly —
    yieldfabric-app/src/components/workflowPipeline/api.ts — so a payload that
    works in the app works here.

    Lifecycle: addDataPolicy (register, MQ) → approveDataPolicy (record one
    reusable M-of-N approval signature, off-chain) → executeUnderPolicy (run a
    bound op under the approved policy, MQ) → removeDataPolicy (on-chain
    revocation, MQ; the settle hook flips the projection row to revoked and
    deletes the approval artifact — a revoked policy can never be approved or
    executed again, and its freed id may be re-registered).
    dataPolicies / dataPolicyApproval are reads; dataPolicies only returns
    revoked rows (flagged `revoked: true`) when `includeRevoked` is passed.
    """

    ADD_DATA_POLICY = """
    mutation AddDataPolicy($input: AddDataPolicyInput!) {
        pipelineGate {
            addDataPolicy(input: $input) {
                success
                message
                messageId
                policyId
            }
        }
    }
    """

    APPROVE_DATA_POLICY = """
    mutation ApproveDataPolicy($input: ApproveDataPolicyInput!) {
        pipelineGate {
            approveDataPolicy(input: $input) {
                success
                message
                signer
                collected
                approved
                registeredDigest
            }
        }
    }
    """

    EXECUTE_UNDER_POLICY = """
    mutation ExecuteUnderPolicy($input: ExecuteUnderPolicyInput!) {
        pipelineGate {
            executeUnderPolicy(input: $input) {
                success
                message
                messageId
                policyId
                collected
                approved
            }
        }
    }
    """

    REMOVE_DATA_POLICY = """
    mutation RemoveDataPolicy($input: RemoveDataPolicyInput!) {
        pipelineGate {
            removeDataPolicy(input: $input) {
                success
                message
                messageId
                policyId
            }
        }
    }
    """

    DATA_POLICY_APPROVAL = """
    query GetDataPolicyApproval($account: String!, $policyId: String!) {
        pipelineGate {
            dataPolicyApproval(account: $account, policyId: $policyId) {
                account
                policyId
                chainId
                registeredDigest
                minSignatories
                collected
                approved
                requiredSigners
                callerIds
            }
        }
    }
    """

    COMMIT_ORACLE_DOCUMENT = """
    mutation CommitOracleDocument($input: CommitOracleDocumentInput!) {
        pipelineGate {
            commitOracleDocument(input: $input) {
                success
                message
                messageId
                oracleAddress
                key
            }
        }
    }
    """

    # Compute the message an issuer EIP-191-signs to attest a document — the keccak of its
    # DataVerifier idHash. Pure read; the caller signs it (auth vault/sign) and passes the
    # signature to commitOracleDocument, where a policy's requiredSigner enforces the issuer.
    DOCUMENT_SIGNER_MESSAGE = """
    query DocumentSignerMessage($input: OracleFlowDocumentSignerMessageInput!) {
        oracleFlow {
            documentSignerMessage(input: $input) {
                message
            }
        }
    }
    """

    DATA_POLICIES = """
    query GetDataPolicies($walletId: String!, $includeRevoked: Boolean! = false) {
        pipelineGate {
            dataPolicies(walletId: $walletId, includeRevoked: $includeRevoked) {
                id
                walletId
                walletAddress
                policyId
                policyType
                start
                expiry
                maxUse
                minSignatories
                requiredSigners
                executors
                allowedOperations
                amountBounds { token lo hi }
                revoked
            }
        }
    }
    """


class GraphQLQuery:
    """Helper class for building GraphQL queries."""

    @staticmethod
    def build_payload(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build GraphQL query payload."""
        payload = {'query': query}
        if variables:
            payload['variables'] = variables
        return payload
