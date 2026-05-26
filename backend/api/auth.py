import time

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import Header, HTTPException


def verify_admin_signature(signature: str, message: str, address: str, deployer_address: str) -> bool:
    """
    Verify that `message` was signed by `address` and that address is the deployer.
    Message format: "admin:<action>:<unix_timestamp>"
    Rejects signatures older than 5 minutes to prevent replay attacks.
    """
    parts = message.split(":")
    if len(parts) < 3 or parts[0] != "admin":
        return False
    try:
        ts = int(parts[-1])
        if abs(time.time() - ts) > 300:
            return False
    except ValueError:
        return False

    try:
        msg_hash = encode_defunct(text=message)
        recovered = Account.recover_message(msg_hash, signature=signature)
        return recovered.lower() == address.lower() == deployer_address.lower()
    except Exception:
        return False


async def admin_auth(
    x_admin_sig: str = Header(alias="X-Admin-Sig", default=""),
    x_admin_message: str = Header(alias="X-Admin-Message", default=""),
    x_admin_address: str = Header(alias="X-Admin-Address", default=""),
):
    """FastAPI dependency — validates wallet signature for owner-only routes."""
    from config import settings

    if not x_admin_sig or not x_admin_message or not x_admin_address:
        raise HTTPException(status_code=403, detail="Missing admin signature headers")

    if not settings.deployer_address:
        raise HTTPException(status_code=503, detail="Deployer address not configured")

    if not verify_admin_signature(x_admin_sig, x_admin_message, x_admin_address, settings.deployer_address):
        raise HTTPException(status_code=403, detail="Invalid or expired admin signature")
