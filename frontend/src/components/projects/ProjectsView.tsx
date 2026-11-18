import React, { useState } from 'react';
import {
  FolderKanban,
  Search,
  Plus,
  Clock,
  Trash2,
  HardDrive,
  Tv,
} from 'lucide-react';
import { YoutubeIcon } from '../common/Icons';
import { useApp } from '../../context/AppContext';
import { NewProjectModal } from '../dashboard/NewProjectModal';
import type { VideoProject } from '../../types';

export const ProjectsView: React.FC = () => {
  const {
    projects,
    setActiveProject,
    setCurrentView,
    deleteProject,
    openEditorForHighlight,
  } = useApp();

  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const [isModalOpen, setIsModalOpen] = useState(false);

  const filtered = projects.filter((p) => {
    const matchesSearch = p.title.toLowerCase().includes(search.toLowerCase());
    const matchesType = filterType === 'all' || p.sourceType === filterType;
    return matchesSearch && matchesType;
  });

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-extrabold text-white flex items-center gap-2.5">
            <FolderKanban className="w-6 h-6 text-purple-400" />
            Project Library
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Manage all imported stream recordings, podcasts, and generated short clips
          </p>
        </div>

        <button
          onClick={() => setIsModalOpen(true)}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold shadow-md transition-all self-start sm:self-auto"
        >
          <Plus className="w-4 h-4" />
          <span>New Project</span>
        </button>
      </div>

      {/* Filter and search bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-4 rounded-2xl bg-[#12141c] border border-[#212638]">
        <div className="relative w-full sm:w-80">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search projects by title..."
            className="w-full pl-9 pr-4 py-2 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs text-white placeholder-slate-500 focus:outline-none focus:border-purple-500"
          />
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5 pointer-events-none" />
        </div>

        <div className="flex items-center gap-2 self-end sm:self-auto">
          <span className="text-xs text-slate-400">Source:</span>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[#0b0c10] border border-[#23283b] text-xs font-semibold text-slate-300 focus:outline-none focus:border-purple-500"
          >
            <option value="all">All Sources</option>
            <option value="local">Local Files</option>
            <option value="youtube">YouTube</option>
            <option value="twitch">Twitch</option>
          </select>
        </div>
      </div>

      {/* Projects Grid */}
      {filtered.length === 0 ? (
        <div className="p-12 text-center rounded-3xl bg-[#12141c] border border-dashed border-[#23283b] space-y-3">
          <p className="text-sm font-semibold text-slate-300">No matching projects found</p>
          <p className="text-xs text-slate-500">Try adjusting your search query or import a new video.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered.map((project: VideoProject) => {
            const highlightCount = project.highlights?.length || 0;
            const exportedCount = project.exportedClips?.length || 0;

            return (
              <div
                key={project.id}
                className="rounded-3xl bg-[#12141c] border border-[#212638] hover:border-purple-500/40 p-6 flex flex-col justify-between space-y-5 transition-all shadow-xl group"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-[#181c2b] text-purple-300 border border-[#29324c] flex items-center gap-1">
                        {project.sourceType === 'local' ? (
                          <HardDrive className="w-3 h-3 text-cyan-400" />
                        ) : project.sourceType === 'youtube' ? (
                          <YoutubeIcon className="w-3 h-3 text-red-400" />
                        ) : (
                          <Tv className="w-3 h-3 text-purple-400" />
                        )}
                        <span>{project.sourceType}</span>
                      </span>

                      {project.isDemo && (
                        <span className="text-[9px] font-extrabold uppercase px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                          Demo Sample
                        </span>
                      )}
                    </div>

                    <span
                      className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                        project.status === 'ready'
                          ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                          : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                      }`}
                    >
                      {project.status === 'ready' ? 'Ready' : 'Processing'}
                    </span>
                  </div>

                  <h3 className="text-sm font-bold text-white group-hover:text-purple-300 transition-colors line-clamp-2">
                    {project.title}
                  </h3>

                  <div className="flex items-center gap-3 text-xs text-slate-400 font-mono">
                    <span className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5 text-cyan-400" />
                      {Math.floor(project.duration / 60)}m {Math.round(project.duration % 60)}s
                    </span>
                    <span>•</span>
                    <span>{project.fps} FPS</span>
                    <span>•</span>
                    <span>{project.fileSizeMb || 0} MB</span>
                  </div>
                </div>

                <div className="space-y-3 pt-3 border-t border-[#1c2030]">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2.5 rounded-xl bg-[#0b0c10] border border-[#1b1f2e] text-center">
                      <span className="text-[10px] text-slate-500 uppercase font-bold block">Highlights</span>
                      <span className="font-bold text-cyan-400 text-sm">{highlightCount} moments</span>
                    </div>
                    <div className="p-2.5 rounded-xl bg-[#0b0c10] border border-[#1b1f2e] text-center">
                      <span className="text-[10px] text-slate-500 uppercase font-bold block">Exported</span>
                      <span className="font-bold text-purple-400 text-sm">{exportedCount} clips</span>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-2 pt-1">
                    <button
                      onClick={() => {
                        setActiveProject(project);
                        setCurrentView('processing');
                      }}
                      className="px-3.5 py-2 rounded-xl bg-[#191d2c] hover:bg-[#22283d] text-xs font-semibold text-slate-200 transition-colors flex-1 text-center"
                    >
                      Processing View
                    </button>

                    {highlightCount > 0 && (
                      <button
                        onClick={() => {
                          setActiveProject(project);
                          openEditorForHighlight(project, project.highlights[0]);
                        }}
                        className="px-3.5 py-2 rounded-xl bg-purple-600/20 hover:bg-purple-600/30 text-xs font-semibold text-purple-300 border border-purple-500/30 transition-colors"
                      >
                        Editor
                      </button>
                    )}

                    <button
                      onClick={() => deleteProject(project.id)}
                      title="Delete Project"
                      className="p-2 rounded-xl text-slate-500 hover:text-red-400 hover:bg-red-950/20 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <NewProjectModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        defaultTab="local"
      />
    </div>
  );
};
