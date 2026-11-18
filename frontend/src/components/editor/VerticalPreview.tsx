import React, { useRef, useEffect } from 'react';
import { Info } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import type { TranscriptWord } from '../../types';

interface VerticalPreviewProps {
  currentTime: number;
  isPlaying: boolean;
  onTimeUpdate?: (time: number) => void;
  videoUrl?: string;
}

export const VerticalPreview: React.FC<VerticalPreviewProps> = ({
  currentTime,
  isPlaying,
  videoUrl,
}) => {
  const { subtitleStyle, layoutConfig, activeProject } = useApp();
  const facecamVideoRef = useRef<HTMLVideoElement>(null);
  const gameplayVideoRef = useRef<HTMLVideoElement>(null);

  // Sync video elements with external play/pause & currentTime
  useEffect(() => {
    const syncVideo = (video: HTMLVideoElement | null) => {
      if (!video) return;
      if (Math.abs(video.currentTime - currentTime) > 0.3) {
        video.currentTime = currentTime;
      }
      if (isPlaying && video.paused) {
        video.play().catch(() => {});
      } else if (!isPlaying && !video.paused) {
        video.pause();
      }
    };

    syncVideo(facecamVideoRef.current);
    syncVideo(gameplayVideoRef.current);
  }, [currentTime, isPlaying]);

  // Find active transcript words based on current playback time
  const currentWords: TranscriptWord[] = [];

  if (subtitleStyle.translatedWords && subtitleStyle.translatedWords.length > 0) {
    const activeWords = subtitleStyle.translatedWords.filter(
      (w) => currentTime >= w.start - 0.25 && currentTime <= w.end + 0.25
    );
    if (activeWords.length > 0) {
      currentWords.push(...activeWords);
    }
  } else if (activeProject && activeProject.transcripts) {
    for (const seg of activeProject.transcripts) {
      if (currentTime >= seg.start - 0.2 && currentTime <= seg.end + 0.2) {
        if (seg.words && seg.words.length > 0) {
          currentWords.push(...seg.words);
        }
        break;
      }
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

  const isFacecamGameplay = layoutConfig.preset === 'facecam_gameplay';
  const isSingleCrop =
    layoutConfig.preset === 'smart_crop' ||
    layoutConfig.preset === 'center_crop' ||
    layoutConfig.preset === 'custom';
  const isFullscreen = layoutConfig.preset === 'fullscreen';
  const isGameplayPip = layoutConfig.preset === 'gameplay_pip';
  const isSplit50 = layoutConfig.preset === 'split_50_50';

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
                muted
                playsInline
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
              muted
              playsInline
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
              className="absolute inset-0 w-full h-full object-cover blur-xl opacity-50 scale-110"
            />
          )}
          {sourceUrl ? (
            <video
              ref={gameplayVideoRef}
              src={sourceUrl}
              muted
              playsInline
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
                muted
                playsInline
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
              muted
              playsInline
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

      {/* Animated Word-Level Subtitles Overlay */}
      <div
        className="absolute inset-x-3 pointer-events-none flex justify-center text-center transition-all duration-100"
        style={{ top: `${subtitleStyle.positionY}%` }}
      >
        <div
          className="inline-flex flex-wrap items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl transition-all max-w-[90%]"
          style={{
            backgroundColor: subtitleStyle.hasBackground ? subtitleStyle.backgroundColor : 'transparent',
            backdropFilter: subtitleStyle.hasBackground ? 'blur(4px)' : 'none',
          }}
        >
          {displayWords.map((w, idx) => {
            const isWordActive = currentTime >= w.start && currentTime <= w.end;
            const anim = subtitleStyle.animation || 'pop';

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
                  subtitleStyle.isUppercase ? 'uppercase' : ''
                } ${
                  isWordActive ? activeAnimClass : 'opacity-90'
                }`}
                style={{
                  fontFamily: subtitleStyle.fontFamily,
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

      {/* Top right timecode badge */}
      <div className="absolute top-3 right-3 px-2 py-0.5 rounded-full bg-black/70 backdrop-blur-md text-[10px] font-mono text-white/90 border border-white/10">
        9:16 • {currentTime.toFixed(1)}s
      </div>
    </div>
  );
};
