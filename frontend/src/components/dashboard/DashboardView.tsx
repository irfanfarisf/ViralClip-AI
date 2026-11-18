import React, { useState } from 'react';
import {
  Upload,
  Tv,
  Plus,
  Sparkles,
  ArrowRight,
  Clock,
  Scissors,
  CheckCircle2,
  Trash2,
  Sliders,
  AlertCircle,
  HelpCircle,
} from 'lucide-react';
import { YoutubeIcon } from '../common/Icons';
import { useApp } from '../../context/AppContext';
import { NewProjectModal } from './NewProjectModal';
import type { VideoProject } from '../../types';

export const DashboardView: React.FC = () => {
  const {
    projects,
    setActiveProject,
    setCurrentView,
    deleteProject,
    openEditorForHighlight,
    createProjectFromUrl,
    loadDemoProject,
    backendStatus,
    showToast,
  } = useApp();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalTab, setModalTab] = useState<'local' | 'youtube' | 'twitch'>('local');
  const [quickUrl, setQuickUrl] = useState('');
  const [quickPlatform, setQuickPlatform] = useState<'youtube' | 'twitch'>('youtube');
  const [isImporting, setIsImporting] = useState(false);

  const handleOpenModal = (tab: 'local' | 'youtube' | 'twitch') => {
    setModalTab(tab);
    setIsModalOpen(true);
  };

  const handleQuickImport = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = quickUrl.trim();
    if (!trimmed) {
      showToast('Please enter a YouTube or Twitch link');
      return;
    }
    try {
      setIsImporting(true);
      await createProjectFromUrl(trimmed, quickPlatform);
      setQuickUrl('');
    } catch (err: any) {
      showToast(err?.message || 'Import failed');
    } finally {
      setIsImporting(false);
    }
  };

  const userProjects = projects.filter((p) => !p.isDemo);
  const totalClips = userProjects.reduce((acc, p) => acc + (p.exportedClips?.length || 0), 0);
  const totalHighlights = userProjects.reduce((acc, p) => acc + (p.highlights?.length || 0), 0);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-10">
      {/* Backend Health notice if offline */}
      {!backendStatus.online && (
        <div className="p-4 rounded-2xl bg-amber-950/40 border border-amber-800/50 flex items-center justify-between text-xs text-amber-200">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 text-amber-400 shrink-0" />
            <span>
              Backend server is offline (127.0.0.1:8000). Video uploading, FFmpeg processing, and exports require the backend.
            </span>
          </div>
          <span className="font-mono text-[11px] text-amber-400">Offline Mode</span>
        </div>
      )}

      {/* Hero Welcome banner */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-r from-[#171526] via-[#131521] to-[#0e1724] border border-[#272b3f] p-8 md:p-10 shadow-2xl">
        <div className="absolute -right-20 -top-20 w-80 h-80 bg-purple-600/15 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute right-40 -bottom-20 w-72 h-72 bg-cyan-600/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative z-10 max-w-2xl space-y-4">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-300 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5 text-purple-400" />
            <span>AI Short-Form Video Automation</span>
          </div>

          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tight text-white leading-tight">
            Turn Long Streams & Videos Into{' '}
            <span className="bg-gradient-to-r from-purple-400 via-indigo-300 to-cyan-400 bg-clip-text text-transparent">
              Viral 9:16 Shorts
            </span>
          </h2>

          <p className="text-sm text-slate-300 leading-relaxed">
            Automate interesting moment detection with local Whisper transcription. Effortlessly compose
            <span className="text-white font-medium"> Facecam Top + Gameplay Bottom (~3:4)</span> layouts with animated word-level subtitles.
          </p>

          <div className="pt-2 flex flex-wrap items-center gap-3.5">
            <button
              onClick={() => handleOpenModal('local')}
              className="flex items-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white text-sm font-semibold shadow-lg shadow-purple-600/30 transition-all duration-200 active:scale-95"
            >
              <Upload className="w-4 h-4" />
              <span>Upload Local Video</span>
            </button>

            <button
              onClick={() => handleOpenModal('youtube')}
              className="flex items-center gap-2 px-4 py-3 rounded-xl bg-[#181b28] hover:bg-[#202436] text-slate-200 text-sm font-medium border border-[#2b3149] transition-all"
            >
              <YoutubeIcon className="w-4 h-4 text-red-400" />
              <span>Import YouTube</span>
            </button>

            <button
              onClick={() => handleOpenModal('twitch')}
              className="flex items-center gap-2 px-4 py-3 rounded-xl bg-[#181b28] hover:bg-[#202436] text-slate-200 text-sm font-medium border border-[#2b3149] transition-all"
            >
              <Tv className="w-4 h-4 text-purple-400" />
              <span>Import Twitch</span>
            </button>
          </div>
        </div>
      </div>

      {/* Quick URL Import Box */}
      <div className="rounded-2xl bg-[#12141c] border border-[#23283b] p-6 shadow-xl space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-cyan-400" />
              Quick Video URL Extraction
            </h3>
            <p className="text-xs text-slate-400">Paste any public or creator-authorized VOD link to extract highlights</p>
          </div>
          <span className="text-[11px] text-slate-400 hidden sm:inline">Connects to POST /api/videos/import-url</span>
        </div>

        <form onSubmit={handleQuickImport} className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <input
              type="url"
              value={quickUrl}
              onChange={(e) => setQuickUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=... or https://twitch.tv/videos/..."
              className="w-full px-4 py-3 rounded-xl bg-[#0b0c10] border border-[#23283b] text-sm text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
            />
          </div>

          <div className="flex items-center gap-2">
            <select
              value={quickPlatform}
              onChange={(e) => setQuickPlatform(e.target.value as 'youtube' | 'twitch')}
              className="px-3 py-3 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-slate-300 focus:outline-none focus:border-purple-500"
            >
              <option value="youtube">YouTube</option>
              <option value="twitch">Twitch</option>
            </select>

            <button
              type="submit"
              disabled={isImporting}
              className="px-6 py-3 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-semibold shrink-0 shadow-md transition-all flex items-center gap-2"
            >
              <span>{isImporting ? 'Importing...' : 'Analyze URL'}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </form>
      </div>

      {/* Analytics stats strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-[#12141c] border border-[#1f2333]">
          <span className="text-xs font-medium text-slate-400">Total User Projects</span>
          <p className="text-2xl font-bold text-white mt-1">{userProjects.length}</p>
          <span className="text-[11px] text-emerald-400 font-medium mt-1 flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3" /> Backend Synchronized
          </span>
        </div>
        <div className="p-5 rounded-2xl bg-[#12141c] border border-[#1f2333]">
          <span className="text-xs font-medium text-slate-400">Highlights Identified</span>
          <p className="text-2xl font-bold text-cyan-400 mt-1">{totalHighlights}</p>
          <span className="text-[11px] text-slate-400 mt-1 block">Whisper & Energy Scored</span>
        </div>
        <div className="p-5 rounded-2xl bg-[#12141c] border border-[#1f2333]">
          <span className="text-xs font-medium text-slate-400">Exported Clips</span>
          <p className="text-2xl font-bold text-purple-400 mt-1">{totalClips}</p>
          <span className="text-[11px] text-purple-300 mt-1 block">9:16 Vertical Ready</span>
        </div>
        <div className="p-5 rounded-2xl bg-[#12141c] border border-[#1f2333]">
          <span className="text-xs font-medium text-slate-400">Hardware Encoder</span>
          <p className="text-sm font-bold text-amber-400 mt-2 truncate">
            {backendStatus.gpuEncoder || 'Probing...'}
          </p>
          <span className="text-[11px] text-slate-400 mt-1 block">Auto-probed via FFmpeg</span>
        </div>
      </div>

      {/* Recent Projects Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold text-white">Recent Projects</h3>
            <p className="text-xs text-slate-400">Click any project to view extracted highlights and open the 9:16 clip editor</p>
          </div>
          <div className="flex items-center gap-3">
            {projects.length === 0 && (
              <button
                onClick={loadDemoProject}
                className="text-xs text-slate-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
              >
                <HelpCircle className="w-3.5 h-3.5 text-purple-400" />
                <span>Explore Demo Sample</span>
              </button>
            )}
            <button
              onClick={() => handleOpenModal('local')}
              className="flex items-center gap-1.5 text-xs font-semibold text-purple-400 hover:text-purple-300 transition-colors"
            >
              <Plus className="w-4 h-4" />
              <span>New Project</span>
            </button>
          </div>
        </div>

        {projects.length === 0 ? (
          <div className="p-12 text-center rounded-2xl bg-[#12141c] border border-dashed border-[#23283b] space-y-4">
            <Upload className="w-10 h-10 text-slate-600 mx-auto" />
            <div>
              <p className="text-sm font-semibold text-slate-300">No projects yet</p>
              <p className="text-xs text-slate-500 max-w-sm mx-auto mt-1">
                Upload a local video file (MP4, MKV, MOV, WEBM) or import a YouTube/Twitch URL to start.
              </p>
            </div>
            <div className="flex items-center justify-center gap-3 pt-2">
              <button
                onClick={() => handleOpenModal('local')}
                className="px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold shadow-md transition-all"
              >
                Upload First Video
              </button>
              <button
                onClick={loadDemoProject}
                className="px-4 py-2.5 rounded-xl bg-[#181b28] hover:bg-[#22273a] text-slate-300 text-xs font-medium border border-[#2b3149] transition-all"
              >
                Load Demo Sample
              </button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {projects.map((project: VideoProject) => {
              const highlightCount = project.highlights?.length || 0;
              return (
                <div
                  key={project.id}
                  className={`rounded-2xl p-5 space-y-4 transition-all duration-200 group shadow-lg flex flex-col justify-between border ${
                    project.isDemo
                      ? 'bg-[#131522] border-purple-500/30'
                      : 'bg-[#12141c] border-[#212537] hover:border-purple-500/40'
                  }`}
                >
                  <div className="space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-[#191d2c] text-purple-300 border border-[#293047]">
                          {project.sourceType}
                        </span>
                        {project.isDemo && (
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 uppercase">
                            Demo Sample
                          </span>
                        )}
                      </div>

                      <span
                        className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${
                          project.status === 'ready'
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : project.status === 'failed'
                            ? 'bg-red-500/20 text-red-300 border border-red-500/30'
                            : 'bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse'
                        }`}
                      >
                        {project.status === 'ready'
                          ? 'Highlights Ready'
                          : project.status === 'failed'
                          ? 'Failed'
                          : project.currentStage || 'Processing'}
                      </span>
                    </div>

                    <div>
                      <h4 className="text-sm font-bold text-white line-clamp-1 group-hover:text-purple-300 transition-colors">
                        {project.title}
                      </h4>
                      <div className="flex items-center gap-3 text-xs text-slate-400 mt-1">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5" />
                          {Math.floor(project.duration / 60)}m {Math.round(project.duration % 60)}s
                        </span>
                        <span>•</span>
                        <span>{project.fps} FPS</span>
                        <span>•</span>
                        <span>{project.fileSizeMb || 0} MB</span>
                      </div>
                    </div>

                    <div className="p-3 rounded-xl bg-[#0c0d14] border border-[#1b1e2c] flex items-center justify-between text-xs">
                      <span className="text-slate-400 flex items-center gap-1.5">
                        <Scissors className="w-3.5 h-3.5 text-cyan-400" />
                        Highlights
                      </span>
                      <span className="font-semibold text-white">
                        {highlightCount} moments detected
                      </span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-[#1b1f2e] flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          setActiveProject(project);
                          setCurrentView('processing');
                        }}
                        className="px-3 py-1.5 rounded-lg bg-[#181b28] hover:bg-[#202538] text-xs font-semibold text-slate-300 hover:text-white transition-colors"
                      >
                        Processing
                      </button>

                      {highlightCount > 0 && (
                        <button
                          onClick={() => {
                            setActiveProject(project);
                            if (project.highlights[0]) {
                              openEditorForHighlight(project, project.highlights[0]);
                            } else {
                              setCurrentView('editor');
                            }
                          }}
                          className="px-3 py-1.5 rounded-lg bg-purple-600/20 hover:bg-purple-600/30 text-xs font-semibold text-purple-300 border border-purple-500/30 flex items-center gap-1 transition-colors"
                        >
                          <Sliders className="w-3 h-3" />
                          <span>Editor</span>
                        </button>
                      )}
                    </div>

                    <button
                      onClick={() => deleteProject(project.id)}
                      title="Delete Project"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-950/20 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <NewProjectModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        defaultTab={modalTab}
      />
    </div>
  );
};
