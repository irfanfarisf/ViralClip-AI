import React, { useState, useRef } from 'react';
import {
  X,
  Upload,
  Tv,
  FileVideo,
  Sparkles,
  AlertCircle,
  CheckCircle2,
  HardDrive,
  Loader2,
  RotateCcw,
  XCircle,
  Globe,
} from 'lucide-react';
import { YoutubeIcon } from '../common/Icons';
import { useApp } from '../../context/AppContext';
import { SUPPORTED_LANGUAGES, type ImportTelemetry } from '../../types';

interface NewProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  defaultTab?: 'local' | 'youtube' | 'twitch';
}

const formatBytes = (bytes: number): string => {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
};

const formatEta = (sec: number | null | undefined): string => {
  if (sec === null || sec === undefined || !isFinite(sec) || sec < 0) return '--';
  if (sec < 60) return `${Math.ceil(sec)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.ceil(sec % 60);
  return `${m}m ${s}s`;
};

export const NewProjectModal: React.FC<NewProjectModalProps> = ({
  isOpen,
  onClose,
  defaultTab = 'local',
}) => {
  const { createProjectFromLocal, createProjectFromUrl, backendStatus } = useApp();
  const [tab, setTab] = useState<'local' | 'youtube' | 'twitch'>(defaultTab);
  const [url, setUrl] = useState('');
  const [sourceLanguage, setSourceLanguage] = useState<string>('auto');
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [telemetry, setTelemetry] = useState<ImportTelemetry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  if (!isOpen) return null;

  const validateFile = (file: File): boolean => {
    setError(null);
    const validExtensions = ['mp4', 'mov', 'mkv', 'webm', 'avi'];
    const ext = file.name.split('.').pop()?.toLowerCase();
    if (!ext || !validExtensions.includes(ext)) {
      setError(`Unsupported format .${ext}. Please select an MP4, MOV, MKV, or WEBM video.`);
      return false;
    }
    const maxBytes = 4 * 1024 * 1024 * 1024; // 4 GB limit
    if (file.size > maxBytes) {
      setError('File exceeds 4 GB maximum limit. Please select a shorter video.');
      return false;
    }
    return true;
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (validateFile(file)) {
        setSelectedFile(file);
        setTelemetry(null);
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (validateFile(file)) {
        setSelectedFile(file);
        setTelemetry(null);
      }
    }
  };

  const handleCancelActiveUpload = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  const handleSubmitLocal = async () => {
    if (!selectedFile) return;
    const ctrl = new AbortController();
    abortControllerRef.current = ctrl;
    try {
      setIsSubmitting(true);
      setError(null);
      setUploadProgress(0);
      await createProjectFromLocal(
        selectedFile,
        (p) => setUploadProgress(p),
        {
          signal: ctrl.signal,
          onTelemetry: (t) => setTelemetry(t),
          language: sourceLanguage !== 'auto' ? sourceLanguage : undefined,
        }
      );
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to upload video to backend');
    } finally {
      setIsSubmitting(false);
      abortControllerRef.current = null;
    }
  };

  const handleSubmitUrl = async () => {
    const trimmed = url.trim();
    if (!trimmed) {
      setError('Please provide a valid stream or video URL');
      return;
    }

    if (tab === 'youtube' && !trimmed.includes('youtube.com') && !trimmed.includes('youtu.be')) {
      setError('Invalid YouTube link. URL must contain youtube.com or youtu.be');
      return;
    }

    if (tab === 'twitch' && !trimmed.includes('twitch.tv')) {
      setError('Invalid Twitch link. URL must contain twitch.tv');
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);
      await createProjectFromUrl(trimmed, tab === 'twitch' ? 'twitch' : 'youtube', {
        language: sourceLanguage !== 'auto' ? sourceLanguage : undefined,
      });
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to import video from URL');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-xl rounded-3xl bg-[#12141c] border border-[#23283b] shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between p-6 border-b border-[#1f2333]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-purple-600/20 text-purple-400 border border-purple-500/30 flex items-center justify-center">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Create New Viral Shorts</h3>
              <p className="text-xs text-slate-400">Chunked resumable upload & stream ingestion up to 4 hours</p>
            </div>
          </div>
          <button
            onClick={() => {
              handleCancelActiveUpload();
              onClose();
            }}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#1a1d2a] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab selection */}
        <div className="px-6 pt-5 pb-2">
          <div className="grid grid-cols-3 gap-2 p-1 rounded-xl bg-[#0b0c10] border border-[#1f2333]">
            <button
              onClick={() => {
                setTab('local');
                setError(null);
              }}
              className={`flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all ${
                tab === 'local'
                  ? 'bg-purple-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <HardDrive className="w-4 h-4" />
              <span>Local File</span>
              <span className="text-[10px] px-1 py-0.2 bg-purple-800/60 rounded">Chunked</span>
            </button>
            <button
              onClick={() => {
                setTab('youtube');
                setError(null);
              }}
              className={`flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all ${
                tab === 'youtube'
                  ? 'bg-red-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <YoutubeIcon className="w-4 h-4" />
              <span>YouTube</span>
            </button>
            <button
              onClick={() => {
                setTab('twitch');
                setError(null);
              }}
              className={`flex items-center justify-center gap-2 py-2 text-xs font-semibold rounded-lg transition-all ${
                tab === 'twitch'
                  ? 'bg-purple-500 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              <Tv className="w-4 h-4" />
              <span>Twitch VOD</span>
            </button>
          </div>
        </div>

        {/* Modal Body */}
        <div className="p-6 pt-3 space-y-4">
          {error && (
            <div className="p-3.5 rounded-xl bg-red-950/40 border border-red-800/50 flex items-center justify-between gap-2.5 text-xs text-red-300">
              <div className="flex items-start gap-2.5">
                <AlertCircle className="w-4 h-4 shrink-0 text-red-400 mt-0.5" />
                <span>{error}</span>
              </div>
              {tab === 'local' && selectedFile && !isSubmitting && (
                <button
                  type="button"
                  onClick={handleSubmitLocal}
                  className="px-3 py-1 rounded-lg bg-red-900/50 hover:bg-red-800/70 text-red-200 font-semibold shrink-0 flex items-center gap-1 border border-red-700/50"
                >
                  <RotateCcw className="w-3 h-3" />
                  <span>Resume</span>
                </button>
              )}
            </div>
          )}

          {!backendStatus.online && (
            <div className="p-3 rounded-xl bg-amber-950/30 border border-amber-800/40 flex items-center justify-between text-xs text-amber-300">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                <span>Backend offline (127.0.0.1:8000). Uploads require active backend server.</span>
              </div>
            </div>
          )}

          {tab === 'local' ? (
            <div className="space-y-4">
              <input
                ref={fileInputRef}
                type="file"
                accept="video/mp4,video/x-matroska,video/webm,video/quicktime,video/x-msvideo"
                className="hidden"
                onChange={handleFileChange}
              />

              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleFileDrop}
                onClick={() => !isSubmitting && fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl p-8 flex flex-col items-center justify-center transition-all ${
                  isSubmitting ? 'cursor-default' : 'cursor-pointer'
                } ${
                  isDragging
                    ? 'border-purple-500 bg-purple-500/10'
                    : selectedFile
                    ? 'border-emerald-500/50 bg-emerald-500/5'
                    : 'border-[#262c3e] hover:border-purple-500/40 bg-[#0e1017]'
                }`}
              >
                {selectedFile ? (
                  <div className="text-center space-y-3 w-full max-w-md">
                    <div className="w-12 h-12 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto border border-emerald-500/40">
                      <CheckCircle2 className="w-6 h-6" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white truncate max-w-sm mx-auto">
                        {selectedFile.name}
                      </p>
                      <p className="text-xs text-slate-400">
                        {formatBytes(selectedFile.size)} • Ready for chunked streaming upload
                      </p>
                    </div>

                    {(isSubmitting || telemetry) && (
                      <div className="w-full space-y-2 pt-2 text-left bg-[#141724] p-3.5 rounded-xl border border-[#252b42]">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-bold text-purple-300 uppercase tracking-wider flex items-center gap-1.5">
                            <span>{telemetry?.stage || 'UPLOADING'}</span>
                            {telemetry?.resumed && (
                              <span className="px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 text-[9px] border border-emerald-500/30">
                                RESUMED
                              </span>
                            )}
                          </span>
                          <span className="font-mono font-bold text-cyan-300">
                            {telemetry?.progress ?? uploadProgress ?? 0}%
                          </span>
                        </div>

                        <div className="w-full h-2 rounded-full bg-slate-900 overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-purple-500 to-cyan-400 transition-all duration-150"
                            style={{ width: `${telemetry?.progress ?? uploadProgress ?? 0}%` }}
                          />
                        </div>

                        <div className="grid grid-cols-3 gap-2 pt-1 text-[10px] text-slate-400 font-mono">
                          <div>
                            <span className="text-slate-500 block">Transferred</span>
                            <span className="text-slate-200">
                              {formatBytes(telemetry?.bytesTransferred ?? 0)} / {formatBytes(selectedFile.size)}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-500 block">Speed</span>
                            <span className="text-emerald-300">
                              {telemetry?.speedBps ? `${(telemetry.speedBps / 1048576).toFixed(1)} MB/s` : '--'}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-500 block">ETA</span>
                            <span className="text-cyan-300">{formatEta(telemetry?.etaSeconds)}</span>
                          </div>
                        </div>
                      </div>
                    )}

                    {!isSubmitting && (
                      <p className="text-[11px] text-purple-400">Click to choose a different file</p>
                    )}
                  </div>
                ) : (
                  <div className="text-center space-y-3">
                    <div className="w-12 h-12 rounded-2xl bg-purple-600/15 text-purple-400 border border-purple-500/30 flex items-center justify-center mx-auto">
                      <Upload className="w-6 h-6" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-white">
                        Drag and drop your video here
                      </p>
                      <p className="text-xs text-slate-400 mt-0.5">
                        MP4, MKV, MOV, WEBM, or AVI up to 4 GB (3–4+ hours supported)
                      </p>
                    </div>
                    <button
                      type="button"
                      className="px-4 py-1.5 rounded-lg bg-[#1a1e2d] hover:bg-[#23283b] text-slate-200 text-xs font-medium border border-[#2b3248]"
                    >
                      Browse Files
                    </button>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 text-[11px] text-slate-400">
                <FileVideo className="w-4 h-4 text-slate-400" />
                <span>Streams 8 MB verified slices directly to disk with automatic resume on interruption.</span>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  {tab === 'youtube' ? 'YouTube Video URL' : 'Twitch VOD URL'}
                </label>
                <div className="relative">
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder={
                      tab === 'youtube'
                        ? 'https://www.youtube.com/watch?v=...'
                        : 'https://www.twitch.tv/videos/...'
                    }
                    className="w-full px-4 py-3 rounded-xl bg-[#0b0c10] border border-[#23283b] text-sm text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
                  />
                </div>
              </div>

              <div className="p-3.5 rounded-xl bg-purple-950/20 border border-purple-800/30 text-xs text-slate-300 space-y-1">
                <p className="font-semibold text-purple-300">Authorized Background Stream Import</p>
                <p className="text-slate-400 text-[11px] leading-relaxed">
                  Downloads creator VODs in a background worker with live speed, byte count, ETA, and resume support.
                </p>
              </div>
            </div>
          )}

          {/* Multilingual Speech Language Selector */}
          <div className="p-3.5 rounded-xl bg-[#0b0d14] border border-[#23283b] flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <Globe className="w-4 h-4 text-purple-400 shrink-0" />
              <div>
                <label htmlFor="source-lang-select" className="text-xs font-semibold text-white block">
                  Spoken Video Language
                </label>
                <span className="text-[11px] text-slate-400">
                  Whisper multilingual speech recognition
                </span>
              </div>
            </div>
            <select
              id="source-lang-select"
              value={sourceLanguage}
              disabled={isSubmitting}
              onChange={(e) => setSourceLanguage(e.target.value)}
              className="bg-[#161a26] border border-[#2e364e] text-xs text-white rounded-lg px-3 py-1.5 focus:outline-none focus:border-purple-500 font-medium cursor-pointer"
            >
              {Object.entries(SUPPORTED_LANGUAGES).map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="p-6 pt-3 border-t border-[#1f2333] flex items-center justify-between">
          {isSubmitting && tab === 'local' ? (
            <button
              type="button"
              onClick={handleCancelActiveUpload}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-red-300 bg-red-950/40 hover:bg-red-900/50 border border-red-800/40 transition-colors"
            >
              <XCircle className="w-4 h-4" />
              <span>Cancel Upload</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white transition-colors"
            >
              Cancel
            </button>
          )}

          <button
            type="button"
            disabled={isSubmitting || (tab === 'local' ? !selectedFile : !url.trim())}
            onClick={tab === 'local' ? handleSubmitLocal : handleSubmitUrl}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-semibold shadow-lg shadow-purple-600/30 transition-all duration-200"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>
                  {telemetry?.stage
                    ? `${telemetry.stage} (${telemetry.progress}%)...`
                    : uploadProgress !== null
                    ? `Uploading ${uploadProgress}%...`
                    : 'Starting Import...'}
                </span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                <span>{error && tab === 'local' ? 'Resume / Retry Upload' : 'Start Clip Extraction'}</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
