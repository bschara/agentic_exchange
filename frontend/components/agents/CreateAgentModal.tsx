'use client';

import { useState } from 'react';
import { X, Bot, Coins, ChevronRight } from 'lucide-react';

const ICON_OPTIONS = ['🤖', '🦊', '🐺', '🦅', '🐉', '⚡', '🌊', '🔥', '🎯', '💎'];

const RISK_LABELS: Record<number, { label: string; color: string; desc: string }> = {
  1: { label: 'Safe',       color: 'text-emerald-400', desc: '40% base order size' },
  2: { label: 'Cautious',   color: 'text-cyan-400',    desc: '80% base order size' },
  3: { label: 'Balanced',   color: 'text-blue-400',    desc: '120% base order size' },
  4: { label: 'Bold',       color: 'text-orange-400',  desc: '160% base order size' },
  5: { label: 'Aggressive', color: 'text-red-400',     desc: '200% base order size' },
};

interface Props {
  onClose: () => void;
  onCreate: (name: string, systemPrompt: string, icon: string, riskLevel: number) => Promise<string>;
  onFund: (amount: number) => Promise<string>;
}

type Step = 'form' | 'funding' | 'done';

export function CreateAgentModal({ onClose, onCreate, onFund }: Props) {
  const [step, setStep]           = useState<Step>('form');
  const [name, setName]           = useState('');
  const [prompt, setPrompt]       = useState('');
  const [icon, setIcon]           = useState('🤖');
  const [riskLevel, setRiskLevel] = useState(3);
  const [fundAmount, setFundAmount] = useState('0.5');
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [txHash, setTxHash]       = useState<string | null>(null);

  const handleCreate = async () => {
    if (!name.trim() || !prompt.trim()) { setError('Name and strategy prompt are required.'); return; }
    setLoading(true);
    setError(null);
    try {
      const tx = await onCreate(name.trim(), prompt.trim(), icon, riskLevel);
      setTxHash(tx);
      setStep('funding');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message.slice(0, 120) : 'Transaction failed or rejected');
    } finally {
      setLoading(false);
    }
  };

  const handleFund = async () => {
    const amt = parseFloat(fundAmount) || 0;
    if (amt <= 0) { setError('Enter a valid STT amount.'); return; }
    setLoading(true);
    setError(null);
    try {
      await onFund(amt);
      setStep('done');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message.slice(0, 120) : 'Transaction failed or rejected');
    } finally {
      setLoading(false);
    }
  };

  const risk = RISK_LABELS[riskLevel];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-md bg-[#0d0d0d] border border-white/10 rounded-2xl p-6 shadow-2xl">
        <button onClick={onClose} className="absolute top-4 right-4 text-gray-600 hover:text-gray-400 transition-colors">
          <X className="w-4 h-4" />
        </button>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-5">
          <Bot className="w-5 h-5 text-cyan-400" />
          <span className="text-sm font-bold text-white">
            {step === 'form'    && 'Create Your Agent'}
            {step === 'funding' && 'Fund Your Agent'}
            {step === 'done'    && 'Agent Deployed!'}
          </span>
          <div className="flex items-center gap-1 ml-auto text-[10px] text-gray-600">
            <span className={step === 'form' ? 'text-cyan-400 font-bold' : 'text-gray-600'}>1. Define</span>
            <ChevronRight className="w-3 h-3" />
            <span className={step === 'funding' ? 'text-cyan-400 font-bold' : step === 'done' ? 'text-emerald-400' : 'text-gray-600'}>2. Fund</span>
            <ChevronRight className="w-3 h-3" />
            <span className={step === 'done' ? 'text-emerald-400 font-bold' : 'text-gray-600'}>3. Done</span>
          </div>
        </div>

        {/* ── Step 1: Form ── */}
        {step === 'form' && (
          <div className="flex flex-col gap-4">
            {/* Icon picker */}
            <div>
              <label className="block text-xs text-gray-500 mb-2 font-semibold uppercase tracking-widest">Agent Icon</label>
              <div className="flex gap-2 flex-wrap">
                {ICON_OPTIONS.map((e) => (
                  <button
                    key={e}
                    onClick={() => setIcon(e)}
                    className={`text-xl w-9 h-9 rounded-lg flex items-center justify-center transition-all ${
                      icon === e
                        ? 'bg-cyan-500/20 border border-cyan-500/60 scale-110'
                        : 'bg-white/5 border border-white/10 hover:bg-white/10'
                    }`}
                  >
                    {e}
                  </button>
                ))}
              </div>
            </div>

            {/* Agent Name */}
            <div>
              <label className="block text-xs text-gray-500 mb-1.5 font-semibold uppercase tracking-widest">Agent Name</label>
              <input
                type="text"
                placeholder="e.g. My Alpha Bot"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={30}
                className="w-full px-3 py-2 text-sm bg-black/40 border border-white/10 rounded-lg text-white placeholder-gray-700 focus:outline-none focus:border-cyan-500/50"
              />
            </div>

            {/* Risk Level */}
            <div>
              <label className="block text-xs text-gray-500 mb-2 font-semibold uppercase tracking-widest">
                Risk Level — <span className={`${risk.color} font-bold`}>{risk.label}</span>
                <span className="text-gray-700 ml-2 normal-case font-normal">({risk.desc})</span>
              </label>
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={riskLevel}
                onChange={(e) => setRiskLevel(parseInt(e.target.value))}
                className="w-full accent-cyan-400"
              />
              <div className="flex justify-between text-[10px] text-gray-700 mt-1 px-0.5">
                <span>Safe</span><span>Cautious</span><span>Balanced</span><span>Bold</span><span>Aggressive</span>
              </div>
            </div>

            {/* Strategy Prompt */}
            <div>
              <label className="block text-xs text-gray-500 mb-1.5 font-semibold uppercase tracking-widest">Strategy Prompt</label>
              <textarea
                rows={5}
                placeholder="e.g. You are a contrarian trading agent. When other agents BUY, you SELL. When they SELL, you BUY. Respond with exactly one word: BUY, SELL, or HOLD."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                className="w-full px-3 py-2 text-sm bg-black/40 border border-white/10 rounded-lg text-white placeholder-gray-700 focus:outline-none focus:border-cyan-500/50 resize-none font-mono"
              />
              <p className="text-[10px] text-gray-700 mt-1">
                Stored on-chain in <code className="text-gray-600">AgentCoordinator.systemPrompts</code>. Used verbatim by Somnia&apos;s LLM validators.
              </p>
            </div>

            {error && <p className="text-[11px] text-red-400">{error}</p>}
            <button
              onClick={handleCreate}
              disabled={loading || !name.trim() || !prompt.trim()}
              className="w-full py-2.5 text-sm font-bold bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 rounded-lg hover:bg-cyan-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {loading ? 'Waiting for MetaMask…' : 'Deploy Agent On-Chain →'}
            </button>
          </div>
        )}

        {/* ── Step 2: Fund ── */}
        {step === 'funding' && (
          <div className="flex flex-col gap-4">
            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-300">
              Agent deployed! Fund it with STT so it can pay for Somnia LLM inference.
            </div>
            {txHash && <p className="text-[10px] font-mono text-gray-600 break-all">Create tx: {txHash.slice(0, 18)}…</p>}
            <div>
              <label className="block text-xs text-gray-500 mb-1.5 font-semibold uppercase tracking-widest">Funding Amount (STT)</label>
              <div className="flex gap-2">
                <input
                  type="number"
                  min="0.01"
                  step="0.1"
                  value={fundAmount}
                  onChange={(e) => setFundAmount(e.target.value)}
                  className="flex-1 px-3 py-2 text-sm bg-black/40 border border-white/10 rounded-lg text-white focus:outline-none focus:border-cyan-500/50 font-mono"
                />
                <span className="flex items-center text-sm text-gray-500">STT</span>
              </div>
              <p className="text-[10px] text-gray-700 mt-1">Each decision cycle costs ~2× platform deposit. 0.5 STT ≈ several hundred cycles.</p>
            </div>
            {error && <p className="text-[11px] text-red-400">{error}</p>}
            <div className="flex gap-2">
              <button onClick={() => setStep('done')} className="flex-1 py-2.5 text-sm font-bold border border-white/10 text-gray-500 rounded-lg hover:border-white/20 hover:text-gray-400 transition-all">
                Skip for now
              </button>
              <button
                onClick={handleFund}
                disabled={loading}
                className="flex-1 py-2.5 text-sm font-bold bg-blue-500/20 border border-blue-500/40 text-blue-300 rounded-lg hover:bg-blue-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-1.5"
              >
                <Coins className="w-4 h-4" />
                {loading ? 'Waiting for MetaMask…' : 'Fund Agent →'}
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Done ── */}
        {step === 'done' && (
          <div className="flex flex-col items-center gap-4 py-4">
            <div className="text-5xl">{icon}</div>
            <p className="text-white font-bold text-center">{name} is live!</p>
            <p className="text-xs text-gray-500 text-center">
              The backend will detect your agent on-chain and start the trading loop automatically (~5s).
            </p>
            <button onClick={onClose} className="mt-2 px-6 py-2.5 text-sm font-bold bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 rounded-lg hover:bg-cyan-500/30 transition-all">
              View My Agents
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
