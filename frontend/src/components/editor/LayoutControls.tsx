import React from 'react';
import {
  LayoutTemplate,
  Maximize2,
  Columns,
  PictureInPicture,
  RotateCcw,
  Sliders,
  MoveVertical,
  ZoomIn,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import type { LayoutPreset } from '../../types';

export const LayoutControls: React.FC = () => {
  const { layoutConfig, setLayoutConfig, showToast } = useApp();

  const presets: { id: LayoutPreset; label: string; desc: string; icon: React.ReactNode; isDefault?: boolean }[] = [
    {
      id: 'facecam_gameplay',
      label: 'Facecam + 3:4 Play',
      desc: 'Facecam TOP + Gameplay BOTTOM (3:4 ratio)',
      icon: <LayoutTemplate className="w-5 h-5 text-purple-400" />,
      isDefault: true,
    },
    {
      id: 'smart_crop',
      label: 'Smart Vertical Crop',
      desc: 'Dynamic face/subject tracking & reframe',
      icon: <Maximize2 className="w-5 h-5 text-cyan-400" />,
    },
    {
      id: 'fullscreen',
      label: 'Full-Screen Video',
      desc: 'Full 16:9 frame on blurred 9:16 canvas',
      icon: <Columns className="w-5 h-5 text-indigo-400" />,
    },
    {
      id: 'gameplay_pip',
      label: 'Facecam PiP',
      desc: '9:16 video with corner facecam overlay',
      icon: <PictureInPicture className="w-5 h-5 text-emerald-400" />,
    },
    {
      id: 'custom',
      label: 'Custom Crop',
      desc: 'Freeform manual zoom & pan crop',
      icon: <Sliders className="w-5 h-5 text-amber-400" />,
    },
    {
      id: 'split_50_50',
      label: 'Equal 50/50 Split',
      desc: 'Top and bottom equal halves',
      icon: <Columns className="w-5 h-5 text-pink-400" />,
    },
  ];

  const handlePresetChange = (preset: LayoutPreset) => {
    if (preset === 'facecam_gameplay') {
      setLayoutConfig({
        preset: 'facecam_gameplay',
        facecamHeightPercent: 25,
        gameplayHeightPercent: 75,
        facecamOffsetX: 0,
        facecamOffsetY: 0,
        facecamZoom: 1.15,
        gameplayOffsetX: 0,
        gameplayOffsetY: 0,
        gameplayZoom: 1.0,
        pipScale: 28,
        pipCorner: 'bottom_right',
      });
    } else {
      setLayoutConfig((prev) => ({
        ...prev,
        preset,
      }));
    }
    showToast(`Applied "${preset.replace('_', ' ')}" layout preset`);
  };

  const handleReset = () => {
    setLayoutConfig({
      preset: 'facecam_gameplay',
      facecamHeightPercent: 25,
      gameplayHeightPercent: 75,
      facecamOffsetX: 0,
      facecamOffsetY: 0,
      facecamZoom: 1.15,
      gameplayOffsetX: 0,
      gameplayOffsetY: 0,
      gameplayZoom: 1.0,
      pipScale: 28,
      pipCorner: 'bottom_right',
    });
    showToast('Reset to default Facecam + 3:4 Gameplay layout');
  };

  return (
    <div className="space-y-6">
      {/* Preset Selector */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
            <LayoutTemplate className="w-4 h-4 text-purple-400" />
            Video Composition Presets
          </label>
          <button
            onClick={handleReset}
            className="text-[11px] text-slate-400 hover:text-white flex items-center gap-1 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Reset Default</span>
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          {presets.map((p) => {
            const isSelected = layoutConfig.preset === p.id;
            return (
              <button
                key={p.id}
                onClick={() => handlePresetChange(p.id)}
                className={`p-3 rounded-2xl border text-left transition-all relative overflow-hidden group ${
                  isSelected
                    ? 'bg-purple-600/15 border-purple-500 shadow-md shadow-purple-950/20'
                    : 'bg-[#12141c] border-[#212638] hover:border-slate-700'
                }`}
              >
                {p.isDefault && (
                  <span className="absolute top-2 right-2 text-[9px] font-bold px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 uppercase">
                    Default
                  </span>
                )}
                <div className="flex items-center gap-2.5">
                  <div className="p-1.5 rounded-lg bg-[#0e1017] border border-[#1f2436]">
                    {p.icon}
                  </div>
                  <div>
                    <h5 className="text-xs font-bold text-white group-hover:text-purple-300 transition-colors">
                      {p.label}
                    </h5>
                    <p className="text-[10px] text-slate-400 mt-0.5 line-clamp-1">{p.desc}</p>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Manual Crop Adjustments (Available across all presets) */}
      <div className="p-4 rounded-2xl bg-[#12141c] border border-[#212638] space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5 text-cyan-400" />
            Manual Crop & Reframing Adjustments
          </span>
          {layoutConfig.preset === 'facecam_gameplay' && (
            <span className="text-[10px] font-mono text-purple-400">
              {Math.round(layoutConfig.facecamHeightPercent)}% / {Math.round(layoutConfig.gameplayHeightPercent)}% (3:4)
            </span>
          )}
        </div>

        {layoutConfig.preset === 'facecam_gameplay' && (
          <div className="space-y-1.5">
            <div className="flex justify-between text-[11px] text-slate-400">
              <span className="flex items-center gap-1">
                <MoveVertical className="w-3 h-3 text-purple-400" />
                Facecam Height (TOP)
              </span>
              <span className="font-mono text-slate-300">{Math.round(layoutConfig.facecamHeightPercent)}%</span>
            </div>
            <input
              type="range"
              min="20"
              max="45"
              step="1"
              value={layoutConfig.facecamHeightPercent}
              onChange={(e) => {
                const val = parseFloat(e.target.value);
                setLayoutConfig((prev) => ({
                  ...prev,
                  facecamHeightPercent: val,
                  gameplayHeightPercent: 100 - val,
                }));
              }}
              className="w-full accent-purple-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
            />
          </div>
        )}

        {(layoutConfig.preset === 'facecam_gameplay' ||
          layoutConfig.preset === 'gameplay_pip' ||
          layoutConfig.preset === 'split_50_50') && (
          <>
            {/* Facecam Zoom */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <ZoomIn className="w-3 h-3 text-purple-400" />
                  Facecam Scale / Zoom
                </span>
                <span className="font-mono text-slate-300">{layoutConfig.facecamZoom.toFixed(2)}x</span>
              </div>
              <input
                type="range"
                min="1.0"
                max="2.5"
                step="0.05"
                value={layoutConfig.facecamZoom}
                onChange={(e) =>
                  setLayoutConfig((prev) => ({
                    ...prev,
                    facecamZoom: parseFloat(e.target.value),
                  }))
                }
                className="w-full accent-purple-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
              />
            </div>

            {/* Facecam Vertical Offset */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-[11px] text-slate-400">
                <span>Facecam Pan Y</span>
                <span className="font-mono text-slate-300">{layoutConfig.facecamOffsetY}%</span>
              </div>
              <input
                type="range"
                min="-40"
                max="40"
                step="2"
                value={layoutConfig.facecamOffsetY}
                onChange={(e) =>
                  setLayoutConfig((prev) => ({
                    ...prev,
                    facecamOffsetY: parseFloat(e.target.value),
                  }))
                }
                className="w-full accent-purple-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
              />
            </div>
            <div className="h-px bg-[#1c2030]" />
          </>
        )}

        {/* Primary / Gameplay Zoom */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-[11px] text-slate-400">
            <span className="flex items-center gap-1">
              <ZoomIn className="w-3 h-3 text-cyan-400" />
              Main / Gameplay Scale
            </span>
            <span className="font-mono text-slate-300">{layoutConfig.gameplayZoom.toFixed(2)}x</span>
          </div>
          <input
            type="range"
            min="1.0"
            max="2.5"
            step="0.05"
            value={layoutConfig.gameplayZoom}
            onChange={(e) =>
              setLayoutConfig((prev) => ({
                ...prev,
                gameplayZoom: parseFloat(e.target.value),
              }))
            }
            className="w-full accent-cyan-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
          />
        </div>

        {/* Main Horizontal Offset */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-[11px] text-slate-400">
            <span>Main / Gameplay Pan X</span>
            <span className="font-mono text-slate-300">{layoutConfig.gameplayOffsetX ?? 0}%</span>
          </div>
          <input
            type="range"
            min="-40"
            max="40"
            step="2"
            value={layoutConfig.gameplayOffsetX ?? 0}
            onChange={(e) =>
              setLayoutConfig((prev) => ({
                ...prev,
                gameplayOffsetX: parseFloat(e.target.value),
              }))
            }
            className="w-full accent-cyan-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
          />
        </div>

        {/* Gameplay Vertical Offset */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-[11px] text-slate-400">
            <span>Main / Gameplay Pan Y</span>
            <span className="font-mono text-slate-300">{layoutConfig.gameplayOffsetY}%</span>
          </div>
          <input
            type="range"
            min="-40"
            max="40"
            step="2"
            value={layoutConfig.gameplayOffsetY}
            onChange={(e) =>
              setLayoutConfig((prev) => ({
                ...prev,
                gameplayOffsetY: parseFloat(e.target.value),
              }))
            }
            className="w-full accent-cyan-500 bg-[#0b0c10] rounded-lg h-2 cursor-pointer"
          />
        </div>
      </div>
    </div>
  );
};
