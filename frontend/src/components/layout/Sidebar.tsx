import React from 'react';
import {
  LayoutDashboard,
  Film,
  FolderKanban,
  Download,
  Settings,
  Sparkles,
  Cpu,
  Layers,
  ChevronRight,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import type { ViewMode } from '../../types';

export const Sidebar: React.FC = () => {
  const { currentView, setCurrentView, backendStatus, projects } = useApp();

  const totalClips = projects.reduce((acc, p) => acc + (p.exportedClips?.length || 0), 0);

  const navItems: { id: ViewMode; label: string; icon: React.ReactNode; badge?: string | number }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
    { id: 'create', label: 'Create Shorts', icon: <Sparkles className="w-5 h-5 text-purple-400" />, badge: 'AI' },
    { id: 'projects', label: 'My Projects', icon: <FolderKanban className="w-5 h-5" />, badge: projects.length },
    { id: 'exports', label: 'Export History', icon: <Download className="w-5 h-5" />, badge: totalClips > 0 ? totalClips : undefined },
    { id: 'settings', label: 'Settings', icon: <Settings className="w-5 h-5" /> },
  ];

  return (
    <aside className="w-64 bg-[#0e1017] border-r border-[#1f2333] flex flex-col justify-between shrink-0 h-screen sticky top-0 select-none">
      {/* Brand header */}
      <div>
        <div className="p-6 border-b border-[#1f2333]/60 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-cyan-400 flex items-center justify-center shadow-lg shadow-purple-500/20 ring-1 ring-purple-400/30">
            <Film className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
                ViralClip
              </span>
              <span className="text-xs px-1.5 py-0.5 rounded-md font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                AI
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-medium">9:16 Shorts Automation</p>
          </div>
        </div>

        {/* Navigation list */}
        <nav className="p-3 space-y-1.5">
          <div className="px-3 py-2 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
            Menu
          </div>
          {navItems.map((item) => {
            const isActive = currentView === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setCurrentView(item.id)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 group ${
                  isActive
                    ? 'bg-gradient-to-r from-purple-600/20 to-indigo-600/10 text-white border border-purple-500/30 shadow-sm shadow-purple-900/20'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-[#161925]'
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className={`transition-colors ${isActive ? 'text-purple-400' : 'group-hover:text-slate-300'}`}>
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </div>
                {item.badge !== undefined && (
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${
                      isActive
                        ? 'bg-purple-500/30 text-purple-200'
                        : 'bg-[#1b1f2e] text-slate-400 group-hover:bg-[#23283b]'
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}

          <div className="pt-4 px-3 py-2 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
            Quick Workspaces
          </div>
          <button
            onClick={() => setCurrentView('processing')}
            className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
              currentView === 'processing'
                ? 'bg-purple-600/20 text-purple-300 border border-purple-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-[#161925]'
            }`}
          >
            <div className="flex items-center gap-3">
              <Layers className="w-5 h-5 text-cyan-400" />
              <span>Video Processing</span>
            </div>
            <ChevronRight className="w-4 h-4 opacity-50" />
          </button>
          <button
            onClick={() => setCurrentView('editor')}
            className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-medium transition-all ${
              currentView === 'editor'
                ? 'bg-purple-600/20 text-purple-300 border border-purple-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-[#161925]'
            }`}
          >
            <div className="flex items-center gap-3">
              <Film className="w-5 h-5 text-amber-400" />
              <span>Clip Editor (9:16)</span>
            </div>
            <ChevronRight className="w-4 h-4 opacity-50" />
          </button>
        </nav>
      </div>

      {/* Backend & Hardware status footer */}
      <div className="p-4 m-3 rounded-2xl bg-[#13151f] border border-[#212638] space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            Hardware Engine
          </span>
          <span className="flex items-center gap-1">
            <span
              className={`w-2 h-2 rounded-full ${
                backendStatus.online ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
              }`}
            />
            <span className="text-[10px] font-medium text-slate-400">
              {backendStatus.online ? 'Active' : 'Local'}
            </span>
          </span>
        </div>

        <div className="space-y-1.5 text-[11px] text-slate-400">
          <div className="flex items-center justify-between">
            <span>Video Encoder:</span>
            <span className="font-mono text-slate-300 font-semibold truncate max-w-[110px]" title={backendStatus.gpuEncoder || 'Hardware probe'}>
              {backendStatus.gpuEncoder ? 'NVENC / GPU' : 'CPU (libx264)'}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>Speech STT:</span>
            <span className="text-emerald-400 font-medium">Whisper Local</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Default Layout:</span>
            <span className="text-purple-300 font-medium">Facecam + 3:4 Play</span>
          </div>
        </div>
      </div>
    </aside>
  );
};
