import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH   = Path(__file__).parent.parent / "data" / "user_agents.json"


class UserAgentsDB:
    """
    JSON-backed cache of user agents discovered via on-chain AgentOwnerSet events.
    Source of truth is always the chain; this is a fast read-through cache.
    No private keys are stored here or anywhere else.
    """

    def __init__(self, db_path: Path = _DB_PATH):
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write([])

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> list[dict]:
        try:
            return json.loads(self._path.read_text())
        except Exception as e:
            logger.warning(f"UserAgentsDB: could not read {self._path}: {e}")
            return []

    def get_by_owner(self, owner_address: str) -> list[dict]:
        owner_lower = owner_address.lower()
        return [a for a in self.load() if a.get("owner_address", "").lower() == owner_lower]

    def get_by_id(self, agent_id: str) -> Optional[dict]:
        for a in self.load():
            if a.get("agent_id") == agent_id:
                return a
        return None

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_agent(self, record: dict) -> None:
        agents = self.load()
        agents.append(record)
        self._write(agents)

    def upsert_from_event(
        self,
        agent_id: str,
        owner_address: str,
        name: str,
        icon: str = "🤖",
        risk_level: int = 3,
    ) -> dict:
        """Insert or update a record from an on-chain AgentOwnerSet event."""
        agents = self.load()
        existing = next((a for a in agents if a["agent_id"] == agent_id), None)
        if existing:
            existing["owner_address"] = owner_address.lower()
            existing["name"]       = name
            existing["icon"]       = icon
            existing["risk_level"] = int(risk_level)
            self._write(agents)
            return existing
        record = {
            "agent_id":      agent_id,
            "owner_address": owner_address.lower(),
            "name":          name,
            "icon":          icon,
            "risk_level":    int(risk_level),
            "created_at":    int(time.time()),
        }
        agents.append(record)
        self._write(agents)
        logger.info(f"UserAgentsDB: cached user agent {agent_id} icon={icon} risk={risk_level} (owner={owner_address})")
        return record

    def update_agent(self, agent_id: str, updates: dict) -> bool:
        agents = self.load()
        for a in agents:
            if a["agent_id"] == agent_id:
                a.update(updates)
                self._write(agents)
                return True
        return False

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write(self, agents: list[dict]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(agents, indent=2))
        os.replace(tmp, self._path)
