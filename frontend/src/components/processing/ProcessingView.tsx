import React, { useState, useRef, useEffect } from 'react';
import {
  Play,
  Pause,
  Scissors,
  CheckCircle2,
  Clock,
  Sparkles,
  Flame,
  Search,
  ChevronRight,
  Sliders,
  Volume2,
  RotateCcw,
  Check,
  AlertCircle,
  RefreshCw,
  XCircle,
  Globe,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { startJob, cancelJob } from '../../services/api';
import { SUPPORTED_LANGUAGES, type HighlightMoment, type TranscriptSegment } from '../../types';

export const ProcessingView: React.FC = () => {
  const {
    activeProject,
    toggleHighlightSelection,
    openEditorForHighlight,
    setCurrentView,
    syncJobDetails,
    showToast,
  } = useApp();

  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState<'highlights' | 'transcript'>('highlights');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  const lowStatus = String(activeProject?.status || '').toLowerCase();
  const isJobRunning = Boolean(
    activeProject?.activeJobId &&
      [
        'queued',
        'initializing',
        'downloading',
        'uploading',
        'validating',
        'extracting_metadata',
        'analyzing',
        'transcribing',
        'detecting',
      ].includes(lowStatus)
  );
  const isMediaReady = Boolean(
    activeProject?.localVideoUrl &&
      !['queued', 'initializing', 'downloading', 'uploading', 'validating', 'extracting_metadata', 'failed', 'cancelled'].includes(
        lowStatus
      )
  );

  // Poll job status if in progress
  useEffect(() => {
    if (isJobRunning && activeProject?.activeJobId) {
      const interval = setInterval(() => {
        syncJobDetails(activeProject.activeJobId!);
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [activeProject?.activeJobId, isJobRunning]);

  if (!activeProject) {
    return (
      <div className="p-12 text-center text-slate-400 space-y-4">
        <AlertCircle className="w-12 h-12 text-slate-500 mx-auto" />
        <p className="text-base font-semibold text-slate-200">No active project selected</p>
        <p className="text-xs">Select or import a project from the Dashboard to monitor processing and review highlights.</p>
        <button
          onClick={() => setCurrentView('dashboard')}
          className="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-semibold"
        >
          Return to Dashboard
        </button>
      </div>
    );
  }

  const handlePlayPause = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const jumpToTime = (seconds: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = seconds;
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleManualRefresh = async () => {
    if (activeProject.activeJobId) {
      setIsRefreshing(true);
      await syncJobDetails(activeProject.activeJobId);
      setIsRefreshing(false);
      showToast('Synchronized job state with backend');
    }
  };

  const handleCancelJob = async () => {
    if (activeProject.activeJobId) {
      try {
        await cancelJob(activeProject.activeJobId);
        showToast('Job cancelled');
        syncJobDetails(activeProject.activeJobId);
      } catch (err: any) {
        showToast(err.message);
      }
    }
  };

  const handleRestartJob = async () => {
    if (activeProject.activeJobId) {
      try {
        await startJob(activeProject.activeJobId);
        showToast('Processing restarted');
        syncJobDetails(activeProject.activeJobId);
      } catch (err: any) {
        showToast(err.message);
      }
    }
  };

  const filteredTranscripts = activeProject.transcripts.filter((seg) =>
    seg.text.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const selectedHighlightsCount = activeProject.selectedClipIds?.length || 0;

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Top Project Header & Progress */}
      <div className="rounded-3xl bg-[#12141c] border border-[#212638] p-6 shadow-xl space-y-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-purple-500/20 text-purple-300 border border-purple-500/30">
                {activeProject.sourceType.toUpperCase()} SOURCE
              </span>
              {activeProject.isDemo && (
                <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 uppercase">
                  DEMO DATA (SAMPLE)
                </span>
              )}
              <span className="text-xs text-slate-400 font-mono">ID: {activeProject.id}</span>
            </div>
            <h2 className="text-xl md:text-2xl font-extrabold text-white">
              {activeProject.title}
            </h2>
            <div className="flex items-center gap-4 text-xs text-slate-400 mt-1">
              <span className="flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-cyan-400" />
                {Math.floor(activeProject.duration / 60)}m {Math.round(activeProject.duration % 60)}s
              </span>
              <span>•</span>
              <span>{activeProject.width}×{activeProject.height}</span>
              <span>•</span>
              <span>{activeProject.fps} FPS</span>
              <span>•</span>
              <span>{activeProject.fileSizeMb || 0} MB</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {activeProject.activeJobId && (
              <button
                onClick={handleManualRefresh}
                disabled={isRefreshing}
                title="Refresh state from backend"
                className="p-2.5 rounded-xl bg-[#181b28] hover:bg-[#202538] text-slate-300 hover:text-white transition-colors border border-[#23283b]"
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
              </button>
            )}

            {isJobRunning && (
              <button
                onClick={handleCancelJob}
                className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-red-950/40 hover:bg-red-900/50 text-red-300 text-xs font-semibold border border-red-800/40 transition-colors"
              >
                <XCircle className="w-4 h-4" />
                <span>Cancel</span>
              </button>
            )}

            {(['cancelled', 'failed', 'completed'].includes(lowStatus)) && activeProject.activeJobId && (
              <button
                onClick={handleRestartJob}
                className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                <span>
                  {lowStatus === 'completed'
                    ? 'Start AI Analysis'
                    : activeProject.canResume
                    ? 'Resume / Retry'
                    : 'Restart'}
                </span>
              </button>
            )}

            <button
              onClick={() => {
                if (activeProject.highlights[0]) {
                  openEditorForHighlight(activeProject, activeProject.highlights[0]);
                } else {
                  showToast('Wait for highlights to finish extracting or select a highlight');
                }
              }}
              disabled={activeProject.highlights.length === 0}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-semibold shadow-md shadow-purple-600/30 transition-all"
            >
              <Sliders className="w-4 h-4" />
              <span>Open Clip Editor</span>
            </button>
          </div>
        </div>

        {/* Multi-stage Progress tracker */}
        <div className="space-y-2 pt-2 border-t border-[#1c2030]">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-slate-300 flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-purple-400" />
              {activeProject.currentStage}
            </span>
            <span className="font-mono font-bold text-cyan-400">{activeProject.progress}%</span>
          </div>

          <div className="w-full h-2.5 rounded-full bg-[#0b0c10] overflow-hidden p-0.5 border border-[#1f2436]">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                activeProject.status === 'failed' || activeProject.status === 'FAILED'
                  ? 'bg-red-500'
                  : 'bg-gradient-to-r from-purple-600 via-indigo-500 to-cyan-400'
              }`}
              style={{ width: `${activeProject.progress}%` }}
            />
          </div>

          {(activeProject.bytesTransferred || activeProject.speedBps) ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3 rounded-xl bg-[#0e1017] border border-[#1f2437] text-[11px] font-mono text-slate-300">
              <div>
                <span className="text-slate-500 block">Import Stage</span>
                <span className="text-purple-300 font-bold">{activeProject.importState || activeProject.status}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Transferred</span>
                <span>
                  {((activeProject.bytesTransferred || 0) / 1048576).toFixed(1)} MB
                  {activeProject.totalBytes ? ` / ${(activeProject.totalBytes / 1048576).toFixed(1)} MB` : ''}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Transfer Speed</span>
                <span className="text-emerald-300">
                  {activeProject.speedBps ? `${(activeProject.speedBps / 1048576).toFixed(1)} MB/s` : '--'}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Elapsed / ETA</span>
                <span className="text-cyan-300">
                  {activeProject.elapsedSeconds !== undefined ? `${Math.round(activeProject.elapsedSeconds)}s / ` : ''}
                  {activeProject.etaSeconds !== null && activeProject.etaSeconds !== undefined
                    ? `${Math.ceil(activeProject.etaSeconds)}s`
                    : '--'}
                </span>
              </div>
            </div>
          ) : null}

          {(activeProject.status === 'transcribing' || activeProject.transcribedSeconds || activeProject.whisperDevice) ? (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3 rounded-xl bg-[#0e1017] border border-[#1f2437] text-[11px] font-mono text-slate-300">
              <div>
                <span className="text-slate-500 block">Whisper Device &amp; Profile</span>
                <span className="text-purple-300 font-bold">
                  {(activeProject.whisperModel || 'base').toUpperCase()} • {(activeProject.whisperProfile || 'balanced').toUpperCase()} • {activeProject.whisperDevice || 'CPU (int8)'}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Transcribed Audio</span>
                <span>
                  {Math.floor((activeProject.transcribedSeconds || 0) / 60)}m {Math.round((activeProject.transcribedSeconds || 0) % 60)}s /{' '}
                  {Math.floor((activeProject.totalAudioSeconds || activeProject.duration || 0) / 60)}m{' '}
                  {Math.round((activeProject.totalAudioSeconds || activeProject.duration || 0) % 60)}s
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Processing Speed</span>
                <span className="text-emerald-300">
                  {activeProject.realtimeFactor ? `${activeProject.realtimeFactor.toFixed(1)}× real-time` : '--'}
                </span>
              </div>
              <div>
                <span className="text-slate-500 block">Elapsed / Remaining</span>
                <span className="text-cyan-300">
                  {activeProject.elapsedSeconds !== undefined ? `${Math.round(activeProject.elapsedSeconds)}s / ` : ''}
                  {activeProject.etaSeconds !== null && activeProject.etaSeconds !== undefined && activeProject.etaSeconds > 0
                    ? `${Math.ceil(activeProject.etaSeconds)}s`
                    : lowStatus === 'ready'
                    ? 'Complete'
                    : '--'}
                </span>
              </div>
            </div>
          ) : null}

          {/* Detected Language Pill */}
          {activeProject.detectedLanguage && (
            <div className="flex items-center justify-between p-3 rounded-xl bg-purple-950/20 border border-purple-800/30 text-xs text-slate-300">
              <div className="flex items-center gap-2.5">
                <Globe className="w-4 h-4 text-purple-400 shrink-0" />
                <span className="text-slate-400 font-medium">Spoken Language:</span>
                <span className="font-bold text-white">
                  {SUPPORTED_LANGUAGES[activeProject.detectedLanguage] || activeProject.detectedLanguage.toUpperCase()}
                </span>
                {activeProject.detectedLanguageProbability !== undefined && activeProject.detectedLanguageProbability !== null && (
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30 font-semibold">
                    {(activeProject.detectedLanguageProbability * 100).toFixed(0)}% confidence
                  </span>
                )}
              </div>
              <span className="text-[11px] text-slate-400 font-mono">
                Multilingual Whisper Model
              </span>
            </div>
          )}

          {(activeProject.status === 'failed' || activeProject.status === 'FAILED') && activeProject.errorMessage && (
            <div className="p-3 rounded-xl bg-red-950/40 border border-red-800/50 flex items-center gap-2 text-xs text-red-300">
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
              <span>{activeProject.errorMessage}</span>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2 pt-2 text-[11px] text-slate-400">
            <div className={`flex items-center gap-1.5 ${activeProject.importState === 'COMPLETED' || ['analyzing', 'transcribing', 'detecting', 'ready'].includes(activeProject.status) ? 'text-emerald-300 font-semibold' : ''}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>1. Import Ready</span>
            </div>
            <div className={`flex items-center gap-1.5 ${activeProject.progress >= 12 || ['transcribing', 'detecting', 'ready'].includes(activeProject.status) ? 'text-purple-300 font-semibold' : ''}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>2. Audio Extracted</span>
            </div>
            <div className={`flex items-center gap-1.5 ${activeProject.progress >= 70 || ['detecting', 'ready'].includes(activeProject.status) ? 'text-purple-300 font-semibold' : ''}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>3. Whisper STT</span>
            </div>
            <div className={`flex items-center gap-1.5 ${activeProject.progress >= 90 || activeProject.status === 'ready' ? 'text-cyan-300 font-semibold' : ''}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>4. AI Highlights</span>
            </div>
            <div className={`flex items-center gap-1.5 ${activeProject.highlights.length > 0 ? 'text-cyan-300 font-semibold' : ''}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>5. Clip Generation</span>
            </div>
            <div className={`flex items-center gap-1.5 ${activeProject.status === 'ready' ? 'text-emerald-300 font-semibold' : ''}`}>
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
              <span>6. Export Ready</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Grid: Video Player (Left) + Highlights / Transcript Tabs (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Video Preview Player */}
        <div className="lg:col-span-7 space-y-4">
          <div className="rounded-3xl bg-[#12141c] border border-[#212638] overflow-hidden shadow-2xl">
            <div className="relative aspect-video bg-black flex items-center justify-center group">
              <video
                ref={videoRef}
                src={isMediaReady ? activeProject.localVideoUrl : undefined}
                onTimeUpdate={handleTimeUpdate}
                onEnded={() => setIsPlaying(false)}
                className="w-full h-full object-contain"
                playsInline
              />

              {/* Play / Pause overlay button */}
              <button
                onClick={handlePlayPause}
                className="absolute inset-0 m-auto w-16 h-16 rounded-full bg-black/60 hover:bg-purple-600/90 text-white flex items-center justify-center backdrop-blur-sm transition-all duration-200 group-hover:scale-105"
              >
                {isPlaying ? <Pause className="w-7 h-7" /> : <Play className="w-7 h-7 ml-1" />}
              </button>

              <div className="absolute top-4 left-4 px-3 py-1 rounded-full bg-black/60 backdrop-blur-md text-[11px] font-mono text-slate-300 border border-white/10">
                {Math.floor(currentTime / 60)}:{Math.floor(currentTime % 60).toString().padStart(2, '0')} /{' '}
                {Math.floor(activeProject.duration / 60)}:{Math.floor(activeProject.duration % 60).toString().padStart(2, '0')}
              </div>
            </div>

            {/* Controls Bar */}
            <div className="p-4 bg-[#0d0e15] border-t border-[#1c2030] flex items-center justify-between text-xs text-slate-400">
              <div className="flex items-center gap-2">
                <button
                  onClick={handlePlayPause}
                  className="p-2 rounded-lg bg-[#181b28] hover:bg-[#202538] text-white transition-colors"
                >
                  {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => jumpToTime(0)}
                  title="Restart"
                  className="p-2 rounded-lg bg-[#181b28] hover:bg-[#202538] text-slate-300 hover:text-white transition-colors"
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
                <div className="h-4 w-px bg-[#262c3f] mx-1" />
                <span className="text-slate-300 font-mono text-[11px]">
                  Scrubbing: {currentTime.toFixed(1)}s
                </span>
              </div>

              <div className="flex items-center gap-2 text-slate-400">
                <Volume2 className="w-4 h-4" />
                <span>Stereo Audio Track</span>
              </div>
            </div>
          </div>

          {/* Highlights summary bar */}
          <div className="p-4 rounded-2xl bg-[#12141c] border border-[#212638] flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-cyan-500/20 text-cyan-400 flex items-center justify-center font-bold text-xs">
                {selectedHighlightsCount}
              </div>
              <span className="text-xs text-slate-300 font-medium">
                Clips selected for export & editing (Pick your top 2)
              </span>
            </div>

            {selectedHighlightsCount > 0 && (
              <button
                onClick={() => {
                  const firstSelected = activeProject.highlights.find((h) =>
                    activeProject.selectedClipIds.includes(h.id)
                  );
                  if (firstSelected) {
                    openEditorForHighlight(activeProject, firstSelected);
                  }
                }}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md transition-all"
              >
                <span>Edit Selected</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>

        {/* Right Column: Highlights & Transcripts Tabs */}
        <div className="lg:col-span-5 space-y-4">
          <div className="rounded-3xl bg-[#12141c] border border-[#212638] p-5 shadow-2xl flex flex-col h-[600px]">
            {/* Tab switch */}
            <div className="flex items-center justify-between pb-4 border-b border-[#1f2436]">
              <div className="flex items-center gap-1 p-1 rounded-xl bg-[#0b0c10] border border-[#1f2333]">
                <button
                  onClick={() => setActiveTab('highlights')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === 'highlights'
                      ? 'bg-purple-600 text-white shadow'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Flame className="w-3.5 h-3.5 text-amber-400" />
                  <span>Highlights ({activeProject.highlights.length})</span>
                </button>
                <button
                  onClick={() => setActiveTab('transcript')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    activeTab === 'transcript'
                      ? 'bg-purple-600 text-white shadow'
                      : 'text-slate-400 hover:text-white'
                  }`}
                >
                  <Scissors className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Transcript</span>
                </button>
              </div>

              {activeTab === 'transcript' && (
                <div className="relative">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search words..."
                    className="w-36 px-2.5 py-1 text-xs rounded-lg bg-[#0b0c10] border border-[#23283b] text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
                  />
                  <Search className="w-3 h-3 text-slate-500 absolute right-2 top-2 pointer-events-none" />
                </div>
              )}
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-y-auto pt-4 pr-1 space-y-3.5">
              {activeTab === 'highlights' ? (
                activeProject.highlights.length === 0 ? (
                  <div className="p-8 text-center text-slate-500 space-y-2">
                    <Sparkles className="w-8 h-8 text-purple-400 animate-spin mx-auto" />
                    <p className="text-xs font-medium text-slate-400">
                      {activeProject.status === 'analyzing'
                        ? 'Backend is processing speech recognition and energy peaks...'
                        : 'No highlights detected yet for this video.'}
                    </p>
                  </div>
                ) : (
                  activeProject.highlights.map((highlight: HighlightMoment) => {
                    const isSelected = activeProject.selectedClipIds?.includes(highlight.id);
                    return (
                      <div
                        key={highlight.id}
                        className={`rounded-2xl p-4 border transition-all duration-200 space-y-3 ${
                          isSelected
                            ? 'bg-[#181a28] border-purple-500/50 shadow-md shadow-purple-950/20'
                            : 'bg-[#0f1118] border-[#202538] hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="w-7 h-7 rounded-lg bg-gradient-to-tr from-purple-600 to-cyan-500 text-white flex items-center justify-center text-xs font-bold shadow">
                              {highlight.score}
                            </span>
                            <div>
                              <h4 className="text-xs font-bold text-white line-clamp-1">
                                {highlight.title}
                              </h4>
                              <p className="text-[11px] text-slate-400 flex items-center gap-1.5 mt-0.5">
                                <Clock className="w-3 h-3 text-cyan-400" />
                                {highlight.startTime.toFixed(1)}s - {highlight.endTime.toFixed(1)}s
                                <span className="text-purple-300 font-semibold">
                                  ({highlight.duration.toFixed(1)}s duration)
                                </span>
                              </p>
                            </div>
                          </div>

                          <button
                            onClick={() => toggleHighlightSelection(activeProject.id, highlight.id)}
                            className={`w-6 h-6 rounded-lg flex items-center justify-center transition-colors ${
                              isSelected
                                ? 'bg-purple-600 text-white'
                                : 'bg-[#1b1e2e] text-slate-500 hover:text-white border border-[#262c3f]'
                            }`}
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                        </div>

                        <p className="text-[11px] text-slate-400 leading-relaxed bg-[#0b0c10] p-2.5 rounded-xl border border-[#1b1e2c]">
                          <span className="text-purple-400 font-semibold">Detection Signal:</span> {highlight.reason}
                        </p>

                        <div className="flex items-center justify-between pt-1">
                          <button
                            onClick={() => jumpToTime(highlight.startTime)}
                            className="text-[11px] font-semibold text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                          >
                            <Play className="w-3 h-3" />
                            <span>Preview Section</span>
                          </button>

                          <button
                            onClick={() => openEditorForHighlight(activeProject, highlight)}
                            className="text-[11px] font-semibold text-purple-400 hover:text-purple-300 flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20"
                          >
                            <Sliders className="w-3 h-3" />
                            <span>Edit in 9:16</span>
                          </button>
                        </div>
                      </div>
                    );
                  })
                )
              ) : (
                /* Transcript Tab */
                <div className="space-y-3">
                  {filteredTranscripts.length === 0 ? (
                    <div className="p-8 text-center text-slate-500 text-xs">
                      No transcript segments available yet.
                    </div>
                  ) : (
                    filteredTranscripts.map((seg: TranscriptSegment) => (
                      <div
                        key={seg.id}
                        onClick={() => jumpToTime(seg.start)}
                        className="p-3 rounded-xl bg-[#0c0d14] border border-[#1b1e2c] hover:border-purple-500/40 cursor-pointer transition-all space-y-1.5 group"
                      >
                        <div className="flex items-center justify-between text-[10px] text-slate-400">
                          <span className="font-mono text-cyan-400 font-semibold group-hover:text-cyan-300">
                            {seg.start.toFixed(1)}s - {seg.end.toFixed(1)}s
                          </span>
                          <span className="text-slate-500 font-medium">
                            Confidence {(seg.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                        <p className="text-xs text-slate-200 leading-relaxed group-hover:text-white">
                          {seg.text}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
