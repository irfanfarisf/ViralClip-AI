import React from 'react';
import { Sparkles, Plus, Zap, RefreshCw } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const Header: React.FC = () => {
  const { currentView, setCurrentView, backendStatus, refreshBackendStatus } = useApp();

  const titleMap: Record<string, { title: string; subtitle: string }> = {
    dashboard: {
      title: 'Studio Dashboard',
      subtitle: 'Create engaging vertical shorts from streams, gaming, and podcasts',
    },
    create: {
      title: 'Create New Shorts',
      subtitle: 'Import local files, YouTube VODs or Twitch recordings',
    },
    processing: {
      title: 'Video Processing & Detection',
      subtitle: 'Speech transcription, interesting-moment ranking, and highlight extraction',
    },
    editor: {
      title: 'Vertical 9:16 Clip Editor',
      subtitle: 'Facecam and gameplay layout, animated subtitles, and time scrubbing',
    },
    exports: {
      title: 'Export History & Downloads',
      subtitle: 'Preview rendered vertical clips, copy generated metadata, and download MP4',
    },
    projects: {
      title: 'Project Library',
      subtitle: 'Manage all imported long-form media and generated clips',
    },
    settings: {
      title: 'Application Settings',
      subtitle: 'Configure local Whisper models, encoder fallbacks, and optional AI keys',
    },
  };

  const currentInfo = titleMap[currentView] || {
    title: 'ViralClip AI',
    subtitle: 'Automated 9:16 vertical video studio',
  };

  return (
    <header className="h-20 border-b border-[#1f2333] px-8 bg-[#0b0c10]/95 backdrop-blur-md sticky top-0 z-20 flex items-center justify-between">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2.5">
          {currentInfo.title}
        </h1>
        <p className="text-xs text-slate-400 mt-0.5">{currentInfo.subtitle}</p>
      </div>

      <div className="flex items-center gap-3.5">
        {/* Hardware badge */}
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#141724] border border-[#23283b] text-xs text-slate-300">
          <Zap className="w-3.5 h-3.5 text-amber-400" />
          <span>Encoder:</span>
          <span className="font-mono text-purple-300 font-semibold">
            {backendStatus.gpuEncoder || 'Hardware probe'}
          </span>
          <button
            onClick={refreshBackendStatus}
            title="Probe Hardware Engine"
            className="ml-1 text-slate-400 hover:text-white transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        </div>

        {/* Action Button */}
        <button
          onClick={() => setCurrentView('create')}
          className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 via-indigo-600 to-cyan-500 hover:from-purple-500 hover:to-cyan-400 text-white text-xs font-semibold shadow-lg shadow-purple-600/25 transition-all duration-200 active:scale-95"
        >
          <Plus className="w-4 h-4" />
          <span>New Shorts</span>
          <Sparkles className="w-3.5 h-3.5 text-cyan-200" />
        </button>
      </div>
    </header>
  );
};
