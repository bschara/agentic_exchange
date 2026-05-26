'use client';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const DEPLOYER_ADDRESS = (process.env.NEXT_PUBLIC_DEPLOYER_ADDRESS || '').toLowerCase();

export function isOwnerAddress(address: string): boolean {
  return !!DEPLOYER_ADDRESS && address.toLowerCase() === DEPLOYER_ADDRESS;
}

async function signAndPost(
  address: string,
  action: string,
  url: string,
  body?: Record<string, unknown>,
): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  if (!window.ethereum) return { ok: false, error: 'MetaMask not found' };

  const timestamp = Math.floor(Date.now() / 1000);
  const message = `admin:${action}:${timestamp}`;

  let signature: string;
  try {
    signature = await window.ethereum.request({
      method: 'personal_sign',
      params: [message, address],
    });
  } catch {
    return { ok: false, error: 'Signature rejected' };
  }

  try {
    const res = await fetch(`${API_URL}${url}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Admin-Sig': signature,
        'X-Admin-Message': message,
        'X-Admin-Address': address,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, error: data?.detail || `HTTP ${res.status}` };
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

export async function connectWallet(): Promise<string | null> {
  if (!window.ethereum) return null;
  try {
    const accounts = await window.ethereum.request({ method: 'eth_requestAccounts' });
    return accounts[0] ?? null;
  } catch {
    return null;
  }
}

export async function pauseAll(address: string) {
  return signAndPost(address, 'pause-all', '/agents/pause-all');
}

export async function resumeAll(address: string) {
  return signAndPost(address, 'resume-all', '/agents/resume-all');
}

export async function fundAll(address: string, amount: number) {
  return signAndPost(address, 'fund-all', '/agents/fund-all', { amount });
}
