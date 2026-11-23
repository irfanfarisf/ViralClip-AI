import React, { useState, useEffect } from 'react';
import {
  Type,
  Sparkles,
  MoveVertical,
  Check,
  Edit3,
  Save,
  Palette,
  Layers,
  Play,
  ShieldCheck,
  Globe,
  Languages,
  Loader2,
  RotateCcw,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { updateClipOnBackend } from '../../services/api';
import { SUPPORTED_LANGUAGES, type SubtitlePreset, type SubtitleAnimation } from '../../types';

export const SubtitleControls: React.FC = () => {
  const {
    subtitleStyle,
    setSubtitleStyle,
    activeHighlight,
    activeProject,
    saveTranscriptCorrection,
    translateCurrentClipSubtitles,
    showToast,
  } = useApp();

  const [activeSubTab, setActiveSubTab] = useState<'style' | 'translate' | 'transcript'>('style');
  const detectedLang = activeProject?.detectedLanguage || 'auto';
  const [targetLanguage, setTargetLanguage] = useState<string>(() => {
    if (subtitleStyle.isTranslated && subtitleStyle.subtitleLanguage && subtitleStyle.subtitleLanguage !== 'original') {
      return subtitleStyle.subtitleLanguage;
    }
    return detectedLang === 'en' ? 'ml' : 'en';
  });
  const [isTranslating, setIsTranslating] = useState(false);
  const [translationError, setTranslationError] = useState<string | null>(null);
  const [isSavingTranscript, setIsSavingTranscript] = useState(false);

  useEffect(() => {
    if (subtitleStyle.isTranslated && subtitleStyle.subtitleLanguage && subtitleStyle.subtitleLanguage !== 'original') {
      setTargetLanguage(subtitleStyle.subtitleLanguage);
    } else if (detectedLang === 'en' && targetLanguage === 'en') {
      setTargetLanguage('ml');
    }
  }, [activeHighlight?.id, subtitleStyle.isTranslated, subtitleStyle.subtitleLanguage, detectedLang]);

  // Filter project transcript segments covering the active highlight clip
  const clipSegments = (activeProject?.transcripts || []).filter((s) => {
    if (!activeHighlight) return false;
    return s.end >= activeHighlight.startTime && s.start <= activeHighlight.endTime;
  });

  const [editedTexts, setEditedTexts] = useState<Record<string, string>>({});

  const presets: {
    id: SubtitlePreset;
    label: string;
    desc: string;
    text: string;
    highlight: string;
    bg: string;
    hasBg: boolean;
    animation: SubtitleAnimation;
  }[] = [
    {
      id: 'yellow_highlight',
      label: 'Yellow Highlight',
      desc: 'Bold white text + viral yellow active word (Default)',
      text: '#FFFFFF',
      highlight: '#FFD700',
      bg: 'rgba(0,0,0,0.65)',
      hasBg: false,
      animation: 'pop',
    },
    {
      id: 'classic_white',
      label: 'Classic White',
      desc: 'Clean bold white text with subtle golden pop',
      text: '#FFFFFF',
      highlight: '#FFF066',
      bg: 'transparent',
      hasBg: false,
      animation: 'pop',
    },
    {
      id: 'bold_creator',
      label: 'Bold Creator Style',
      desc: 'High-contrast uppercase with dark boxed backing',
      text: '#FFFFFF',
      highlight: '#22C55E',
      bg: '#000000',
      hasBg: true,
      animation: 'bounce',
    },
    {
      id: 'neon_glow',
      label: 'Neon Glow',
      desc: 'Cyberpunk electric cyan + neon magenta glow',
      text: '#00F0FF',
      highlight: '#D946EF',
      bg: 'rgba(15,10,30,0.8)',
      hasBg: false,
      animation: 'scale_glow',
    },
    {
      id: 'minimal_captions',
      label: 'Minimal Captions',
      desc: 'Soft slate with sky blue highlight and subtle fade',
      text: '#F8FAFC',
      highlight: '#38BDF8',
      bg: 'transparent',
      hasBg: false,
      animation: 'fade',
    },
  ];

  const handleApplyPreset = (presetId: SubtitlePreset) => {
    const p = presets.find((item) => item.id === presetId);
    if (!p) return;
    const isIndic =
      subtitleStyle.subtitleLanguage === 'ml' ||
      subtitleStyle.subtitleLanguage === 'hi' ||
      subtitleStyle.subtitleLanguage === 'ta' ||
      subtitleStyle.subtitleLanguage === 'te' ||
      subtitleStyle.subtitleLanguage === 'kn' ||
      activeProject?.detectedLanguage === 'ml' ||
      activeProject?.detectedLanguage === 'hi';
    const resolvedFont = isIndic ? 'Nirmala UI' : presetId === 'bold_creator' ? 'Impact' : 'Montserrat';

    setSubtitleStyle((prev) => ({
      ...prev,
      preset: presetId,
      textColor: p.text,
      highlightColor: p.highlight,
      backgroundColor: p.bg,
      hasBackground: p.hasBg,
      animation: p.animation,
      fontFamily: resolvedFont,
      fontSize: presetId === 'bold_creator' ? 'xl' : 'lg',
      isUppercase: presetId !== 'minimal_captions' && !isIndic,
    }));
    showToast(`Applied "${p.label}" subtitle preset`);
  };

  const handleTranslateSubtitles = async () => {
    if (isTranslating) return;
    try {
      setIsTranslating(true);
      setTranslationError(null);
      await translateCurrentClipSubtitles(targetLanguage);
    } catch (err: any) {
      setTranslationError(err?.message || 'Subtitle translation failed. Please check your connection and retry.');
    } finally {
      setIsTranslating(false);
    }
  };

  const handleResetSubtitles = async () => {
    if (isTranslating) return;
    try {
      setIsTranslating(true);
      setTranslationError(null);
      await translateCurrentClipSubtitles('original');
    } catch (err: any) {
      setTranslationError(err?.message || 'Failed to restore original subtitles.');
    } finally {
      setIsTranslating(false);
    }
  };

  const handleSaveTranscript = async () => {
    if (!activeHighlight) return;
    try {
      setIsSavingTranscript(true);
      const updates = clipSegments.map((s) => ({
        id: s.id,
        start: s.start,
        end: s.end,
        text: editedTexts[s.id] !== undefined ? editedTexts[s.id] : s.text,
      }));
      await saveTranscriptCorrection(activeHighlight.id, updates);
    } catch {
      // error handled in context toast
    } finally {
      setIsSavingTranscript(false);
    }
  };

  const subtitlesEnabled = subtitleStyle.enabled !== false;

  const handleToggleSubtitlesVisibility = () => {
    const nextEnabled = !subtitlesEnabled;
    setSubtitleStyle((prev) => ({ ...prev, enabled: nextEnabled }));
    if (activeProject && activeHighlight && !activeProject.isDemo) {
      updateClipOnBackend(activeHighlight.id, {
        subtitle_style: {
          ...(activeHighlight.subtitleStyle || {}),
          enabled: nextEnabled,
        },
      }).catch(() => {});
    }
    showToast(nextEnabled ? 'Subtitles enabled for preview & export' : 'Subtitles disabled for preview & export');
  };

  return (
    <div className="space-y-6">
      {/* Independent Subtitle Visibility Toggle (Preview & Export) */}
      <div className="p-3.5 rounded-2xl bg-[#12141c] border border-[#212638] flex items-center justify-between gap-3">
        <div>
          <span className="text-xs font-bold text-white flex items-center gap-2">
            <Type className="w-4 h-4 text-purple-400" />
            <span>Show &amp; Burn Subtitles</span>
            <span
              className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                subtitlesEnabled
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                  : 'bg-slate-800 text-slate-400 border-slate-700'
              }`}
            >
              {subtitlesEnabled ? 'ON' : 'OFF'}
            </span>
          </span>
          <p className="text-[11px] text-slate-400 mt-0.5">
            {subtitlesEnabled
              ? 'Subtitles are visible in preview and burned into exported clips.'
              : 'Subtitles are hidden in preview and excluded from export. Transcription & translations stay saved.'}
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={subtitlesEnabled}
          onClick={handleToggleSubtitlesVisibility}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
            subtitlesEnabled ? 'bg-purple-600' : 'bg-slate-700'
          }`}
        >
          <span
            className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${
              subtitlesEnabled ? 'translate-x-5' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      {/* Tab Switcher: Styling vs Multilingual Translation vs Manual Transcript */}
      <div className="flex items-center gap-1.5 p-1.5 rounded-2xl bg-[#12141c] border border-[#212638]">
        <button
          onClick={() => setActiveSubTab('style')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-bold transition-all ${
            activeSubTab === 'style'
              ? 'bg-purple-600 text-white shadow-md'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Sparkles className="w-4 h-4" />
          <span>Style & Presets</span>
        </button>
        <button
          onClick={() => setActiveSubTab('translate')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-bold transition-all relative ${
            activeSubTab === 'translate'
              ? 'bg-purple-600 text-white shadow-md'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Languages className="w-4 h-4" />
          <span>Translate</span>
          {subtitleStyle.isTranslated && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          )}
        </button>
        <button
          onClick={() => setActiveSubTab('transcript')}
          className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-xs font-bold transition-all ${
            activeSubTab === 'transcript'
              ? 'bg-purple-600 text-white shadow-md'
              : 'text-slate-400 hover:text-white'
          }`}
        >
          <Edit3 className="w-4 h-4" />
          <span>Edit Words</span>
          {clipSegments.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.2 bg-purple-900/80 rounded font-normal">
              {clipSegments.length}
            </span>
          )}
        </button>
      </div>

      {activeSubTab === 'style' ? (
        <>
          {/* Subtitle Presets (5 Requirements) */}
          <div className="space-y-3">
            <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-purple-400" />
              Word-by-Word Animated Presets
            </label>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {presets.map((p) => {
                const isSelected = subtitleStyle.preset === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => handleApplyPreset(p.id)}
                    className={`p-3 rounded-2xl border text-left transition-all flex items-center justify-between ${
                      isSelected
                        ? 'bg-purple-600/15 border-purple-500 shadow-md shadow-purple-950/20'
                        : 'bg-[#12141c] border-[#212638] hover:border-slate-700'
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-bold text-white block">{p.label}</span>
                        {p.id === 'yellow_highlight' && (
                          <span className="text-[9px] font-bold px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 uppercase">
                            Default
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-slate-400">{p.desc}</p>
                      <div className="pt-1 flex items-center gap-2">
                        <span
                          className="text-[11px] font-black uppercase tracking-wider px-2 py-0.5 rounded shadow-sm"
                          style={{
                            color: p.text,
                            backgroundColor: p.hasBg ? p.bg : '#151825',
                            border: '1px solid rgba(255,255,255,0.1)',
                          }}
                        >
                          VIRAL <span style={{ color: p.highlight }}>WORD</span> POP
                        </span>
                      </div>
                    </div>
                    {isSelected && <Check className="w-4 h-4 text-purple-400 shrink-0 ml-2" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Typography, Color & Animation Settings */}
          <div className="p-4 rounded-2xl bg-[#12141c] border border-[#212638] space-y-4">
            <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
              <Type className="w-3.5 h-3.5 text-cyan-400" />
              Typography & Animation Customization
            </span>

            {/* Font Family & Size */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Font Family</label>
                <select
                  value={subtitleStyle.fontFamily}
                  onChange={(e) =>
                    setSubtitleStyle((prev) => ({
                      ...prev,
                      fontFamily: e.target.value as any,
                    }))
                  }
                  className="w-full px-3 py-2 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-white focus:outline-none focus:border-purple-500"
                >
                  <option value="Nirmala UI">Nirmala UI (Malayalam & Indic Scripts)</option>
                  <option value="Montserrat">Montserrat Black</option>
                  <option value="Inter">Inter Bold</option>
                  <option value="Bebas Neue">Bebas Neue Condensed</option>
                  <option value="Impact">Impact Heavy</option>
                  <option value="Arial">Arial Bold</option>
                  <option value="Segoe UI">Segoe UI (Arabic / Latin)</option>
                  <option value="Malgun Gothic">Malgun Gothic (Korean)</option>
                  <option value="MS Gothic">MS Gothic (Japanese)</option>
                  <option value="Roboto">Roboto Bold</option>
                </select>
              </div>

              <div>
                <label className="block text-[11px] text-slate-400 mb-1">Font Size</label>
                <select
                  value={subtitleStyle.fontSize}
                  onChange={(e) =>
                    setSubtitleStyle((prev) => ({
                      ...prev,
                      fontSize: e.target.value as any,
                    }))
                  }
                  className="w-full px-3 py-2 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-white focus:outline-none focus:border-purple-500"
                >
                  <option value="sm">Small (62pt / 14px)</option>
                  <option value="md">Medium (72pt / 18px)</option>
                  <option value="lg">Large (82pt / 22px - Recommended)</option>
                  <option value="xl">Extra Large (92pt / 26px)</option>
                </select>
              </div>
            </div>

            {/* Color Selectors: Text Color & Highlight Color */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-[11px] text-slate-400 mb-1 flex items-center gap-1">
                  <Palette className="w-3 h-3 text-purple-400" />
                  Base Text Color
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={subtitleStyle.textColor}
                    onChange={(e) =>
                      setSubtitleStyle((prev) => ({ ...prev, textColor: e.target.value }))
                    }
                    className="w-8 h-8 rounded-lg cursor-pointer bg-transparent border border-[#2a2f45]"
                  />
                  <input
                    type="text"
                    value={subtitleStyle.textColor}
                    onChange={(e) =>
                      setSubtitleStyle((prev) => ({ ...prev, textColor: e.target.value }))
                    }
                    className="flex-1 px-2.5 py-1.5 rounded-lg bg-[#0b0c10] border border-[#23283b] text-xs font-mono text-white focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] text-slate-400 mb-1 flex items-center gap-1">
                  <Sparkles className="w-3 h-3 text-amber-400" />
                  Active Word Highlight Color
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={subtitleStyle.highlightColor}
                    onChange={(e) =>
                      setSubtitleStyle((prev) => ({ ...prev, highlightColor: e.target.value }))
                    }
                    className="w-8 h-8 rounded-lg cursor-pointer bg-transparent border border-[#2a2f45]"
                  />
                  <input
                    type="text"
                    value={subtitleStyle.highlightColor}
                    onChange={(e) =>
                      setSubtitleStyle((prev) => ({ ...prev, highlightColor: e.target.value }))
                    }
                    className="flex-1 px-2.5 py-1.5 rounded-lg bg-[#0b0c10] border border-[#23283b] text-xs font-mono text-white focus:outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Animation Selector */}
            <div>
              <label className="block text-[11px] text-slate-400 mb-1 flex items-center gap-1">
                <Play className="w-3 h-3 text-cyan-400" />
                Active Word Animation Effect
              </label>
              <select
                value={subtitleStyle.animation || 'pop'}
                onChange={(e) =>
                  setSubtitleStyle((prev) => ({
                    ...prev,
                    animation: e.target.value as SubtitleAnimation,
                  }))
                }
                className="w-full px-3 py-2 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-white focus:outline-none focus:border-purple-500"
              >
                <option value="pop">Smooth Pop-in (Scale 120% → 106% Ease)</option>
                <option value="bounce">Energetic Bounce (Scale 130% → 96% → 105%)</option>
                <option value="scale_glow">Scale & Glow (Continuous Active Scale)</option>
                <option value="fade">Smooth Fade Transition (Alpha Ease)</option>
                <option value="none">Classic Karaoke (Color change only)</option>
              </select>
            </div>

            {/* Vertical Position Slider with Safe Margins Notice */}
            <div className="space-y-1.5 pt-1">
              <div className="flex justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <MoveVertical className="w-3 h-3 text-purple-400" />
                  Vertical Position (% from Top)
                </span>
                <span className="font-mono text-slate-300">{subtitleStyle.positionY}%</span>
              </div>
              <input
                type="range"
                min="20"
                max="85"
                step="1"
                value={subtitleStyle.positionY}
                onChange={(e) =>
                  setSubtitleStyle((prev) => ({
                    ...prev,
                    positionY: parseInt(e.target.value),
                  }))
                }
                className="w-full accent-purple-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
              />
              <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>Top Safe Zone (20%)</span>
                <span className="text-purple-300 font-semibold">Recommended: 74% - 80%</span>
                <span>Bottom Safe Zone (85%)</span>
              </div>
            </div>

            {/* Outline & Background Settings */}
            <div className="pt-2 border-t border-[#1e2335] space-y-3">
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300 font-semibold">
                  <Layers className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Semi-Transparent Background Box</span>
                </label>
                <input
                  type="checkbox"
                  checked={subtitleStyle.hasBackground}
                  onChange={(e) =>
                    setSubtitleStyle((prev) => ({ ...prev, hasBackground: e.target.checked }))
                  }
                  className="w-4 h-4 rounded accent-purple-600 bg-[#0b0c10] border-[#23283b] cursor-pointer"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={subtitleStyle.isUppercase}
                    onChange={(e) =>
                      setSubtitleStyle((prev) => ({ ...prev, isUppercase: e.target.checked }))
                    }
                    className="w-4 h-4 rounded accent-purple-600 bg-[#0b0c10] border-[#23283b]"
                  />
                  <span>All Uppercase</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
                  <input
                    type="checkbox"
                    checked={subtitleStyle.animateKaraoke}
                    onChange={(e) =>
                      setSubtitleStyle((prev) => ({ ...prev, animateKaraoke: e.target.checked }))
                    }
                    className="w-4 h-4 rounded accent-purple-600 bg-[#0b0c10] border-[#23283b]"
                  />
                  <span>Karaoke Word Glow</span>
                </label>
              </div>
            </div>
          </div>
        </>
      ) : activeSubTab === 'translate' ? (
        /* Multilingual Translation Panel */
        <div className="p-4 rounded-2xl bg-[#12141c] border border-[#212638] space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#1e2335]">
            <div className="flex items-center gap-2">
              <Languages className="w-4 h-4 text-purple-400" />
              <div>
                <span className="text-xs font-bold text-slate-200 block">
                  Translate Subtitles
                </span>
                <span className="text-[10px] text-slate-400">
                  Translate video captions into English, Malayalam, Hindi, Tamil & more
                </span>
              </div>
            </div>
            {subtitleStyle.isTranslated && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                ACTIVE
              </span>
            )}
          </div>

          {/* Current Spoken Language vs Target Language */}
          <div className="p-3 rounded-xl bg-[#0b0c10] border border-[#23283b] flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Globe className="w-4 h-4 text-purple-400 shrink-0" />
              <div>
                <span className="text-[11px] text-slate-400 block">Original Spoken Audio:</span>
                <span className="text-xs font-bold text-white">
                  {activeProject?.detectedLanguage
                    ? SUPPORTED_LANGUAGES[activeProject.detectedLanguage] || activeProject.detectedLanguage.toUpperCase()
                    : 'Auto-Detected'}
                </span>
              </div>
            </div>
            {activeProject?.detectedLanguageProbability !== undefined && activeProject?.detectedLanguageProbability !== null && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">
                {(activeProject.detectedLanguageProbability * 100).toFixed(0)}% confidence
              </span>
            )}
          </div>

          {/* Target Language Selection */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-slate-300">
              Target Subtitle Language
            </label>
            <select
              value={targetLanguage}
              disabled={isTranslating}
              onChange={(e) => {
                setTargetLanguage(e.target.value);
                setTranslationError(null);
              }}
              className="w-full px-3 py-2.5 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-white focus:outline-none focus:border-purple-500 disabled:opacity-50"
            >
              {Object.entries(SUPPORTED_LANGUAGES).filter(([code]) => code !== 'auto').map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          {/* Explicit Error Banner with Retry */}
          {translationError && (
            <div className="p-3 rounded-xl bg-red-950/40 border border-red-800/50 flex items-start justify-between gap-2 text-xs text-red-300">
              <div className="flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                <span>{translationError}</span>
              </div>
              <button
                type="button"
                onClick={handleTranslateSubtitles}
                disabled={isTranslating}
                className="px-2.5 py-1 rounded-lg bg-red-900/60 hover:bg-red-800/70 text-red-100 text-[11px] font-semibold shrink-0 border border-red-700/50"
              >
                Retry
              </button>
            </div>
          )}

          {/* Completed / Partial Translation Status */}
          {subtitleStyle.isTranslated && subtitleStyle.subtitleLanguage && subtitleStyle.subtitleLanguage !== 'original' && (
            <div className="p-3 rounded-xl bg-emerald-950/25 border border-emerald-700/40 space-y-1.5 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-emerald-300 flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>
                    Translated to {SUPPORTED_LANGUAGES[subtitleStyle.subtitleLanguage] || subtitleStyle.subtitleLanguage.toUpperCase()}
                  </span>
                </span>
                {subtitleStyle.translationProvider && (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                    {subtitleStyle.translationProvider === 'google_translate'
                      ? 'Google Translate (Free)'
                      : subtitleStyle.translationProvider === 'gemini'
                      ? 'Gemini API'
                      : subtitleStyle.translationProvider === 'openai'
                      ? 'OpenAI API'
                      : subtitleStyle.translationProvider}
                  </span>
                )}
              </div>
              {subtitleStyle.translationPartial && (
                <p className="text-[11px] text-amber-300">
                  Partial translation: some segments could not be translated and kept original text. Click Translate to retry.
                </p>
              )}
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex items-center gap-2 pt-2">
            <button
              onClick={handleTranslateSubtitles}
              disabled={isTranslating || clipSegments.length === 0}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-bold shadow-md shadow-purple-600/30 transition-all"
            >
              {isTranslating ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Translating to {SUPPORTED_LANGUAGES[targetLanguage] || targetLanguage}...</span>
                </>
              ) : (
                <>
                  <Languages className="w-4 h-4" />
                  <span>
                    {subtitleStyle.isTranslated ? 'Re-Translate Subtitles' : 'Translate Subtitles'}
                  </span>
                </>
              )}
            </button>

            {subtitleStyle.isTranslated && (
              <button
                onClick={handleResetSubtitles}
                disabled={isTranslating}
                className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl bg-[#1a1d2a] hover:bg-[#232738] text-slate-300 hover:text-white text-xs font-semibold border border-[#262c3e] transition-colors"
                title="Restore original spoken transcripts"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>Original</span>
              </button>
            )}
          </div>

          {/* Translated vs Original Segment Comparison */}
          {subtitleStyle.isTranslated && subtitleStyle.translatedSegments && subtitleStyle.translatedSegments.length > 0 && (
            <div className="space-y-2 pt-1">
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span className="font-semibold text-slate-300">
                  Translated Subtitles ({subtitleStyle.translatedSegments.length} segments)
                </span>
                <span className="text-[10px] text-emerald-400">Original transcript preserved</span>
              </div>
              <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
                {subtitleStyle.translatedSegments.map((seg, idx) => (
                  <div
                    key={seg.segment_id || idx}
                    className="p-2.5 rounded-xl bg-[#0b0c10] border border-[#23283b] space-y-1 text-xs"
                  >
                    <div className="flex items-center justify-between text-[10px] font-mono text-slate-500">
                      <span>#{idx + 1}</span>
                      <span>
                        {seg.start.toFixed(1)}s → {seg.end.toFixed(1)}s
                      </span>
                    </div>
                    {seg.original_text && (
                      <p className="text-[11px] text-slate-400">
                        <span className="text-[10px] uppercase tracking-wider text-slate-500 mr-1.5">Original:</span>
                        {seg.original_text}
                      </p>
                    )}
                    <p
                      dir={/[\u0600-\u06FF]/.test(seg.text) ? 'rtl' : 'auto'}
                      className="text-xs font-medium text-emerald-200"
                    >
                      <span className="text-[10px] uppercase tracking-wider text-emerald-400/80 mr-1.5">Translated:</span>
                      {seg.text}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Font & Synchronization Notice */}
          <div className="p-3 rounded-xl bg-cyan-950/20 border border-cyan-800/30 space-y-1 text-slate-300 text-[11px]">
            <p className="font-semibold text-cyan-300 flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
              <span>Independent Subtitle Layer</span>
            </p>
            <p className="text-slate-400 text-[10px] leading-relaxed">
              Original spoken transcripts are strictly preserved in the database. Translating updates the active clip subtitles and automatically configures Unicode font rendering (Nirmala UI for Malayalam & Indic scripts) with synchronized word timing.
            </p>
          </div>
        </div>
      ) : (
        /* Manual Transcript Correction View */
        <div className="p-4 rounded-2xl bg-[#12141c] border border-[#212638] space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#1e2335]">
            <div>
              <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                <Edit3 className="w-3.5 h-3.5 text-purple-400" />
                Manual Transcript Editor
              </span>
              <p className="text-[10px] text-slate-400 mt-0.5">
                Edit words or punctuation. Accurate Whisper timestamps are automatically preserved and synchronized.
              </p>
            </div>
            <button
              onClick={handleSaveTranscript}
              disabled={isSavingTranscript}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-bold shadow-md transition-all"
            >
              <Save className="w-3.5 h-3.5" />
              <span>{isSavingTranscript ? 'Saving...' : 'Save Changes'}</span>
            </button>
          </div>

          {clipSegments.length === 0 ? (
            <div className="py-8 text-center text-xs text-slate-500">
              No transcript segments found within this clip's time range ({activeHighlight?.startTime.toFixed(1)}s - {activeHighlight?.endTime.toFixed(1)}s).
            </div>
          ) : (
            <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
              {clipSegments.map((seg, idx) => {
                const currentText = editedTexts[seg.id] !== undefined ? editedTexts[seg.id] : seg.text;
                return (
                  <div
                    key={seg.id || idx}
                    className="p-3 rounded-xl bg-[#0b0c10] border border-[#23283b] space-y-2"
                  >
                    <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono">
                      <span>Line #{idx + 1}</span>
                      <span>
                        {seg.start.toFixed(2)}s → {seg.end.toFixed(2)}s ({(seg.end - seg.start).toFixed(1)}s)
                      </span>
                    </div>
                    <textarea
                      value={currentText}
                      onChange={(e) =>
                        setEditedTexts((prev) => ({
                          ...prev,
                          [seg.id]: e.target.value,
                        }))
                      }
                      rows={2}
                      className="w-full p-2 rounded-lg bg-[#141724] border border-[#292f44] text-xs text-white focus:outline-none focus:border-purple-500 resize-none font-sans"
                    />
                    {seg.words && seg.words.length > 0 && (
                      <div className="flex flex-wrap gap-1 text-[10px] text-slate-500 font-mono">
                        {seg.words.slice(0, 6).map((w, wIdx) => (
                          <span key={wIdx} className="px-1.5 py-0.2 rounded bg-[#161a29]">
                            {w.word}
                          </span>
                        ))}
                        {seg.words.length > 6 && (
                          <span className="text-slate-600">+{seg.words.length - 6} words</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="pt-2 flex items-center gap-1.5 text-[10px] text-slate-400">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
            <span>Updated subtitles will be automatically burned on export with word-level animation.</span>
          </div>
        </div>
      )}
    </div>
  );
};
