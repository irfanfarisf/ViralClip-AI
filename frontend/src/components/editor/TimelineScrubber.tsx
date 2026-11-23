import React from 'react';
import {
  Play,
  Pause,
  RotateCcw,
  Scissors,
  Volume2,
  VolumeX,
} from 'lucide-react';

interface TimelineScrubberProps {
  startTime: number;
  endTime: number;
  currentTime: number;
  maxDuration: number;
  isPlaying: boolean;
  isMuted?: boolean;
  volume?: number;
  hasAudio?: boolean;
  onPlayPause: () => void;
  onToggleMute?: () => void;
  onVolumeChange?: (volume: number) => void;
  onSeek: (time: number) => void;
  onAdjustStart: (delta: number) => void;
  onAdjustEnd: (delta: number) => void;
}

export const TimelineScrubber: React.FC<TimelineScrubberProps> = ({
  startTime,
  endTime,
  currentTime,
  maxDuration,
  isPlaying,
  isMuted = false,
  volume = 1,
  hasAudio = true,
  onPlayPause,
  onToggleMute,
  onVolumeChange,
  onSeek,
  onAdjustStart,
  onAdjustEnd,
}) => {
  const duration = Math.max(0.5, endTime - startTime);

  // Generate simulated audio waveform bars
  const barsCount = 48;
  const waveformHeights = [
    30, 45, 60, 85, 40, 70, 95, 100, 65, 80, 50, 35, 60, 90, 75, 40,
    65, 85, 100, 90, 70, 50, 80, 95, 60, 40, 75, 90, 85, 60, 45, 70,
    95, 80, 60, 35, 50, 75, 100, 85, 40, 65, 80, 95, 70, 50, 40, 30,
  ];

  return (
    <div className="p-5 rounded-3xl bg-[#12141c] border border-[#212638] space-y-4 shadow-xl">
      {/* Header controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2">
          <button
            onClick={onPlayPause}
            className="p-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white shadow-md shadow-purple-900/30 transition-all flex items-center gap-1.5 font-bold"
          >
            {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
            <span>{isPlaying ? 'Pause' : 'Play 9:16'}</span>
          </button>

          <button
            onClick={() => onSeek(startTime)}
            title="Loop from clip start"
            className="p-2.5 rounded-xl bg-[#181b28] hover:bg-[#202538] text-slate-300 hover:text-white transition-colors"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          {hasAudio ? (
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-xl bg-[#181b28] border border-[#23283b]">
              <button
                type="button"
                onClick={onToggleMute}
                title={isMuted || volume === 0 ? 'Unmute audio' : 'Mute audio'}
                className="text-slate-300 hover:text-white transition-colors"
              >
                {isMuted || volume === 0 ? (
                  <VolumeX className="w-4 h-4 text-red-400" />
                ) : (
                  <Volume2 className="w-4 h-4 text-cyan-400" />
                )}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                aria-label="Preview volume"
                value={isMuted ? 0 : volume}
                onChange={(e) => onVolumeChange?.(parseFloat(e.target.value))}
                className="w-16 sm:w-20 accent-cyan-400 cursor-pointer h-1.5"
              />
            </div>
          ) : (
            <span className="flex items-center gap-1 px-2.5 py-1.5 rounded-xl bg-[#181b28] border border-[#23283b] text-[11px] text-slate-400">
              <VolumeX className="w-3.5 h-3.5 text-slate-500" />
              <span>No audio</span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1 text-slate-400">
            <span>Clip Span:</span>
            <span className="text-purple-300 font-bold text-sm">{duration.toFixed(1)}s</span>
          </div>
          <div className="flex items-center gap-1 text-slate-400">
            <span>Scrub:</span>
            <span className="text-cyan-400 font-bold">{currentTime.toFixed(1)}s</span>
          </div>
        </div>

        {/* Fine duration adjustment buttons */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-400">Trim End:</span>
          <button
            onClick={() => onAdjustEnd(-0.5)}
            className="px-2 py-1 rounded-lg bg-[#181b28] hover:bg-[#22273a] text-slate-300 text-xs font-mono font-bold border border-[#2b3147]"
          >
            -0.5s
          </button>
          <button
            onClick={() => onAdjustEnd(+0.5)}
            className="px-2 py-1 rounded-lg bg-[#181b28] hover:bg-[#22273a] text-slate-300 text-xs font-mono font-bold border border-[#2b3147]"
          >
            +0.5s
          </button>
        </div>
      </div>

      {/* Visual Waveform + Scrub Track */}
      <div className="relative pt-2 pb-1">
        <div
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            const percent = Math.max(0, Math.min(1, clickX / rect.width));
            onSeek(percent * maxDuration);
          }}
          className="relative h-14 w-full bg-[#0b0c10] rounded-2xl border border-[#1f2436] p-2 flex items-center justify-between gap-1 overflow-hidden cursor-pointer"
        >
          {/* Active Highlight Selection Band */}
          <div
            className="absolute top-0 bottom-0 bg-purple-600/20 border-x-2 border-purple-400 z-0 pointer-events-none transition-all duration-75"
            style={{
              left: `${(startTime / maxDuration) * 100}%`,
              width: `${((endTime - startTime) / maxDuration) * 100}%`,
            }}
          />

          {/* Current playhead indicator */}
          <div
            className="absolute top-0 bottom-0 w-1 bg-cyan-400 shadow-[0_0_12px_#06b6d4] z-10 pointer-events-none transition-all duration-75"
            style={{ left: `${(currentTime / maxDuration) * 100}%` }}
          >
            <div className="w-3 h-3 rounded-full bg-cyan-400 -ml-1 -mt-1 shadow-md" />
          </div>

          {/* Audio Waveform Bars */}
          {waveformHeights.map((h, i) => {
            const barPositionPercent = (i / barsCount) * 100;
            const inSelectedClip =
              barPositionPercent >= (startTime / maxDuration) * 100 &&
              barPositionPercent <= (endTime / maxDuration) * 100;

            return (
              <div
                key={i}
                className={`w-full rounded-full transition-colors duration-150 ${
                  inSelectedClip
                    ? 'bg-gradient-to-t from-purple-500 to-cyan-400 opacity-90'
                    : 'bg-[#1e2335] opacity-50'
                }`}
                style={{ height: `${h}%` }}
              />
            );
          })}
        </div>

        {/* Start / End Time Sliders */}
        <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <div className="flex items-center gap-1.5">
            <Scissors className="w-3.5 h-3.5 text-purple-400" />
            <span>Start: {startTime.toFixed(1)}s</span>
            <button
              onClick={() => onAdjustStart(-0.5)}
              className="px-1.5 py-0.5 rounded bg-[#181b28] text-slate-300"
            >
              -
            </button>
            <button
              onClick={() => onAdjustStart(0.5)}
              className="px-1.5 py-0.5 rounded bg-[#181b28] text-slate-300"
            >
              +
            </button>
          </div>

          <div className="flex items-center gap-1 text-slate-500">
            <Volume2 className="w-3.5 h-3.5" />
            <span>Word-boundary snap active</span>
          </div>

          <div className="flex items-center gap-1.5">
            <span>End: {endTime.toFixed(1)}s</span>
            <button
              onClick={() => onAdjustEnd(-0.5)}
              className="px-1.5 py-0.5 rounded bg-[#181b28] text-slate-300"
            >
              -
            </button>
            <button
              onClick={() => onAdjustEnd(0.5)}
              className="px-1.5 py-0.5 rounded bg-[#181b28] text-slate-300"
            >
              +
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
