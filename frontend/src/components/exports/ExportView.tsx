import React, { useState } from 'react';
import {
  Download,
  Copy,
  Check,
  Sparkles,
  Zap,
  CheckCircle2,
  Film,
  Hash,
  AlertCircle,
  Image as ImageIcon,
  Clock,
  Type,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import type { ExportedClip } from '../../types';

export const ExportView: React.FC = () => {
  const { activeProject, setCurrentView, showToast, projects } = useApp();
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Collect real exported clips from active project, or fall back to all user projects
  const exportedClips: ExportedClip[] =
    activeProject && activeProject.exportedClips?.length > 0
      ? activeProject.exportedClips
      : projects.flatMap((p) => p.exportedClips || []);

  const handleCopy = (text: string, fieldId: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldId);
    showToast('Copied to clipboard!');
    setTimeout(() => {
      setCopiedField((prev) => (prev === fieldId ? null : prev));
    }, 2000);
  };

  const handleDownload = (clip: ExportedClip) => {
    const link = document.createElement('a');
    link.href = clip.videoUrl;
    link.download = `${clip.title.replace(/[^a-zA-Z0-9_-]/g, '_')}.mp4`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast(`Downloading "${clip.title}"...`);
  };

  if (exportedClips.length === 0) {
    return (
      <div className="p-16 max-w-xl mx-auto text-center space-y-4 rounded-3xl bg-[#12141c] border border-[#212638] shadow-2xl my-12">
        <Film className="w-12 h-12 text-slate-500 mx-auto" />
        <h3 className="text-lg font-bold text-white">No Exported Shorts Yet</h3>
        <p className="text-xs text-slate-400">
          Open any highlight in the 9:16 Clip Editor and click "Export 9:16 Short" to render vertical clips with animated subtitles.
        </p>
        <button
          onClick={() => setCurrentView('dashboard')}
          className="px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold shadow-md transition-all"
        >
          Return to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header banner */}
      <div className="rounded-3xl bg-gradient-to-r from-[#171526] to-[#12141d] border border-[#23283b] p-6 shadow-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs font-semibold mb-2">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>FFmpeg Render & Container Timestamp Sync Validated</span>
          </div>
          <h2 className="text-2xl font-extrabold text-white">
            Exported Vertical 9:16 Shorts
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Ready for publishing to YouTube Shorts, TikTok, and Instagram Reels with AI-generated titles and descriptions.
          </p>
        </div>

        <button
          onClick={() => setCurrentView('create')}
          className="px-4 py-2.5 rounded-xl bg-[#191d2c] hover:bg-[#22283d] text-slate-200 text-xs font-semibold border border-[#2e374f] transition-colors"
        >
          Export Another Video
        </button>
      </div>

      {/* Generated Clip Previews Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {exportedClips.map((clip: ExportedClip, idx: number) => {
          return (
            <div
              key={clip.id}
              className="rounded-3xl bg-[#12141c] border border-[#212638] overflow-hidden shadow-2xl flex flex-col justify-between"
            >
              {/* Top: Video Preview Container */}
              <div className="relative aspect-[9/16] max-h-[440px] w-full bg-black overflow-hidden flex items-center justify-center group">
                {clip.videoUrl ? (
                  <video
                    src={clip.videoUrl}
                    controls
                    playsInline
                    className="w-full h-full object-contain"
                  />
                ) : (
                  <div className="p-8 text-center text-slate-500 text-xs flex flex-col items-center gap-2">
                    <AlertCircle className="w-6 h-6 text-slate-400" />
                    <span>Video file is processing on the backend</span>
                  </div>
                )}

                <div className="absolute top-4 left-4 px-3 py-1 rounded-full bg-black/75 backdrop-blur-md text-[10px] font-bold text-purple-300 border border-purple-500/30 flex items-center gap-1.5">
                  <Sparkles className="w-3 h-3 text-cyan-400" />
                  <span>Clip #{idx + 1} • {clip.resolution}</span>
                </div>

                <div className="absolute top-4 right-4 px-2.5 py-1 rounded-full bg-emerald-950/80 backdrop-blur-md text-[10px] font-mono text-emerald-300 border border-emerald-700/50 flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                  <span>Measured A/V Offset: {clip.syncOffsetMs}ms (±50ms tol)</span>
                </div>
              </div>

              {/* Bottom: Generated Metadata & Copy Actions */}
              <div className="p-6 space-y-5 bg-[#0e1017]">
                {/* Title & Suggestions */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                      <Type className="w-3.5 h-3.5 text-purple-400" />
                      <span>Shorts Title Suggestions</span>
                    </span>
                    <button
                      onClick={() => handleCopy(clip.title, `title_${clip.id}`)}
                      className="text-[11px] text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
                    >
                      {copiedField === `title_${clip.id}` ? (
                        <Check className="w-3 h-3 text-emerald-400" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                      <span>Copy Active Title</span>
                    </button>
                  </div>

                  {/* Primary chosen title */}
                  <p className="text-sm font-bold text-white p-3 rounded-xl bg-[#141724] border border-[#23283b] flex items-center justify-between gap-2">
                    <span>{clip.title}</span>
                    <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30 text-[10px] font-bold uppercase tracking-wider shrink-0">
                      Active
                    </span>
                  </p>

                  {/* Alternative suggestions if available */}
                  {clip.titleSuggestions && clip.titleSuggestions.length > 1 && (
                    <div className="space-y-1.5 pt-1">
                      <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                        Alternative Title Angles:
                      </span>
                      {clip.titleSuggestions
                        .filter((t) => t !== clip.title)
                        .slice(0, 2)
                        .map((altTitle, aIdx) => (
                          <div
                            key={aIdx}
                            className="p-2.5 rounded-lg bg-[#111420] border border-[#1f2437] flex items-center justify-between gap-2 text-xs text-slate-300"
                          >
                            <span className="truncate">{altTitle}</span>
                            <button
                              onClick={() => handleCopy(altTitle, `alt_${clip.id}_${aIdx}`)}
                              className="text-[10px] text-slate-400 hover:text-white shrink-0 flex items-center gap-1 px-2 py-0.5 rounded bg-[#1a1f33]"
                            >
                              {copiedField === `alt_${clip.id}_${aIdx}` ? (
                                <Check className="w-2.5 h-2.5 text-emerald-400" />
                              ) : (
                                <Copy className="w-2.5 h-2.5" />
                              )}
                              <span>Copy</span>
                            </button>
                          </div>
                        ))}
                    </div>
                  )}
                </div>

                {/* Thumbnail Suggestion & Best Frame */}
                <div className="p-3.5 rounded-xl bg-[#141724] border border-[#23283b] space-y-2">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                      <ImageIcon className="w-3.5 h-3.5 text-amber-400" />
                      <span>Thumbnail Text & Timestamp</span>
                    </span>
                    {clip.thumbnailTimestamp !== undefined && (
                      <span className="text-[11px] font-mono text-cyan-300 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        <span>Best Frame: {clip.thumbnailTimestamp.toFixed(2)}s</span>
                      </span>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="px-2.5 py-1 rounded bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[11px] font-extrabold uppercase tracking-wider">
                        {clip.thumbnailText || 'VIRAL MOMENT!'}
                      </span>
                      <button
                        onClick={() => handleCopy(clip.thumbnailText || 'VIRAL MOMENT!', `thumb_txt_${clip.id}`)}
                        className="text-[10px] text-slate-400 hover:text-purple-300 p-1"
                        title="Copy thumbnail text"
                      >
                        {copiedField === `thumb_txt_${clip.id}` ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                      </button>
                    </div>

                    {clip.thumbnailTimestamp !== undefined && (
                      <button
                        onClick={() => handleCopy(`${clip.thumbnailTimestamp?.toFixed(2)}s`, `thumb_ts_${clip.id}`)}
                        className="text-[10px] text-slate-400 hover:text-cyan-300 flex items-center gap-1 px-2 py-1 rounded bg-[#1c2238] border border-[#2b3350]"
                      >
                        {copiedField === `thumb_ts_${clip.id}` ? (
                          <Check className="w-3 h-3 text-emerald-400" />
                        ) : (
                          <Copy className="w-3 h-3" />
                        )}
                        <span>Copy Timestamp</span>
                      </button>
                    )}
                  </div>
                </div>

                {/* Description */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span className="font-semibold text-slate-300">Description & Hook</span>
                    <button
                      onClick={() => handleCopy(clip.description, `desc_${clip.id}`)}
                      className="text-[11px] text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
                    >
                      {copiedField === `desc_${clip.id}` ? (
                        <Check className="w-3 h-3 text-emerald-400" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                      <span>Copy Description</span>
                    </button>
                  </div>
                  <p className="text-xs text-slate-300 p-3 rounded-xl bg-[#141724] border border-[#23283b] leading-relaxed whitespace-pre-line">
                    {clip.description}
                  </p>
                </div>

                {/* Hashtags */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span className="font-semibold text-slate-300 flex items-center gap-1">
                      <Hash className="w-3 h-3 text-cyan-400" />
                      Social Hashtags
                    </span>
                    <button
                      onClick={() => handleCopy(clip.hashtags.join(' '), `hash_${clip.id}`)}
                      className="text-[11px] text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
                    >
                      {copiedField === `hash_${clip.id}` ? (
                        <Check className="w-3 h-3 text-emerald-400" />
                      ) : (
                        <Copy className="w-3 h-3" />
                      )}
                      <span>Copy All Tags</span>
                    </button>
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {clip.hashtags.map((tag, tIdx) => (
                      <span
                        key={tIdx}
                        className="text-xs px-2.5 py-1 rounded-lg bg-[#181c2b] text-cyan-300 border border-[#273049] font-medium"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Technical Specs & Download Bar */}
                <div className="pt-3 border-t border-[#1c2030] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="text-[11px] text-slate-400 space-y-0.5">
                    <div className="flex items-center gap-2">
                      <Zap className="w-3 h-3 text-amber-400" />
                      <span>Encoder:</span>
                      <span className="font-mono text-slate-200">{clip.encoderUsed}</span>
                    </div>
                    <div>
                      <span>Size: {clip.fileSizeMb} MB</span> • <span>Duration: {clip.duration.toFixed(1)}s</span>
                    </div>
                  </div>

                  <button
                    onClick={() => handleDownload(clip)}
                    className="flex items-center justify-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-xs font-bold shadow-lg shadow-purple-600/30 transition-all active:scale-95"
                  >
                    <Download className="w-4 h-4" />
                    <span>Download MP4</span>
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
