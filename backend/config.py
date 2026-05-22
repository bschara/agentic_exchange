from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Blockchain
    somnia_rpc_url: str = "https://dream-rpc.somnia.network"
    somnia_chain_id: int = 50312

    # Agent wallets
    deployer_private_key: str = "0x0000000000000000000000000000000000000000000000000000000000000001"
    market_maker_pk: str = "0x0000000000000000000000000000000000000000000000000000000000000001"
    momentum_trader_pk: str = "0x0000000000000000000000000000000000000000000000000000000000000002"
    arbitrage_agent_pk: str = "0x0000000000000000000000000000000000000000000000000000000000000003"
    risk_manager_pk: str = "0x0000000000000000000000000000000000000000000000000000000000000004"

    # Contract addresses
    exchange_address: str = "0x0000000000000000000000000000000000000000"
    agent_registry_address: str = "0x0000000000000000000000000000000000000000"
    treasury_address: str = "0x0000000000000000000000000000000000000000"
    agent_coordinator_address: str = "0x0000000000000000000000000000000000000000"

    # Initial price shown before the first on-chain trade arrives
    initial_price: float = 3500.0

    # Somnia block time in milliseconds — used for latency display.
    # Set to 400 for testnet, 0 for local Hardhat (blocks are instant).
    somnia_block_ms: int = 0

    # CORS
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
