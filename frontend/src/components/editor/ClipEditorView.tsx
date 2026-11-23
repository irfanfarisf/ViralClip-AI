import React, { useState, useEffect } from 'react';
import {
  Download,
  ArrowLeft,
  Sparkles,
  LayoutTemplate,
  Type,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { updateClipOnBackend } from '../../services/api';
import { VerticalPreview } from './VerticalPreview';
import { LayoutControls } from './LayoutControls';
import { SubtitleControls } from './SubtitleControls';
import { MetadataControls } from './MetadataControls';
import { TimelineScrubber } from './TimelineScrubber';

export const ClipEditorView: React.FC = () => {
  const {
    activeProject,
    activeHighlight,
    setActiveHighlight,
    setCurrentView,
    subtitleStyle,
    setSubtitleStyle,
    exportCurrentHighlight,
    showToast,
  } = useApp();

  const [activeTab, setActiveTab] = useState<'layout' | 'subtitles' | 'metadata'>('layout');
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [clipTitle, setClipTitle] = useState('');
  const [isExporting, setIsExporting] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [seekVersion, setSeekVersion] = useState(0);

  useEffect(() => {
    if (activeHighlight) {
      setClipTitle(activeHighlight.title);
      setCurrentTime(activeHighlight.startTime);
      setSeekVersion((v) => v + 1);
      setIsPlaying(false);
    }
  }, [activeHighlight?.id]);

  // Fallback timer ONLY when there is no real video URL (e.g. demo sample without media)
  useEffect(() => {
    if (activeProject?.localVideoUrl) return;
    let animId: number;
    let lastStamp = performance.now();

    const loop = (now: number) => {
      const delta = (now - lastStamp) / 1000;
      lastStamp = now;

      if (isPlaying && activeHighlight) {
        setCurrentTime((prev) => {
          const next = prev + delta;
          if (next >= activeHighlight.endTime) {
            return activeHighlight.startTime; // loop back to clip start
          }
          return next;
        });
      }
      animId = requestAnimationFrame(loop);
    };

    animId = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animId);
  }, [isPlaying, activeHighlight, activeProject?.localVideoUrl]);

  if (!activeProject || !activeHighlight) {
    return (
      <div className="p-12 text-center text-slate-400 space-y-4">
        <Sparkles className="w-10 h-10 text-slate-500 mx-auto" />
        <p className="text-sm font-semibold text-white">No active clip selected for editing</p>
        <p className="text-xs">Please select a highlight moment from the Video Processing page.</p>
        <button
          onClick={() => setCurrentView('processing')}
          className="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-semibold"
        >
          Go to Video Processing
        </button>
      </div>
    );
  }

  const handleExport = async () => {
    try {
      setIsExporting(true);
      await exportCurrentHighlight(clipTitle);
    } catch (err: any) {
      showToast(err?.message || 'Export error');
    } finally {
      setIsExporting(false);
    }
  };

  const handleSeek = (targetTime: number) => {
    const clamped = Math.max(activeHighlight.startTime, Math.min(activeHighlight.endTime, targetTime));
    setCurrentTime(clamped);
    setSeekVersion((v) => v + 1);
  };

  const handleToggleMute = () => {
    setIsMuted((prev) => !prev);
  };

  const handleVolumeChange = (nextVolume: number) => {
    const clamped = Math.min(1, Math.max(0, nextVolume));
    setVolume(clamped);
    if (clamped > 0 && isMuted) {
      setIsMuted(false);
    } else if (clamped === 0 && !isMuted) {
      setIsMuted(true);
    }
  };

  const handleAdjustStart = (delta: number) => {
    const newStart = Math.max(0, Math.min(activeHighlight.endTime - 3, activeHighlight.startTime + delta));
    const newDur = Math.max(3, activeHighlight.endTime - newStart);
    setActiveHighlight({
      ...activeHighlight,
      startTime: newStart,
      duration: newDur,
    });
    if (currentTime < newStart || currentTime > activeHighlight.endTime) {
      setCurrentTime(newStart);
      setSeekVersion((v) => v + 1);
    }
    if (!activeProject.isDemo) {
      updateClipOnBackend(activeHighlight.id, { start_time: newStart, end_time: activeHighlight.endTime }).catch(() => {});
    }
  };

  const handleAdjustEnd = (delta: number) => {
    const newEnd = Math.min(activeProject.duration, Math.max(activeHighlight.startTime + 3, activeHighlight.endTime + delta));
    const newDur = Math.max(3, newEnd - activeHighlight.startTime);
    setActiveHighlight({
      ...activeHighlight,
      endTime: newEnd,
      duration: newDur,
    });
    if (currentTime > newEnd || currentTime < activeHighlight.startTime) {
      setCurrentTime(activeHighlight.startTime);
      setSeekVersion((v) => v + 1);
    }
    if (!activeProject.isDemo) {
      updateClipOnBackend(activeHighlight.id, { start_time: activeHighlight.startTime, end_time: newEnd }).catch(() => {});
    }
  };

  const subtitlesOn = subtitleStyle.enabled !== false;

  const handleToggleSubtitles = () => {
    const nextEnabled = !subtitlesOn;
    setSubtitleStyle((prev) => ({ ...prev, enabled: nextEnabled }));
    if (activeProject && activeHighlight && !activeProject.isDemo) {
      updateClipOnBackend(activeHighlight.id, {
        subtitle_style: {
          ...(activeHighlight.subtitleStyle || {}),
          enabled: nextEnabled,
        },
      }).catch(() => {});
    }
    showToast(nextEnabled ? 'Subtitles turned ON (preview & export)' : 'Subtitles turned OFF (preview & export)');
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto space-y-6">
      {/* Top Action Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[#1f2333]">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setCurrentView('processing')}
            className="p-2.5 rounded-xl bg-[#141724] hover:bg-[#1d2235] text-slate-300 hover:text-white transition-colors border border-[#23283b]"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 uppercase">
                Viral Score {activeHighlight.score}%
              </span>
              <span className="text-xs text-slate-400 font-mono">
                Duration: {activeHighlight.duration.toFixed(1)}s
              </span>
            </div>
            <input
              type="text"
              value={clipTitle}
              onChange={(e) => setClipTitle(e.target.value)}
              className="mt-1 font-extrabold text-lg text-white bg-transparent border-b border-transparent hover:border-slate-600 focus:border-purple-500 focus:outline-none transition-colors w-full max-w-md"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleExport}
            disabled={isExporting}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 via-indigo-600 to-cyan-500 hover:from-purple-500 hover:to-cyan-400 disabled:opacity-50 text-white text-xs font-bold shadow-lg shadow-purple-600/30 transition-all active:scale-95"
          >
            <Download className="w-4 h-4" />
            <span>{isExporting ? 'Composing & Exporting...' : 'Export 9:16 Short'}</span>
          </button>
        </div>
      </div>

      {/* Main Studio Work Area */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: 9:16 Vertical Preview Phone Canvas */}
        <div className="lg:col-span-5 flex flex-col items-center justify-center p-6 rounded-3xl bg-[#0e1017] border border-[#212638] shadow-2xl space-y-4">
          <div className="flex items-center justify-between w-full px-2 text-xs text-slate-400 gap-2">
            <span className="font-semibold text-slate-300 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-purple-400" />
              Vertical 9:16 Live Canvas
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleToggleSubtitles}
                aria-pressed={subtitlesOn}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-bold border transition-colors ${
                  subtitlesOn
                    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40 hover:bg-emerald-500/25'
                    : 'bg-slate-800/80 text-slate-400 border-slate-700 hover:text-white'
                }`}
                title="Toggle subtitles in preview and exported video without deleting transcript data"
              >
                <Type className="w-3 h-3" />
                <span>Subtitles: {subtitlesOn ? 'ON' : 'OFF'}</span>
              </button>
              <span className="font-mono text-[11px] text-cyan-400">1080×1920</span>
            </div>
          </div>

          <VerticalPreview
            currentTime={currentTime}
            isPlaying={isPlaying}
            startTime={activeHighlight.startTime}
            endTime={activeHighlight.endTime}
            isMuted={isMuted}
            volume={volume}
            hasAudio={activeProject.hasAudio !== false}
            seekVersion={seekVersion}
            onTimeUpdate={(t) => setCurrentTime(t)}
            onAudioError={(msg) => showToast(msg)}
            videoUrl={activeProject.localVideoUrl}
          />

          <p className="text-[11px] text-slate-400 text-center max-w-xs">
            {subtitlesOn
              ? 'Live preview simulates 9:16 layout with synchronized subtitles (included in export).'
              : 'Subtitles are OFF — hidden in preview and excluded from export. Transcript & translations are preserved.'}
          </p>
        </div>

        {/* Right Column: Customization Tabs (Layout & Subtitles) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Tab Selector */}
          <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-[#12141c] border border-[#212638]">
            <button
              onClick={() => setActiveTab('layout')}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-bold transition-all ${
                activeTab === 'layout'
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <LayoutTemplate className="w-4 h-4" />
              <span>Layout</span>
              <span className="text-[10px] px-1.5 py-0.2 bg-purple-900/60 rounded font-normal hidden sm:inline">
                Facecam Top
              </span>
            </button>

            <button
              onClick={() => setActiveTab('subtitles')}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-bold transition-all ${
                activeTab === 'subtitles'
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Type className="w-4 h-4" />
              <span>Subtitles</span>
              <span className="text-[10px] px-1.5 py-0.2 bg-cyan-900/60 rounded text-cyan-200 font-normal hidden sm:inline">
                Word-Level
              </span>
            </button>

            <button
              onClick={() => setActiveTab('metadata')}
              className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-bold transition-all ${
                activeTab === 'metadata'
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Sparkles className="w-4 h-4" />
              <span>AI Metadata</span>
              <span className="text-[10px] px-1.5 py-0.2 bg-amber-900/60 rounded text-amber-200 font-normal hidden sm:inline">
                Titles & Thumb
              </span>
            </button>
          </div>

          {/* Active Tab Component */}
          {activeTab === 'layout' ? (
            <LayoutControls />
          ) : activeTab === 'subtitles' ? (
            <SubtitleControls />
          ) : (
            <MetadataControls
              currentTime={currentTime}
              onSeek={handleSeek}
            />
          )}

          {/* Interactive Timeline Scrubber */}
          <TimelineScrubber
            startTime={activeHighlight.startTime}
            endTime={activeHighlight.endTime}
            currentTime={currentTime}
            maxDuration={activeProject.duration}
            isPlaying={isPlaying}
            isMuted={isMuted}
            volume={volume}
            hasAudio={activeProject.hasAudio !== false}
            onPlayPause={() => setIsPlaying(!isPlaying)}
            onToggleMute={handleToggleMute}
            onVolumeChange={handleVolumeChange}
            onSeek={handleSeek}
            onAdjustStart={handleAdjustStart}
            onAdjustEnd={handleAdjustEnd}
          />
        </div>
      </div>
    </div>
  );
};
