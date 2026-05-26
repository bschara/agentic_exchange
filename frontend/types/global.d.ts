interface EthereumProvider {
  request(args: { method: 'eth_requestAccounts' }): Promise<string[]>;
  request(args: { method: 'personal_sign'; params: [string, string] }): Promise<string>;
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
  on(event: string, listener: (...args: unknown[]) => void): void;
  removeListener(event: string, listener: (...args: unknown[]) => void): void;
  isMetaMask?: boolean;
}

interface Window {
  ethereum?: EthereumProvider;
}
