import React, { useState } from 'react';
import {
  Settings,
  Cpu,
  Key,
  Sparkles,
  CheckCircle2,
  RefreshCw,
  Save,
  Zap,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const SettingsView: React.FC = () => {
  const { settings, setSettings, backendStatus, refreshBackendStatus, showToast } = useApp();
  const [geminiKey, setGeminiKey] = useState(settings.geminiApiKey);
  const [openaiKey, setOpenaiKey] = useState(settings.openaiApiKey);
  const [isProbing, setIsProbing] = useState(false);

  const handleSave = () => {
    // Keep API keys in memory only — never stored to localStorage
    setSettings((prev) => ({
      ...prev,
      geminiApiKey: geminiKey,
      openaiApiKey: openaiKey,
    }));
    showToast('Preferences updated! (API keys retained in memory only)');
  };

  const handleProbe = async () => {
    setIsProbing(true);
    await refreshBackendStatus();
    setIsProbing(false);
    showToast('Hardware engine probe complete');
  };

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-8">
      <div>
        <h2 className="text-2xl font-extrabold text-white flex items-center gap-2.5">
          <Settings className="w-6 h-6 text-purple-400" />
          Application Settings
        </h2>
        <p className="text-xs text-slate-400 mt-1">
          Configure offline speech recognition models, hardware acceleration, and optional AI enhancement
        </p>
      </div>

      {/* Hardware & Backend Status Card */}
      <div className="p-6 rounded-3xl bg-[#12141c] border border-[#212638] shadow-xl space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Cpu className="w-5 h-5 text-cyan-400" />
            <h3 className="text-sm font-bold text-white">Engine Diagnostics & Hardware Status</h3>
          </div>
          <button
            onClick={handleProbe}
            disabled={isProbing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#191d2c] hover:bg-[#23283c] text-slate-300 text-xs font-semibold border border-[#2b3349] transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isProbing ? 'animate-spin' : ''}`} />
            <span>Probe Engine</span>
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          <div className="p-4 rounded-2xl bg-[#0b0c10] border border-[#1b1f2e] space-y-1">
            <span className="text-[11px] text-slate-400 block font-medium">FastAPI Backend</span>
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  backendStatus.online ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'
                }`}
              />
              <span className="text-xs font-bold text-white truncate">
                {backendStatus.online ? `Online (${backendStatus.pythonVersion})` : 'Offline (Port 8000)'}
              </span>
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-[#0b0c10] border border-[#1b1f2e] space-y-1">
            <span className="text-[11px] text-slate-400 block font-medium">Video Encoder</span>
            <div className="flex items-center gap-2">
              <Zap className="w-3.5 h-3.5 text-amber-400" />
              <span className="text-xs font-bold text-slate-200 truncate">
                {backendStatus.gpuEncoder || 'Hardware probing...'}
              </span>
            </div>
          </div>

          <div className="p-4 rounded-2xl bg-[#0b0c10] border border-[#1b1f2e] space-y-1">
            <span className="text-[11px] text-slate-400 block font-medium">FFmpeg & FFprobe</span>
            <div className="flex items-center gap-2">
              <CheckCircle2
                className={`w-3.5 h-3.5 ${
                  backendStatus.ffmpeg ? 'text-emerald-400' : 'text-amber-400'
                }`}
              />
              <span className="text-xs font-bold text-slate-200">
                {backendStatus.ffmpeg ? 'Installed on PATH' : 'FFmpeg Not on PATH'}
              </span>
            </div>
          </div>
        </div>

        {!backendStatus.ffmpeg && backendStatus.online && (
          <div className="p-3 rounded-xl bg-amber-950/30 border border-amber-800/40 text-xs text-amber-300 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-amber-400 mt-0.5" />
            <span>
              FFmpeg was not detected on system PATH. Install FFmpeg 5.0+ and add it to your PATH to enable hardware video composition and encoding.
            </span>
          </div>
        )}
      </div>

      {/* Model & Processing Settings */}
      <div className="p-6 rounded-3xl bg-[#12141c] border border-[#212638] shadow-xl space-y-5">
        <div className="flex items-center gap-2.5">
          <Sparkles className="w-5 h-5 text-purple-400" />
          <h3 className="text-sm font-bold text-white">Whisper Speech Recognition & Layout</h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Whisper Model Variant
            </label>
            <select
              value={settings.whisperModel}
              onChange={(e) =>
                setSettings((prev) => ({
                  ...prev,
                  whisperModel: e.target.value as any,
                }))
              }
              className="w-full px-3 py-2.5 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-white focus:outline-none focus:border-purple-500"
            >
              <option value="tiny">Tiny (~75 MB - Ultra Fast, English)</option>
              <option value="base">Base (~145 MB - Fast Default, English)</option>
              <option value="small">Small (~480 MB - Recommended for Multilingual)</option>
              <option value="medium">Medium (~1.5 GB - High Multilingual Accuracy)</option>
              <option value="large-v3">Large-v3 (~3.0 GB - Best Non-English Accuracy)</option>
            </select>
            <p className="text-[11px] text-slate-400 mt-1">
              Use Small, Medium, or Large-v3 for Malayalam, Hindi, Tamil, Arabic, and non-Latin scripts.
            </p>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5">
              Computation Device
            </label>
            <select
              value={settings.device}
              onChange={(e) =>
                setSettings((prev) => ({
                  ...prev,
                  device: e.target.value as any,
                }))
              }
              className="w-full px-3 py-2.5 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-white focus:outline-none focus:border-purple-500"
            >
              <option value="cpu">CPU (Universal Fallback)</option>
              <option value="cuda">CUDA (NVIDIA Hardware Acceleration)</option>
            </select>
            <p className="text-[11px] text-slate-400 mt-1">
              {backendStatus.whisperHardware?.backend_note || 'Uses CPU int8 quantization by default.'}
            </p>
          </div>
        </div>

        <div className="space-y-2 pt-2 border-t border-[#1c2030]">
          <label className="block text-xs font-semibold text-slate-300">
            Transcription Performance Profile
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
            {([
              {
                id: 'speed',
                label: 'Speed',
                desc: 'Batched beam=1, best_of=1. Fastest on long videos; slight accuracy trade-off on noisy/non-English audio.',
              },
              {
                id: 'balanced',
                label: 'Balanced (Default)',
                desc: 'Batched beam=1 for English; unbatched beam=2 for non-English to protect multilingual quality.',
              },
              {
                id: 'accuracy',
                label: 'Accuracy',
                desc: 'Unbatched beam=3, best_of=2 with multi-temperature fallback. Best fidelity, slowest runtime.',
              },
            ] as const).map((prof) => {
              const active = (settings.transcriptionProfile || 'balanced') === prof.id;
              return (
                <button
                  key={prof.id}
                  type="button"
                  onClick={() =>
                    setSettings((prev) => ({
                      ...prev,
                      transcriptionProfile: prof.id,
                    }))
                  }
                  className={`p-3 rounded-xl border text-left transition-all ${
                    active
                      ? 'bg-purple-600/15 border-purple-500 text-white'
                      : 'bg-[#0b0c10] border-[#23283b] text-slate-300 hover:border-slate-600'
                  }`}
                >
                  <div className="text-xs font-bold">{prof.label}</div>
                  <div className="text-[10px] text-slate-400 mt-1 leading-relaxed">{prof.desc}</div>
                </button>
              );
            })}
          </div>
        </div>

        <div className="pt-2 border-t border-[#1c2030] flex items-center justify-between">
          <div>
            <span className="text-xs font-bold text-slate-200">Default Video Composition</span>
            <p className="text-[11px] text-slate-400">
              Facecam Top (37.5%) + Gameplay Bottom (62.5% ~3:4 ratio)
            </p>
          </div>
          <span className="text-xs px-2.5 py-1 rounded-md bg-purple-500/20 text-purple-300 border border-purple-500/30 font-semibold">
            Active
          </span>
        </div>
      </div>

      {/* Optional AI API Keys */}
      <div className="p-6 rounded-3xl bg-[#12141c] border border-[#212638] shadow-xl space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Key className="w-5 h-5 text-amber-400" />
            <h3 className="text-sm font-bold text-white">Optional AI Enhancement (Google Gemini & OpenAI)</h3>
          </div>
          <span className="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-bold uppercase">
            Optional
          </span>
        </div>

        <p className="text-xs text-slate-400 leading-relaxed">
          ViralClip AI operates <strong className="text-white">100% offline</strong> using local rule-based energy spike and laughter detection. You can optionally provide an API key to enhance moment ranking and auto-generate click-worthy YouTube titles.
        </p>

        <div className="p-3 rounded-xl bg-purple-950/20 border border-purple-800/30 flex items-center gap-2 text-xs text-purple-300">
          <ShieldCheck className="w-4 h-4 text-purple-400 shrink-0" />
          <span>Security Guarantee: API keys are strictly held in-memory and never stored in localStorage.</span>
        </div>

        <div className="space-y-3 pt-2">
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              Google Gemini API Key
            </label>
            <input
              type="password"
              value={geminiKey}
              onChange={(e) => setGeminiKey(e.target.value)}
              placeholder="AIzaSy..."
              className="w-full px-4 py-2.5 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs text-white placeholder-slate-600 focus:outline-none focus:border-purple-500"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              OpenAI API Key
            </label>
            <input
              type="password"
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
              placeholder="sk-..."
              className="w-full px-4 py-2.5 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs text-white placeholder-slate-600 focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>

        <div className="pt-3 flex justify-end">
          <button
            onClick={handleSave}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold shadow-md transition-all"
          >
            <Save className="w-4 h-4" />
            <span>Save Preferences</span>
          </button>
        </div>
      </div>
    </div>
  );
};
