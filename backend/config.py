import re
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict

_PK_RE     = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ZERO_PK   = "0x" + "0" * 64
_ZERO_ADDR = "0x" + "0" * 40
_LOCAL_RPC = ("127.0.0.1", "localhost")


class Settings(BaseSettings):
    # Blockchain
    somnia_rpc_url: str = "https://dream-rpc.somnia.network"
    somnia_chain_id: int = 50312

    # Agent wallets — must be set via .env (no usable defaults)
    # On localhost these are auto-loaded from somnia-local.json at startup.
    deployer_private_key: str = ""
    market_maker_pk: str = ""
    momentum_trader_pk: str = ""
    arbitrage_agent_pk: str = ""
    risk_manager_pk: str = ""
    noise_trader_pk: str = ""

    # Contract addresses — auto-loaded from somnia-local.json on localhost;
    # must be set via .env for testnet (printed by deploy.js)
    exchange_address: str = _ZERO_ADDR
    agent_registry_address: str = _ZERO_ADDR
    treasury_address: str = _ZERO_ADDR
    agent_coordinator_address: str = _ZERO_ADDR
    agent_token_address: str = _ZERO_ADDR
    quote_token_address: str = _ZERO_ADDR

    # Derived at startup from deployer_private_key — public address, safe to expose
    deployer_address: str = ""

    # Initial price shown before the first on-chain trade arrives
    initial_price: float = 3500.0

    # Somnia block time in milliseconds — used for latency display.
    # Set to 400 for testnet, 0 for local Hardhat (blocks are instant).
    somnia_block_ms: int = 0

    # CORS
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def validate_settings() -> None:
    """
    Called at startup. Exits with a clear error if required secrets are
    missing or invalid when connecting to a non-localhost chain.

    On localhost (Hardhat), missing PKs are allowed — _load_local_deployment()
    in the orchestrator fills them from somnia-local.json before use.
    """
    is_local = any(h in settings.somnia_rpc_url for h in _LOCAL_RPC)

    pk_fields = {
        "DEPLOYER_PRIVATE_KEY": settings.deployer_private_key,
        "MARKET_MAKER_PK":      settings.market_maker_pk,
        "MOMENTUM_TRADER_PK":   settings.momentum_trader_pk,
        "ARBITRAGE_AGENT_PK":   settings.arbitrage_agent_pk,
        "RISK_MANAGER_PK":      settings.risk_manager_pk,
        "NOISE_TRADER_PK":      settings.noise_trader_pk,
    }

    errors: list[str] = []
    for name, val in pk_fields.items():
        if not val:
            if not is_local:
                errors.append(f"  {name} is not set")
            # on localhost, somnia-local.json supplies it — skip
        elif not _PK_RE.match(val):
            errors.append(f"  {name} is not a valid 32-byte hex private key")
        elif val == _ZERO_PK:
            errors.append(f"  {name} is the all-zeros key — set a real private key")

    if errors:
        print("\n[config] Missing or invalid secrets:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print(
            "\nCopy backend/.env.example to backend/.env and fill in your values.\n",
            file=sys.stderr,
        )
        sys.exit(1)
