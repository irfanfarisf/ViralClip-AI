import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import {
  SUPPORTED_LANGUAGES,
  type ViewMode,
  type VideoProject,
  type HighlightMoment,
  type SubtitleStyle,
  type LayoutConfig,
  type AppSettings,
  type ExportedClip,
  type ImportTelemetry,
} from '../types';
import {
  checkBackendHealth,
  uploadVideoFile,
  importFromUrl,
  fetchJobs,
  fetchJobDetails,
  deleteJob,
  exportClipOnBackend,
  updateClipOnBackend,
  updateClipTranscript,
  translateClipSubtitles,
  connectJobWebSocket,
  sampleDemoProject,
} from '../services/api';

interface AppContextType {
  currentView: ViewMode;
  setCurrentView: (view: ViewMode) => void;
  projects: VideoProject[];
  activeProject: VideoProject | null;
  setActiveProject: (project: VideoProject | null) => void;
  activeHighlight: HighlightMoment | null;
  setActiveHighlight: (highlight: HighlightMoment | null) => void;
  subtitleStyle: SubtitleStyle;
  setSubtitleStyle: React.Dispatch<React.SetStateAction<SubtitleStyle>>;
  layoutConfig: LayoutConfig;
  setLayoutConfig: React.Dispatch<React.SetStateAction<LayoutConfig>>;
  settings: AppSettings;
  setSettings: React.Dispatch<React.SetStateAction<AppSettings>>;
  backendStatus: {
    online: boolean;
    ffmpeg: boolean;
    ffprobe: boolean;
    gpuEncoder: string | null;
    whisper: boolean;
    pythonVersion: string;
  };
  refreshBackendStatus: () => Promise<void>;
  createProjectFromLocal: (
    file: File,
    onUploadProgress?: (p: number) => void,
    options?: { signal?: AbortSignal; onTelemetry?: (t: ImportTelemetry) => void; language?: string }
  ) => Promise<VideoProject>;
  createProjectFromUrl: (url: string, platform: 'youtube' | 'twitch', options?: { language?: string }) => Promise<VideoProject>;
  deleteProject: (id: string) => Promise<void>;
  toggleHighlightSelection: (projectId: string, highlightId: string) => void;
  exportCurrentHighlight: (clipTitle?: string) => Promise<ExportedClip>;
  openEditorForHighlight: (project: VideoProject, highlight: HighlightMoment) => void;
  saveTranscriptCorrection: (
    clipId: string,
    segments: Array<{ id?: string; start?: number; end?: number; text: string; words?: any[] }>
  ) => Promise<void>;
  translateCurrentClipSubtitles: (targetLanguage: string) => Promise<void>;
  loadDemoProject: () => void;
  syncJobDetails: (jobId: string, includeWords?: boolean) => Promise<void>;
  toastMessage: string | null;
  showToast: (msg: string) => void;
}

const defaultSubtitleStyle: SubtitleStyle = {
  preset: 'yellow_highlight',
  fontSize: 'lg',
  fontFamily: 'Montserrat',
  textColor: '#FFFFFF',
  highlightColor: '#FFD700',
  outlineColor: '#000000',
  outlineWidth: 5,
  shadowDepth: 2.5,
  backgroundColor: 'rgba(0,0,0,0.65)',
  hasBackground: false,
  positionY: 76,
  isUppercase: true,
  animateKaraoke: true,
  animation: 'pop',
  maxWordsPerLine: 4,
};

// Default layout: Facecam TOP (25% = 480px) + Gameplay BOTTOM (75% = 1440px, exact 3:4 ratio)
const defaultLayoutConfig: LayoutConfig = {
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
};

const defaultSettings: AppSettings = {
  geminiApiKey: '', // NOT saved to localStorage
  openaiApiKey: '', // NOT saved to localStorage
  whisperModel: 'base',
  device: 'cpu',
  defaultLayout: 'facecam_gameplay',
  defaultSubtitlePreset: 'beast_yellow',
  outputResolution: '1080x1920',
  targetBitrate: 8500,
  hardwareAcceleration: true,
  autoCleanupHours: 24,
};

const AppContext = createContext<AppContextType | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [currentView, setCurrentView] = useState<ViewMode>(() => {
    const saved = sessionStorage.getItem('viralclip_current_view') as ViewMode | null;
    if (saved && ['dashboard', 'create', 'processing', 'editor', 'exports', 'projects', 'settings'].includes(saved)) {
      return saved;
    }
    return 'dashboard';
  });
  const [projects, setProjects] = useState<VideoProject[]>([]);
  const [activeProject, setActiveProject] = useState<VideoProject | null>(null);
  const [activeHighlight, setActiveHighlight] = useState<HighlightMoment | null>(null);

  const activeWsRef = useRef<WebSocket | null>(null);
  const objectUrlsRef = useRef<string[]>([]);

  const [subtitleStyle, setSubtitleStyle] = useState<SubtitleStyle>(() => {
    const saved = localStorage.getItem('viralclip_subtitle_style');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        return defaultSubtitleStyle;
      }
    }
    return defaultSubtitleStyle;
  });

  const [layoutConfig, setLayoutConfig] = useState<LayoutConfig>(() => {
    const saved = localStorage.getItem('viralclip_layout_config');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch {
        return defaultLayoutConfig;
      }
    }
    return defaultLayoutConfig;
  });

  const [settings, setSettings] = useState<AppSettings>(() => {
    const saved = localStorage.getItem('viralclip_ui_preferences');
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        return {
          ...defaultSettings,
          ...parsed,
          geminiApiKey: '', // Never populate from storage
          openaiApiKey: '', // Never populate from storage
        };
      } catch {
        return defaultSettings;
      }
    }
    return defaultSettings;
  });

  const [backendStatus, setBackendStatus] = useState({
    online: false,
    ffmpeg: false,
    ffprobe: false,
    gpuEncoder: null as string | null,
    whisper: false,
    pythonVersion: 'Unknown',
  });

  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage((prev) => (prev === msg ? null : prev));
    }, 3500);
  };

  const refreshBackendStatus = async () => {
    const status = await checkBackendHealth();
    setBackendStatus(status);
  };

  // Sync projects from backend on mount and periodically
  const loadProjectsFromBackend = async () => {
    try {
      const backendJobs = await fetchJobs();
      if (backendJobs && backendJobs.length > 0) {
        const mapped: VideoProject[] = backendJobs.map((j: any) => ({
          id: j.video_id || j.id,
          title: j.title || 'Processed Video',
          sourceType: j.source_type || 'local',
          localVideoUrl: j.video_url || (j.video_id ? `/api/videos/${j.video_id}/stream` : undefined),
          duration: j.duration || 0,
          width: j.width || 1920,
          height: j.height || 1080,
          fps: j.fps || 30,
          fileSizeMb: j.file_size_mb || 0,
          status: j.status || 'ready',
          progress: j.progress || 0,
          currentStage: j.current_stage || 'Processing',
          errorMessage: j.error_message || undefined,
          activeJobId: j.id,
          detectedLanguage: j.detected_language,
          detectedLanguageProbability: j.detected_language_probability,
          transcripts: [],
          highlights: [],
          selectedClipIds: [],
          createdAt: j.created_at || new Date().toISOString(),
          updatedAt: j.created_at || new Date().toISOString(),
          exportedClips: [],
        }));

        const savedJobId = sessionStorage.getItem('viralclip_active_job_id');
        setProjects(mapped);
        setActiveProject((prev) => {
          if (prev) {
            const found = mapped.find((p) => p.id === prev.id || p.activeJobId === prev.activeJobId);
            if (found) return found;
          }
          if (savedJobId) {
            const savedFound = mapped.find((p) => p.activeJobId === savedJobId || p.id === savedJobId);
            if (savedFound) return savedFound;
          }
          return mapped[0];
        });

        // Recover full job details (transcripts, highlights, export history) for all jobs on refresh
        for (const j of backendJobs) {
          if (j.id) {
            syncJobDetails(j.id);
            if (['queued', 'analyzing', 'transcribing', 'detecting'].includes(j.status) && !activeWsRef.current) {
              activeWsRef.current = connectJobWebSocket(j.id, (data) => {
                setProjects((prev) =>
                  prev.map((p) =>
                    p.activeJobId === j.id
                      ? {
                          ...p,
                          progress: data.progress,
                          currentStage: data.stage,
                          status: data.status as any,
                          detectedLanguage: data.detected_language ?? p.detectedLanguage,
                          detectedLanguageProbability: data.detected_language_probability ?? p.detectedLanguageProbability,
                        }
                      : p
                  )
                );
                setActiveProject((prev) =>
                  prev && prev.activeJobId === j.id
                    ? {
                        ...prev,
                        progress: data.progress,
                        currentStage: data.stage,
                        status: data.status as any,
                        detectedLanguage: data.detected_language ?? prev.detectedLanguage,
                        detectedLanguageProbability: data.detected_language_probability ?? prev.detectedLanguageProbability,
                      }
                    : prev
                );
                if (data.progress >= 100 || data.status === 'ready') {
                  syncJobDetails(j.id, true);
                }
              });
            }
          }
        }
      }
    } catch {
      // Backend may be offline or empty
    }
  };

  useEffect(() => {
    refreshBackendStatus();
    loadProjectsFromBackend();
    const interval = setInterval(() => {
      refreshBackendStatus();
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  // Cleanup object URLs on unmount
  useEffect(() => {
    return () => {
      if (activeWsRef.current) {
        activeWsRef.current.close();
      }
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  // Save only non-sensitive UI preferences in localStorage
  useEffect(() => {
    const { geminiApiKey, openaiApiKey, ...safePreferences } = settings;
    localStorage.setItem('viralclip_ui_preferences', JSON.stringify(safePreferences));
  }, [settings]);

  useEffect(() => {
    localStorage.setItem('viralclip_subtitle_style', JSON.stringify(subtitleStyle));
  }, [subtitleStyle]);

  useEffect(() => {
    localStorage.setItem('viralclip_layout_config', JSON.stringify(layoutConfig));
  }, [layoutConfig]);

  useEffect(() => {
    sessionStorage.setItem('viralclip_current_view', currentView);
    if (currentView === 'editor' && activeProject?.activeJobId) {
      syncJobDetails(activeProject.activeJobId, true);
    }
  }, [currentView, activeProject?.activeJobId]);

  useEffect(() => {
    if (activeProject?.activeJobId) {
      sessionStorage.setItem('viralclip_active_job_id', activeProject.activeJobId);
    }
  }, [activeProject?.activeJobId]);

  const loadDemoProject = () => {
    setProjects((prev) => {
      const exists = prev.some((p) => p.id === sampleDemoProject.id);
      if (exists) return prev;
      return [sampleDemoProject, ...prev];
    });
    setActiveProject(sampleDemoProject);
    setActiveHighlight(sampleDemoProject.highlights[0] || null);
    showToast('Loaded Demo Sample Project');
  };

  const syncJobDetails = async (jobId: string, includeWords: boolean = false) => {
    try {
      const details = await fetchJobDetails(jobId, includeWords);
      if (!details) return;

      const highlights: HighlightMoment[] = (details.clips || []).map((c: any) => ({
        id: c.id,
        title: c.title,
        startTime: c.start_time,
        endTime: c.end_time,
        duration: c.duration,
        score: c.score,
        reason: c.reason,
        category: c.category || 'hype',
        tags: c.tags || c.hashtags || ['#shorts', '#viralclip'],
        selected: c.selected !== undefined ? Boolean(c.selected) : c.status === 'selected',
        titleSuggestions: c.title_suggestions || [],
        suggestedTitle: c.suggested_title || c.title,
        suggestedDescription: c.suggested_description || c.description,
        thumbnailText: c.thumbnail_text || '',
        thumbnailTimestamp: c.thumbnail_timestamp,
      }));

      const exported: ExportedClip[] = (details.clips || [])
        .filter((c: any) => c.status === 'exported')
        .map((c: any) => ({
          id: c.id,
          title: c.title,
          description: c.description || c.suggested_description || c.reason || '',
          hashtags: c.tags || c.hashtags || ['#shorts', '#viralclip'],
          videoUrl: c.export_url || `/api/exports/${c.id}/download`,
          thumbnailUrl: '',
          duration: c.duration,
          createdAt: details.created_at,
          fileSizeMb: c.file_size_mb ?? 0,
          resolution: c.resolution || c.sync_report?.resolution || '1080x1920',
          encoderUsed: c.encoder_used || c.sync_report?.encoder || details.encoder_used || 'CPU (libx264)',
          syncOffsetMs: c.sync_report?.sync_offset_ms ?? 0,
          layout: c.layout || 'facecam_gameplay',
          downloadsCount: 0,
          titleSuggestions: c.title_suggestions || [],
          thumbnailText: c.thumbnail_text || '',
          thumbnailTimestamp: c.thumbnail_timestamp,
        }));

      const selectedIds = highlights.filter((h) => h.selected).map((h) => h.id);
      const fallbackSelectedIds = selectedIds.length > 0 ? selectedIds : highlights.slice(0, 2).map((h) => h.id);

      setProjects((prev) =>
        prev.map((p) => {
          if (p.activeJobId !== jobId && p.id !== details.video_id) return p;
          return {
            ...p,
            title: details.video?.filename || p.title,
            localVideoUrl: p.localVideoUrl || details.video?.video_url || (details.video_id ? `/api/videos/${details.video_id}/stream` : undefined),
            duration: details.video?.duration || p.duration,
            width: details.video?.width || p.width,
            height: details.video?.height || p.height,
            fps: details.video?.fps || p.fps,
            fileSizeMb: details.video?.file_size_mb ?? p.fileSizeMb,
            status: details.status,
            importState: details.import_state || details.status,
            progress: details.progress,
            currentStage: details.current_stage,
            errorMessage: details.error_message || undefined,
            bytesTransferred: details.bytes_transferred,
            totalBytes: details.total_bytes,
            speedBps: details.speed_bps,
            etaSeconds: details.eta_seconds,
            canResume: details.can_resume,
            transcribedSeconds: details.transcribed_seconds,
            totalAudioSeconds: details.total_audio_seconds,
            whisperModel: details.whisper_model,
            whisperDevice: details.whisper_device,
            realtimeFactor: details.realtime_factor,
            detectedLanguage: details.detected_language || p.detectedLanguage,
            detectedLanguageProbability: details.detected_language_probability ?? p.detectedLanguageProbability,
            transcripts: details.transcripts || [],
            highlights,
            exportedClips: exported,
            selectedClipIds: fallbackSelectedIds,
          };
        })
      );

      setActiveProject((prev) => {
        if (!prev || (prev.activeJobId !== jobId && prev.id !== details.video_id)) return prev;
        return {
          ...prev,
          title: details.video?.filename || prev.title,
          localVideoUrl: prev.localVideoUrl || details.video?.video_url || (details.video_id ? `/api/videos/${details.video_id}/stream` : undefined),
          duration: details.video?.duration || prev.duration,
          width: details.video?.width || prev.width,
          height: details.video?.height || prev.height,
          fps: details.video?.fps || prev.fps,
          fileSizeMb: details.video?.file_size_mb ?? prev.fileSizeMb,
          status: details.status,
          importState: details.import_state || details.status,
          progress: details.progress,
          currentStage: details.current_stage,
          errorMessage: details.error_message || undefined,
          bytesTransferred: details.bytes_transferred,
          totalBytes: details.total_bytes,
          speedBps: details.speed_bps,
          etaSeconds: details.eta_seconds,
          canResume: details.can_resume,
          detectedLanguage: details.detected_language || prev.detectedLanguage,
          detectedLanguageProbability: details.detected_language_probability ?? prev.detectedLanguageProbability,
          transcripts: details.transcripts || [],
          highlights,
          exportedClips: exported,
          selectedClipIds: fallbackSelectedIds,
        };
      });

      if (highlights.length > 0 && !activeHighlight) {
        setActiveHighlight(highlights[0]);
      }
    } catch {
      // ignore
    }
  };

  const createProjectFromLocal = async (
    file: File,
    onUploadProgress?: (p: number) => void,
    options?: { signal?: AbortSignal; onTelemetry?: (t: ImportTelemetry) => void; language?: string }
  ): Promise<VideoProject> => {
    // 1. Create client-side object URL for immediate local preview
    const localVideoUrl = URL.createObjectURL(file);
    objectUrlsRef.current.push(localVideoUrl);

    // 2. Perform real chunked resumable upload to backend
    const res = await uploadVideoFile(file, onUploadProgress, {
      language: options?.language,
      whisperModel: settings.whisperModel,
      geminiApiKey: settings.geminiApiKey,
      openaiApiKey: settings.openaiApiKey,
      signal: options?.signal,
      onTelemetry: options?.onTelemetry,
    });

    const newProj: VideoProject = {
      id: res.id,
      title: res.title,
      sourceType: 'local',
      localVideoUrl,
      duration: res.duration,
      width: res.width,
      height: res.height,
      fps: res.fps,
      fileSizeMb: res.fileSizeMb,
      status: 'analyzing',
      progress: 10,
      currentStage: 'Ingesting video on backend...',
      activeJobId: res.jobId,
      sourceLanguage: options?.language,
      transcripts: [],
      highlights: [],
      selectedClipIds: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      exportedClips: [],
    };

    setProjects((prev) => [newProj, ...prev]);
    setActiveProject(newProj);
    setCurrentView('processing');
    showToast(`Uploaded "${file.name}". Background processing started.`);

    // 3. Connect real WebSocket to receive stage updates
    if (activeWsRef.current) {
      activeWsRef.current.close();
    }

    activeWsRef.current = connectJobWebSocket(
      res.jobId,
      (data) => {
        setProjects((prev) =>
          prev.map((p) => {
            if (p.activeJobId !== res.jobId) return p;
            return {
              ...p,
              progress: data.progress,
              currentStage: data.stage,
              status: data.status as any,
              importState: data.import_state || data.status,
              bytesTransferred: data.bytes_transferred ?? p.bytesTransferred,
              totalBytes: data.total_bytes ?? p.totalBytes,
              speedBps: data.speed_bps ?? p.speedBps,
              etaSeconds: data.eta_seconds ?? p.etaSeconds,
              canResume: data.can_resume ?? p.canResume,
              transcribedSeconds: data.transcribed_seconds ?? p.transcribedSeconds,
              totalAudioSeconds: data.total_audio_seconds ?? p.totalAudioSeconds,
              whisperModel: data.whisper_model ?? p.whisperModel,
              whisperDevice: data.whisper_device ?? p.whisperDevice,
              realtimeFactor: data.realtime_factor ?? p.realtimeFactor,
            };
          })
        );

        setActiveProject((prev) => {
          if (!prev || prev.activeJobId !== res.jobId) return prev;
          return {
            ...prev,
            progress: data.progress,
            currentStage: data.stage,
            status: data.status as any,
            importState: data.import_state || data.status,
            bytesTransferred: data.bytes_transferred ?? prev.bytesTransferred,
            totalBytes: data.total_bytes ?? prev.totalBytes,
            speedBps: data.speed_bps ?? prev.speedBps,
            etaSeconds: data.eta_seconds ?? prev.etaSeconds,
            canResume: data.can_resume ?? prev.canResume,
            transcribedSeconds: data.transcribed_seconds ?? prev.transcribedSeconds,
            totalAudioSeconds: data.total_audio_seconds ?? prev.totalAudioSeconds,
            whisperModel: data.whisper_model ?? prev.whisperModel,
            whisperDevice: data.whisper_device ?? prev.whisperDevice,
            realtimeFactor: data.realtime_factor ?? prev.realtimeFactor,
          };
        });

        if (data.progress >= 100 || data.status === 'ready' || data.status === 'COMPLETED') {
          syncJobDetails(res.jobId);
        }
      },
      () => {
        // Fallback polling if WebSocket fails
        const poll = setInterval(async () => {
          await syncJobDetails(res.jobId);
        }, 2000);
        setTimeout(() => clearInterval(poll), 12000);
      }
    );

    // Fetch initial details
    setTimeout(() => syncJobDetails(res.jobId), 1500);
    return newProj;
  };

  const createProjectFromUrl = async (
    url: string,
    platform: 'youtube' | 'twitch',
    options?: { language?: string }
  ): Promise<VideoProject> => {
    const res = await importFromUrl(url, platform, {
      language: options?.language,
      whisperModel: settings.whisperModel,
      geminiApiKey: settings.geminiApiKey,
      openaiApiKey: settings.openaiApiKey,
    });

    const newProj: VideoProject = {
      id: res.id,
      title: res.title,
      sourceType: platform,
      sourceUrl: url,
      localVideoUrl: res.videoUrl,
      duration: res.duration,
      width: res.width,
      height: res.height,
      fps: res.fps,
      fileSizeMb: res.fileSizeMb,
      status: 'analyzing',
      progress: 15,
      currentStage: `Importing ${platform.toUpperCase()} stream on backend...`,
      activeJobId: res.jobId,
      sourceLanguage: options?.language,
      transcripts: [],
      highlights: [],
      selectedClipIds: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      exportedClips: [],
    };

    setProjects((prev) => [newProj, ...prev]);
    setActiveProject(newProj);
    setCurrentView('processing');
    showToast(`Imported ${platform.toUpperCase()} video. Processing started.`);

    // Connect WebSocket
    if (activeWsRef.current) {
      activeWsRef.current.close();
    }

    activeWsRef.current = connectJobWebSocket(
      res.jobId,
      (data) => {
        setProjects((prev) =>
          prev.map((p) => {
            if (p.activeJobId !== res.jobId) return p;
            return {
              ...p,
              progress: data.progress,
              currentStage: data.stage,
              status: data.status as any,
              importState: data.import_state || data.status,
              bytesTransferred: data.bytes_transferred ?? p.bytesTransferred,
              totalBytes: data.total_bytes ?? p.totalBytes,
              speedBps: data.speed_bps ?? p.speedBps,
              etaSeconds: data.eta_seconds ?? p.etaSeconds,
              canResume: data.can_resume ?? p.canResume,
              transcribedSeconds: data.transcribed_seconds ?? p.transcribedSeconds,
              totalAudioSeconds: data.total_audio_seconds ?? p.totalAudioSeconds,
              whisperModel: data.whisper_model ?? p.whisperModel,
              whisperDevice: data.whisper_device ?? p.whisperDevice,
              realtimeFactor: data.realtime_factor ?? p.realtimeFactor,
            };
          })
        );

        setActiveProject((prev) => {
          if (!prev || prev.activeJobId !== res.jobId) return prev;
          return {
            ...prev,
            progress: data.progress,
            currentStage: data.stage,
            status: data.status as any,
            importState: data.import_state || data.status,
            bytesTransferred: data.bytes_transferred ?? prev.bytesTransferred,
            totalBytes: data.total_bytes ?? prev.totalBytes,
            speedBps: data.speed_bps ?? prev.speedBps,
            etaSeconds: data.eta_seconds ?? prev.etaSeconds,
            canResume: data.can_resume ?? prev.canResume,
            transcribedSeconds: data.transcribed_seconds ?? prev.transcribedSeconds,
            totalAudioSeconds: data.total_audio_seconds ?? prev.totalAudioSeconds,
            whisperModel: data.whisper_model ?? prev.whisperModel,
            whisperDevice: data.whisper_device ?? prev.whisperDevice,
            realtimeFactor: data.realtime_factor ?? prev.realtimeFactor,
          };
        });

        if (data.progress >= 100 || data.status === 'ready' || data.status === 'COMPLETED') {
          syncJobDetails(res.jobId);
        }
      }
    );

    setTimeout(() => syncJobDetails(res.jobId), 1500);
    return newProj;
  };

  const deleteProjectHandler = async (id: string) => {
    const proj = projects.find((p) => p.id === id);
    if (proj?.activeJobId) {
      try {
        await deleteJob(proj.activeJobId);
      } catch {
        // ignore
      }
    }

    setProjects((prev) => prev.filter((p) => p.id !== id));
    if (activeProject?.id === id) {
      setActiveProject(projects.find((p) => p.id !== id) || null);
    }
    showToast('Project removed');
  };

  const toggleHighlightSelection = (projectId: string, highlightId: string) => {
    const targetProj = projects.find((p) => p.id === projectId);
    const willBeSelected = targetProj ? !targetProj.selectedClipIds.includes(highlightId) : true;
    if (targetProj && !targetProj.isDemo) {
      updateClipOnBackend(highlightId, { status: willBeSelected ? 'selected' : 'detected' }).catch(() => {});
    }

    setProjects((prev) =>
      prev.map((p) => {
        if (p.id !== projectId) return p;
        const exists = p.selectedClipIds.includes(highlightId);
        const updatedIds = exists
          ? p.selectedClipIds.filter((id) => id !== highlightId)
          : [...p.selectedClipIds, highlightId];
        const updatedHighlights = p.highlights.map((h) =>
          h.id === highlightId ? { ...h, selected: !exists } : h
        );
        return {
          ...p,
          selectedClipIds: updatedIds,
          highlights: updatedHighlights,
        };
      })
    );

    setActiveProject((prev) => {
      if (!prev || prev.id !== projectId) return prev;
      const exists = prev.selectedClipIds.includes(highlightId);
      const updatedIds = exists
        ? prev.selectedClipIds.filter((id) => id !== highlightId)
        : [...prev.selectedClipIds, highlightId];
      const updatedHighlights = prev.highlights.map((h) =>
        h.id === highlightId ? { ...h, selected: !exists } : h
      );
      return {
        ...prev,
        selectedClipIds: updatedIds,
        highlights: updatedHighlights,
      };
    });
  };

  const openEditorForHighlight = (project: VideoProject, highlight: HighlightMoment) => {
    setActiveProject(project);
    setActiveHighlight(highlight);
    if (project.activeJobId) {
      syncJobDetails(project.activeJobId, true);
    }
    setCurrentView('editor');
  };

  const exportCurrentHighlight = async (clipTitle?: string): Promise<ExportedClip> => {
    if (!activeProject || !activeHighlight) {
      throw new Error('No active highlight to export');
    }

    const title = clipTitle || activeHighlight.title;

    if (!activeProject.activeJobId || activeProject.isDemo) {
      throw new Error('Demo sample data cannot be exported. Upload a real video to render clips.');
    }

    // Real render on the backend (FFmpeg). Any failure is surfaced; nothing is fabricated.
    const res = await exportClipOnBackend(activeProject.activeJobId, activeHighlight.id, {
      title,
      start_time: activeHighlight.startTime,
      end_time: activeHighlight.endTime,
      resolution: settings.outputResolution,
      layout: layoutConfig.preset,
      facecam_crop: {
        heightPercent: layoutConfig.facecamHeightPercent,
        zoom: layoutConfig.facecamZoom,
        offsetX: (layoutConfig.facecamOffsetX ?? 0) / 40,
        offsetY: layoutConfig.facecamOffsetY / 40,
        pipScale: layoutConfig.pipScale,
        pipCorner: layoutConfig.pipCorner,
      },
      gameplay_crop: {
        heightPercent: layoutConfig.gameplayHeightPercent,
        zoom: layoutConfig.gameplayZoom,
        offsetX: (layoutConfig.gameplayOffsetX ?? 0) / 40,
        offsetY: layoutConfig.gameplayOffsetY / 40,
        pipScale: layoutConfig.pipScale,
        pipCorner: layoutConfig.pipCorner,
      },
      subtitle_style: subtitleStyle,
      prefer_hardware: settings.hardwareAcceleration,
      bitrate_kbps: settings.targetBitrate,
      fps: 30,
      quality: 'balanced',
    });

    const newClip: ExportedClip = {
      id: activeHighlight.id,
      title: res.title || title,
      description: res.description || activeHighlight.suggestedDescription || activeHighlight.reason || '',
      hashtags: res.hashtags || activeHighlight.tags,
      videoUrl: res.export_url,
      thumbnailUrl: '',
      duration: res.duration,
      createdAt: new Date().toISOString(),
      fileSizeMb: res.file_size_mb,
      resolution: res.resolution,
      encoderUsed: res.encoder,
      syncOffsetMs: res.sync_report?.sync_offset_ms ?? 0,
      layout: layoutConfig.preset,
      downloadsCount: 0,
      titleSuggestions: res.title_suggestions || activeHighlight.titleSuggestions || [],
      thumbnailText: res.thumbnail_text || activeHighlight.thumbnailText || '',
      thumbnailTimestamp: res.thumbnail_timestamp ?? activeHighlight.thumbnailTimestamp,
    };
    setProjects((prev) =>
      prev.map((p) => {
        if (p.id !== activeProject.id) return p;
        return {
          ...p,
          exportedClips: [newClip, ...p.exportedClips],
        };
      })
    );

    setActiveProject((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        exportedClips: [newClip, ...prev.exportedClips],
      };
    });

    showToast(`Clip exported: "${newClip.title}"`);
    setCurrentView('exports');
    return newClip;
  };

  const saveTranscriptCorrection = async (
    clipId: string,
    segments: Array<{ id?: string; start?: number; end?: number; text: string; words?: any[] }>
  ): Promise<void> => {
    try {
      const res = await updateClipTranscript(clipId, segments);
      if (res && res.transcript) {
        // Update local state transcripts
        const updatedSegs = res.transcript.map((t: any) => ({
          id: t.id,
          start: t.start,
          end: t.end,
          text: t.text,
          confidence: 1.0,
          words: t.words,
        }));

        setProjects((prev) =>
          prev.map((p) => {
            if (p.id !== activeProject?.id) return p;
            return {
              ...p,
              transcripts: p.transcripts.map((old) => {
                const match = updatedSegs.find((u: any) => u.id === old.id);
                return match || old;
              }),
            };
          })
        );

        setActiveProject((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            transcripts: prev.transcripts.map((old) => {
              const match = updatedSegs.find((u: any) => u.id === old.id);
              return match || old;
            }),
          };
        });
      }
      showToast('Transcript corrections saved successfully');
    } catch (err: any) {
      showToast(`Correction failed: ${err?.message || 'Error updating transcript'}`);
      throw err;
    }
  };

  const translateCurrentClipSubtitles = async (targetLanguage: string): Promise<void> => {
    if (!activeHighlight) {
      showToast('Select a clip first to translate its subtitles');
      return;
    }
    try {
      const res = await translateClipSubtitles(activeHighlight.id, targetLanguage, {
        geminiApiKey: settings.geminiApiKey,
        openaiApiKey: settings.openaiApiKey,
      });

      const isReset = targetLanguage === 'original' || targetLanguage === 'source';
      const updatedWords = isReset ? [] : (res.translated_words || []);
      const newFont = res.subtitle_style?.font || res.subtitle_style?.fontFamily || subtitleStyle.fontFamily;

      setSubtitleStyle((prev) => ({
        ...prev,
        subtitleLanguage: targetLanguage,
        translatedWords: updatedWords,
        isTranslated: !isReset,
        fontFamily: newFont,
      }));

      // Also persist to backend clip update
      await updateClipOnBackend(activeHighlight.id, {
        subtitle_style: {
          ...subtitleStyle,
          subtitleLanguage: targetLanguage,
          translatedWords: updatedWords,
          fontFamily: newFont,
        },
      });

      const langLabel = SUPPORTED_LANGUAGES[targetLanguage] || targetLanguage;
      showToast(isReset ? 'Subtitles restored to original spoken language' : `Subtitles translated to ${langLabel}`);
    } catch (err: any) {
      showToast(`Translation failed: ${err?.message || err}`);
      throw err;
    }
  };

  return (
    <AppContext.Provider
      value={{
        currentView,
        setCurrentView,
        projects,
        activeProject,
        setActiveProject,
        activeHighlight,
        setActiveHighlight,
        subtitleStyle,
        setSubtitleStyle,
        layoutConfig,
        setLayoutConfig,
        settings,
        setSettings,
        backendStatus,
        refreshBackendStatus,
        createProjectFromLocal,
        createProjectFromUrl,
        deleteProject: deleteProjectHandler,
        toggleHighlightSelection,
        exportCurrentHighlight,
        openEditorForHighlight,
        saveTranscriptCorrection,
        translateCurrentClipSubtitles,
        loadDemoProject,
        syncJobDetails,
        toastMessage,
        showToast,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
