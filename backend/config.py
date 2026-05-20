from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = "sk-ant-placeholder"
    claude_model: str = "claude-sonnet-4-6"

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

    # Agent behavior
    agent_loop_interval_seconds: float = 8.0
    max_llm_reasoning_tokens: int = 400
    tx_retry_attempts: int = 3

    # Market simulation
    initial_price: float = 100.0
    price_volatility: float = 0.025
    price_drift: float = 0.0002

    # Simulation mode (skips real blockchain txs)
    simulation_mode: bool = False

    # CORS
    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
