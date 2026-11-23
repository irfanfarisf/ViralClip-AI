import React, { useRef, useEffect } from 'react';
import { Info } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import type { TranscriptWord } from '../../types';

interface VerticalPreviewProps {
  currentTime: number;
  isPlaying: boolean;
  startTime?: number;
  endTime?: number;
  isMuted?: boolean;
  volume?: number;
  hasAudio?: boolean;
  seekVersion?: number;
  onTimeUpdate?: (time: number) => void;
  onAudioError?: (msg: string) => void;
  videoUrl?: string;
}

export const VerticalPreview: React.FC<VerticalPreviewProps> = ({
  currentTime,
  isPlaying,
  startTime = 0,
  endTime,
  isMuted = false,
  volume = 1,
  hasAudio = true,
  seekVersion = 0,
  onTimeUpdate,
  onAudioError,
  videoUrl,
}) => {
  const { subtitleStyle, layoutConfig, activeProject } = useApp();
  const facecamVideoRef = useRef<HTMLVideoElement>(null);
  const gameplayVideoRef = useRef<HTMLVideoElement>(null);
  const effectiveMuted = Boolean(isMuted || !hasAudio);

  const isFacecamGameplay = layoutConfig.preset === 'facecam_gameplay';
  const isSingleCrop =
    layoutConfig.preset === 'smart_crop' ||
    layoutConfig.preset === 'center_crop' ||
    layoutConfig.preset === 'custom';
  const isFullscreen = layoutConfig.preset === 'fullscreen';
  const isGameplayPip = layoutConfig.preset === 'gameplay_pip';
  const isSplit50 = layoutConfig.preset === 'split_50_50';

  const getMediaPair = () => {
    const primary = isSingleCrop ? facecamVideoRef.current : gameplayVideoRef.current;
    const secondary = isSingleCrop ? null : facecamVideoRef.current;
    return { primary, secondary };
  };

  // Keep audio volume & mute state synchronized on the single primary video element
  useEffect(() => {
    const { primary, secondary } = getMediaPair();
    if (primary) {
      primary.muted = effectiveMuted;
      primary.volume = Math.min(1, Math.max(0, volume));
    }
    if (secondary) {
      secondary.muted = true;
    }
  }, [effectiveMuted, volume, layoutConfig.preset, videoUrl]);

  // Apply explicit user seeks / trim adjustments / restart requests
  useEffect(() => {
    const { primary, secondary } = getMediaPair();
    const target = Math.max(0, currentTime);
    if (primary && Number.isFinite(target)) {
      try {
        primary.currentTime = target;
      } catch {
        // ignore if metadata not yet loaded
      }
    }
    if (secondary && Number.isFinite(target)) {
      try {
        secondary.currentTime = target;
      } catch {
        // ignore
      }
    }
  }, [seekVersion, layoutConfig.preset]);

  // Synchronize play / pause state without fighting the native media clock
  useEffect(() => {
    const { primary, secondary } = getMediaPair();
    if (!primary) return;

    if (isPlaying) {
      if (endTime !== undefined && (primary.currentTime < startTime - 0.1 || primary.currentTime >= endTime)) {
        primary.currentTime = startTime;
        if (secondary) secondary.currentTime = startTime;
      }
      primary.muted = effectiveMuted;
      primary.volume = Math.min(1, Math.max(0, volume));
      const playPromise = primary.play();
      if (playPromise && typeof playPromise.catch === 'function') {
        playPromise.catch((err: any) => {
          if (err?.name === 'NotAllowedError' && !primary.muted) {
            primary.muted = true;
            primary.play().catch(() => {});
            onAudioError?.('Browser blocked unmuted playback — click Play or Unmute to enable audio.');
          }
        });
      }
      if (secondary) {
        secondary.muted = true;
        if (Math.abs(secondary.currentTime - primary.currentTime) > 0.2) {
          secondary.currentTime = primary.currentTime;
        }
        secondary.play().catch(() => {});
      }
    } else {
      if (!primary.paused) primary.pause();
      if (secondary && !secondary.paused) secondary.pause();
    }
  }, [isPlaying, layoutConfig.preset, videoUrl]);

  // Ensure audio stops cleanly on unmount
  useEffect(() => {
    return () => {
      facecamVideoRef.current?.pause();
      gameplayVideoRef.current?.pause();
    };
  }, []);

  const handlePrimaryLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const vid = e.currentTarget;
    vid.muted = effectiveMuted;
    vid.volume = Math.min(1, Math.max(0, volume));
    if (Math.abs(vid.currentTime - currentTime) > 0.15) {
      vid.currentTime = Math.max(0, currentTime);
    }
  };

  const handleSecondaryLoadedMetadata = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const vid = e.currentTarget;
    vid.muted = true;
    if (Math.abs(vid.currentTime - currentTime) > 0.15) {
      vid.currentTime = Math.max(0, currentTime);
    }
  };

  const handlePrimaryTimeUpdate = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const primary = e.currentTarget;
    const { secondary } = getMediaPair();
    let t = primary.currentTime;
    if (endTime !== undefined && t >= endTime) {
      t = startTime;
      primary.currentTime = t;
      if (secondary) secondary.currentTime = t;
    } else if (secondary && Math.abs(secondary.currentTime - t) > 0.25) {
      secondary.currentTime = t;
    }
    onTimeUpdate?.(t);
  };

  const handlePrimaryEnded = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const primary = e.currentTarget;
    const { secondary } = getMediaPair();
    primary.currentTime = startTime;
    if (secondary) secondary.currentTime = startTime;
    onTimeUpdate?.(startTime);
    if (isPlaying) {
      primary.play().catch(() => {});
      if (secondary) secondary.play().catch(() => {});
    }
  };

  // Find active transcript word chunk matching maxWordsPerLine at currentTime
  const maxWords = Math.max(1, subtitleStyle.maxWordsPerLine || 4);
  const candidateWords: TranscriptWord[] = [];

  if (subtitleStyle.translatedWords && subtitleStyle.translatedWords.length > 0) {
    candidateWords.push(...subtitleStyle.translatedWords);
  } else if (activeProject && activeProject.transcripts) {
    for (const seg of activeProject.transcripts) {
      if (currentTime >= seg.start - 0.5 && currentTime <= seg.end + 0.5) {
        if (seg.words && seg.words.length > 0) {
          candidateWords.push(...seg.words);
        } else if (seg.text?.trim()) {
          const toks = seg.text.trim().split(/\s+/);
          const step = Math.max(0.1, (seg.end - seg.start) / toks.length);
          candidateWords.push(
            ...toks.map((t, idx) => ({
              word: t,
              start: seg.start + idx * step,
              end: seg.start + (idx + 1) * step,
              probability: 1,
            }))
          );
        }
      }
    }
  }

  let currentWords: TranscriptWord[] = [];
  if (candidateWords.length > 0) {
    const chunks: TranscriptWord[][] = [];
    let cur: TranscriptWord[] = [];
    for (const w of candidateWords) {
      const prev = cur[cur.length - 1];
      const curChars = cur.reduce((acc, x) => acc + x.word.length, 0) + cur.length;
      if (
        cur.length > 0 &&
        (cur.length >= maxWords ||
          w.end - cur[0].start > 2.0 ||
          w.start - prev.end > 0.75 ||
          (curChars + w.word.length > 36 && cur.length >= 2) ||
          /[.!?।؟。！？]$/.test(prev.word))
      ) {
        chunks.push(cur);
        cur = [];
      }
      cur.push(w);
    }
    if (cur.length > 0) chunks.push(cur);

    const activeChunk = chunks.find(
      (ch) => currentTime >= ch[0].start - 0.15 && currentTime <= ch[ch.length - 1].end + 0.25
    );
    if (activeChunk) {
      currentWords = activeChunk;
    }
  }

  // Only show fallback demo words when viewing the explicit Demo Sample project
  const displayWords: TranscriptWord[] =
    currentWords.length > 0
      ? currentWords
      : activeProject?.isDemo
      ? [
          { word: "CHECK", start: currentTime - 0.4, end: currentTime + 0.2, probability: 0.99 },
          { word: "OUT", start: currentTime + 0.2, end: currentTime + 0.5, probability: 0.99 },
          { word: "THIS", start: currentTime + 0.5, end: currentTime + 0.9, probability: 0.98 },
          { word: "PLAY!", start: currentTime + 0.9, end: currentTime + 1.4, probability: 0.99 },
        ]
      : [];

  const sourceUrl =
    videoUrl ||
    activeProject?.localVideoUrl ||
    '';

  return (
    <div className="relative mx-auto w-full max-w-[340px] aspect-[9/16] rounded-3xl overflow-hidden bg-black border-4 border-[#252a3d] shadow-2xl shadow-purple-950/40 select-none ring-1 ring-white/10">
      {/* 9:16 Canvas Content based on Layout Preset */}

      {/* 1. Default Layout: Facecam TOP (37.5% ~720px) + Gameplay BOTTOM (62.5% ~1200px / ~3:4 ratio) */}
      {isFacecamGameplay && (
        <div className="w-full h-full flex flex-col">
          {/* Top: Facecam Region (37.5% of vertical height) */}
          <div
            className="w-full relative overflow-hidden bg-slate-900 border-b-2 border-purple-500/40"
            style={{ height: `${layoutConfig.facecamHeightPercent}%` }}
          >
            {sourceUrl ? (
              <video
                ref={facecamVideoRef}
                src={sourceUrl}
                muted
                playsInline
                onLoadedMetadata={handleSecondaryLoadedMetadata}
                className="w-full h-full object-cover transition-transform duration-75"
                style={{
                  transform: `scale(${layoutConfig.facecamZoom}) translateY(${layoutConfig.facecamOffsetY}%)`,
                  transformOrigin: 'top center',
                }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
                No video loaded
              </div>
            )}
            {/* Visual crop badge */}
            <div className="absolute top-2.5 left-2.5 px-2 py-0.5 rounded-md bg-black/60 backdrop-blur-md text-[9px] font-bold tracking-wider text-purple-300 border border-purple-500/30 uppercase">
              Facecam Top (Crop)
            </div>
          </div>

          {/* Bottom: Gameplay Region (62.5% ~3:4 proportion) */}
          <div
            className="w-full relative overflow-hidden bg-slate-950 flex-1"
            style={{ height: `${layoutConfig.gameplayHeightPercent}%` }}
          >
            {sourceUrl ? (
              <video
                ref={gameplayVideoRef}
                src={sourceUrl}
                muted={effectiveMuted}
                playsInline
                onLoadedMetadata={handlePrimaryLoadedMetadata}
                onTimeUpdate={handlePrimaryTimeUpdate}
                onEnded={handlePrimaryEnded}
                className="w-full h-full object-cover transition-transform duration-75"
                style={{
                  transform: `scale(${layoutConfig.gameplayZoom}) translateY(${layoutConfig.gameplayOffsetY}%)`,
                  transformOrigin: 'center center',
                }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
                No video loaded
              </div>
            )}
            {/* Visual crop badge */}
            <div className="absolute top-2.5 left-2.5 px-2 py-0.5 rounded-md bg-black/60 backdrop-blur-md text-[9px] font-bold tracking-wider text-cyan-300 border border-cyan-500/30 uppercase">
              Gameplay ~3:4 (Crop)
            </div>
          </div>
        </div>
      )}

      {/* 2. Alternative: Smart Vertical Crop / Custom / Center Crop */}
      {isSingleCrop && (
        <div className="w-full h-full relative overflow-hidden bg-black">
          {sourceUrl ? (
            <video
              ref={facecamVideoRef}
              src={sourceUrl}
              muted={effectiveMuted}
              playsInline
              onLoadedMetadata={handlePrimaryLoadedMetadata}
              onTimeUpdate={handlePrimaryTimeUpdate}
              onEnded={handlePrimaryEnded}
              className="w-full h-full object-cover"
              style={{
                transform: `scale(${layoutConfig.gameplayZoom}) translate(${layoutConfig.gameplayOffsetX ?? 0}%, ${layoutConfig.gameplayOffsetY}%)`,
              }}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
              No video loaded
            </div>
          )}
          <div className="absolute top-2.5 left-2.5 px-2 py-0.5 rounded-md bg-black/60 backdrop-blur-md text-[9px] font-bold tracking-wider text-cyan-300 border border-cyan-500/30 uppercase">
            {layoutConfig.preset === 'smart_crop'
              ? 'Smart 9:16 Dynamic Crop'
              : layoutConfig.preset === 'custom'
              ? 'Custom 9:16 Crop'
              : '9:16 Center Crop'}
          </div>
        </div>
      )}

      {/* 2b. Alternative: Full-Screen Video (16:9 preserved on blurred 9:16 canvas) */}
      {isFullscreen && (
        <div className="w-full h-full relative overflow-hidden bg-slate-950 flex items-center justify-center">
          {sourceUrl && (
            <video
              ref={facecamVideoRef}
              src={sourceUrl}
              muted
              playsInline
              onLoadedMetadata={handleSecondaryLoadedMetadata}
              className="absolute inset-0 w-full h-full object-cover blur-xl opacity-50 scale-110"
            />
          )}
          {sourceUrl ? (
            <video
              ref={gameplayVideoRef}
              src={sourceUrl}
              muted={effectiveMuted}
              playsInline
              onLoadedMetadata={handlePrimaryLoadedMetadata}
              onTimeUpdate={handlePrimaryTimeUpdate}
              onEnded={handlePrimaryEnded}
              className="relative z-10 w-full aspect-video object-contain shadow-2xl border-y border-white/10"
              style={{
                transform: `scale(${layoutConfig.gameplayZoom}) translateY(${layoutConfig.gameplayOffsetY}%)`,
              }}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
              No video loaded
            </div>
          )}
          <div className="absolute top-2.5 left-2.5 z-20 px-2 py-0.5 rounded-md bg-black/60 backdrop-blur-md text-[9px] font-bold tracking-wider text-indigo-300 border border-indigo-500/30 uppercase">
            Full-Screen Blurred Fit
          </div>
        </div>
      )}

      {/* 3. Alternative: Split 50/50 */}
      {isSplit50 && (
        <div className="w-full h-full flex flex-col">
          <div className="w-full h-1/2 relative overflow-hidden border-b-2 border-purple-500/30">
            {sourceUrl && (
              <video
                ref={facecamVideoRef}
                src={sourceUrl}
                muted
                playsInline
                onLoadedMetadata={handleSecondaryLoadedMetadata}
                className="w-full h-full object-cover"
                style={{ transform: `scale(${layoutConfig.facecamZoom})` }}
              />
            )}
            <div className="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-black/60 text-[9px] text-purple-300 font-bold">
              Facecam 50%
            </div>
          </div>
          <div className="w-full h-1/2 relative overflow-hidden">
            {sourceUrl && (
              <video
                ref={gameplayVideoRef}
                src={sourceUrl}
                muted={effectiveMuted}
                playsInline
                onLoadedMetadata={handlePrimaryLoadedMetadata}
                onTimeUpdate={handlePrimaryTimeUpdate}
                onEnded={handlePrimaryEnded}
                className="w-full h-full object-cover"
                style={{ transform: `scale(${layoutConfig.gameplayZoom})` }}
              />
            )}
            <div className="absolute top-2 left-2 px-1.5 py-0.5 rounded bg-black/60 text-[9px] text-cyan-300 font-bold">
              Content 50%
            </div>
          </div>
        </div>
      )}

      {/* 4. Alternative: Gameplay Full + Facecam PiP */}
      {isGameplayPip && (
        <div className="w-full h-full relative overflow-hidden bg-black">
          {sourceUrl && (
            <video
              ref={gameplayVideoRef}
              src={sourceUrl}
              muted={effectiveMuted}
              playsInline
              onLoadedMetadata={handlePrimaryLoadedMetadata}
              onTimeUpdate={handlePrimaryTimeUpdate}
              onEnded={handlePrimaryEnded}
              className="w-full h-full object-cover"
            />
          )}
          {/* PiP overlay badge */}
          <div className="absolute bottom-16 right-4 w-28 h-28 rounded-2xl overflow-hidden border-2 border-purple-400 shadow-2xl bg-black">
            {sourceUrl && (
              <video
                ref={facecamVideoRef}
                src={sourceUrl}
                muted
                playsInline
                onLoadedMetadata={handleSecondaryLoadedMetadata}
                className="w-full h-full object-cover scale-125"
              />
            )}
            <div className="absolute top-1 left-1 px-1 py-0.5 rounded bg-black/70 text-[8px] text-purple-300 font-bold">
              Facecam PiP
            </div>
          </div>
        </div>
      )}

      {/* Preview Approximation Clarification Notice */}
      <div className="absolute bottom-2 inset-x-2 px-2 py-1 rounded-lg bg-black/75 backdrop-blur-sm border border-white/10 flex items-center justify-center gap-1.5 text-[9px] text-slate-300 z-10 pointer-events-none">
        <Info className="w-3 h-3 text-cyan-400 shrink-0" />
        <span className="truncate">Preview Approximation: Source re-framed for 9:16 layout</span>
      </div>

      {/* Animated Word-Level Subtitles Overlay (hidden when subtitles are turned OFF) */}
      {subtitleStyle.enabled !== false && displayWords.length > 0 && (
      <div
        className="absolute inset-x-3 pointer-events-none flex justify-center text-center transition-all duration-100"
        style={{ top: `${subtitleStyle.positionY}%` }}
      >
        <div
          dir={displayWords.some((w) => /[\u0600-\u06FF]/.test(w.word)) ? 'rtl' : 'auto'}
          className="inline-flex flex-wrap items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl transition-all max-w-[90%]"
          style={{
            backgroundColor: subtitleStyle.hasBackground ? subtitleStyle.backgroundColor : 'transparent',
            backdropFilter: subtitleStyle.hasBackground ? 'blur(4px)' : 'none',
          }}
        >
          {displayWords.map((w, idx) => {
            const isWordActive = currentTime >= w.start && currentTime <= w.end;
            const anim = subtitleStyle.animation || 'pop';
            const isLatinWord = /^[A-Za-z0-9\s.,!?'":;\-()]+$/.test(w.word);
            const resolvedPreviewFont = /[\u0900-\u0D7F]/.test(w.word)
              ? '"Nirmala UI", sans-serif'
              : /[\u0600-\u06FF]/.test(w.word)
              ? '"Segoe UI", sans-serif'
              : /[\uAC00-\uD7AF]/.test(w.word)
              ? '"Malgun Gothic", sans-serif'
              : /[\u3040-\u30FF\u4E00-\u9FFF]/.test(w.word)
              ? '"MS Gothic", sans-serif'
              : subtitleStyle.fontFamily;

            let activeAnimClass = 'scale-110 drop-shadow-[0_4px_12px_rgba(255,223,0,0.85)]';
            if (anim === 'bounce') {
              activeAnimClass = 'scale-125 -translate-y-0.5 drop-shadow-[0_4px_16px_rgba(34,197,94,0.9)]';
            } else if (anim === 'scale_glow') {
              activeAnimClass = 'scale-115 drop-shadow-[0_4px_16px_rgba(217,70,239,0.95)]';
            } else if (anim === 'fade') {
              activeAnimClass = 'scale-105 opacity-100 drop-shadow-[0_2px_8px_rgba(56,189,248,0.8)]';
            } else if (anim === 'none') {
              activeAnimClass = 'scale-100 opacity-100';
            }

            return (
              <span
                key={idx}
                className={`font-black tracking-wide transition-all duration-150 inline-block ${
                  subtitleStyle.isUppercase && isLatinWord ? 'uppercase' : ''
                } ${
                  isWordActive ? activeAnimClass : 'opacity-90'
                }`}
                style={{
                  fontFamily: resolvedPreviewFont,
                  color: isWordActive ? subtitleStyle.highlightColor : subtitleStyle.textColor,
                  fontSize:
                    subtitleStyle.fontSize === 'sm'
                      ? '15px'
                      : subtitleStyle.fontSize === 'md'
                      ? '19px'
                      : subtitleStyle.fontSize === 'lg'
                      ? '23px'
                      : '27px',
                  textShadow:
                    '2.5px 2.5px 0 #000, -2.5px -2.5px 0 #000, 2.5px -2.5px 0 #000, -2.5px 2.5px 0 #000, 0 4px 10px rgba(0,0,0,0.95)',
                }}
              >
                {w.word}
              </span>
            );
          })}
        </div>
      </div>
      )}

      {/* Top right timecode badge */}
      <div className="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-black/70 backdrop-blur-md text-[10px] font-mono text-white/90 border border-white/10">
        9:16 • {currentTime.toFixed(1)}s
      </div>
    </div>
  );
};
