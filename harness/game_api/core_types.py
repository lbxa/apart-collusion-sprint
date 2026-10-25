"""Compatibility names for generated API models and local startup metadata.

The HTTP contract is generated from Rust; no HTTP fields are maintained here.
Startup is a local subprocess protocol, separate from the versioned HTTP API.
"""

from .generated import (
    BalancesView as Balances,
    DeploymentView as Deployment,
    EpisodeView as Episode,
    HealthResponse as Health,
    JurorView as Juror,
    OperationView as Operation,
    ProtocolParameters as Parameters,
    ReceiptView as Receipt,
    RegisterEpisode as Registration,
    SettlementView as Settlement,
    TransactionView as Transaction,
    Verdict as Vote,
    WireModel,
)


class Startup(WireModel):
    api_url: str
    rpc_url: str
    deployment: Deployment
