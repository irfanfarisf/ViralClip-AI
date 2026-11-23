import type { ImportTelemetry, VideoProject } from '../types';

const API_BASE = '/api';

export interface BackendHealthResponse {
  online: boolean;
  ffmpeg: boolean;
  ffprobe: boolean;
  gpuEncoder: string | null;
  whisper: boolean;
  whisperHardware?: {
    device?: string;
    compute_type?: string;
    cpu_threads?: number;
    gpu_accelerated?: boolean;
    cpu_name?: string;
    amd_gpu?: string | null;
    backend_note?: string;
    label?: string;
  } | null;
  pythonVersion: string;
}

export const checkBackendHealth = async (): Promise<BackendHealthResponse> => {
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      const data = await res.json();
      return {
        online: true,
        ffmpeg: Boolean(data.ffmpeg),
        ffprobe: Boolean(data.ffprobe),
        gpuEncoder: data.gpu_encoder ?? null,
        whisper: Boolean(data.whisper),
        whisperHardware: data.whisper_hardware ?? null,
        pythonVersion: data.python_version || '3.12+',
      };
    }
  } catch {
    // Backend is offline or unreachable
  }
  return {
    online: false,
    ffmpeg: false,
    ffprobe: false,
    gpuEncoder: null,
    whisper: false,
    whisperHardware: null,
    pythonVersion: 'Unknown',
  };
};

const CHUNK_SIZE_BYTES = 16 * 1024 * 1024; // 16 MB default configurable slice for 1-3+ hour videos
const CONCURRENT_UPLOAD_WORKERS = 2; // Pipelined 2-worker upload (<= 32 MB in-flight browser slice memory)

export const cancelUploadSession = async (uploadId: string): Promise<void> => {
  try {
    await fetch(`${API_BASE}/videos/upload/${uploadId}`, { method: 'DELETE' });
  } catch {
    // ignore
  }
};

export const uploadVideoFile = async (
  file: File,
  onProgress?: (percent: number) => void,
  options?: {
    language?: string;
    whisperModel?: string;
    transcriptionProfile?: string;
    geminiApiKey?: string;
    openaiApiKey?: string;
    autoAnalyze?: boolean;
    signal?: AbortSignal;
    onTelemetry?: (t: ImportTelemetry) => void;
  }
): Promise<{
  id: string;
  jobId: string;
  title: string;
  videoUrl: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  fileSizeMb: number;
}> => {
  const fingerprint = `${file.name}:${file.size}:${file.lastModified || 0}`;

  if (options?.onTelemetry) {
    options.onTelemetry({
      stage: 'INITIALIZING',
      progress: 0,
      bytesTransferred: 0,
      totalBytes: file.size,
      speedBps: 0,
      etaSeconds: null,
    });
  }

  // 1. Initialize or resume chunked upload session on backend
  const initRes = await fetch(`${API_BASE}/videos/upload/init`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: options?.signal,
    body: JSON.stringify({
      filename: file.name,
      total_bytes: file.size,
      chunk_size: CHUNK_SIZE_BYTES,
      fingerprint,
      auto_analyze: options?.autoAnalyze ?? true,
      language: options?.language || undefined,
      whisper_model: options?.whisperModel || undefined,
      transcription_profile: options?.transcriptionProfile || undefined,
      gemini_api_key: options?.geminiApiKey || undefined,
      openai_api_key: options?.openaiApiKey || undefined,
    }),
  });

  if (!initRes.ok) {
    let errMsg = `Failed to initialize upload (HTTP ${initRes.status})`;
    try {
      const errData = await initRes.json();
      errMsg = errData.detail || errMsg;
    } catch {
      // ignore
    }
    throw new Error(errMsg);
  }

  const session = await initRes.json();
  const uploadId: string = session.upload_id;
  const chunkSize: number = session.chunk_size || CHUNK_SIZE_BYTES;
  const totalChunks: number = session.total_chunks || Math.max(1, Math.ceil(file.size / chunkSize));
  const receivedSet = new Set<number>(session.received_chunks || []);

  if (options?.onTelemetry) {
    options.onTelemetry({
      stage: 'UPLOADING',
      progress: Math.round(((session.bytes_received || 0) / Math.max(file.size, 1)) * 100),
      bytesTransferred: session.bytes_received || 0,
      totalBytes: file.size,
      speedBps: 0,
      etaSeconds: null,
      chunksReceived: receivedSet.size,
      totalChunks,
      resumed: Boolean(session.resumed),
      uploadId,
    });
  }

  // 2. Stream missing chunks with 2 pipelined workers (<= 32 MB browser memory footprint)
  const pendingIndices: number[] = [];
  for (let idx = 0; idx < totalChunks; idx++) {
    if (!receivedSet.has(idx)) {
      pendingIndices.push(idx);
    }
  }

  let cursor = 0;
  let highWaterBytes = Number(session.bytes_received || 0);
  let highWaterPct = Math.round((highWaterBytes / Math.max(file.size, 1)) * 95);
  let abortTriggered = false;

  const uploadWorker = async () => {
    while (cursor < pendingIndices.length) {
      if (options?.signal?.aborted) {
        if (!abortTriggered) {
          abortTriggered = true;
          await cancelUploadSession(uploadId);
        }
        throw new Error('Upload cancelled by user');
      }
      const idx = pendingIndices[cursor++];
      if (idx === undefined) break;

      const start = idx * chunkSize;
      const end = Math.min(start + chunkSize, file.size);
      const slice = file.slice(start, end);

      const chunkRes = await fetch(
        `${API_BASE}/videos/upload/${uploadId}/chunk?chunk_index=${idx}&offset=${start}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/octet-stream' },
          body: slice,
          signal: options?.signal,
        }
      );

      if (!chunkRes.ok) {
        let errMsg = `Chunk #${idx} failed (HTTP ${chunkRes.status})`;
        try {
          const errData = await chunkRes.json();
          errMsg = errData.detail || errMsg;
        } catch {
          // ignore
        }
        throw new Error(errMsg);
      }

      const cData = await chunkRes.json();
      highWaterBytes = Math.max(highWaterBytes, Number(cData.bytes_received ?? end));
      const pct = Math.max(highWaterPct, Number(cData.progress ?? Math.round((highWaterBytes / Math.max(file.size, 1)) * 95)));
      highWaterPct = pct;
      if (onProgress) onProgress(pct);
      if (options?.onTelemetry) {
        options.onTelemetry({
          stage: cData.stage || 'UPLOADING',
          progress: pct,
          bytesTransferred: highWaterBytes,
          totalBytes: cData.total_bytes ?? file.size,
          speedBps: cData.speed_bps ?? 0,
          etaSeconds: cData.eta_seconds ?? null,
          chunksReceived: cData.chunks_received ?? idx + 1,
          totalChunks,
          resumed: Boolean(session.resumed),
          uploadId,
        });
      }
    }
  };

  if (pendingIndices.length > 0) {
    const workerCount = Math.min(CONCURRENT_UPLOAD_WORKERS, pendingIndices.length);
    try {
      await Promise.all(Array.from({ length: workerCount }, () => uploadWorker()));
    } catch (err) {
      if (options?.signal?.aborted && !abortTriggered) {
        abortTriggered = true;
        await cancelUploadSession(uploadId);
      }
      throw err;
    }
  }

  // 3. Finalize & verify integrity + extract FFprobe metadata
  if (options?.onTelemetry) {
    options.onTelemetry({
      stage: 'VALIDATING',
      progress: 96,
      bytesTransferred: file.size,
      totalBytes: file.size,
      speedBps: 0,
      etaSeconds: 0,
      chunksReceived: totalChunks,
      totalChunks,
      uploadId,
    });
  }

  const compRes = await fetch(`${API_BASE}/videos/upload/${uploadId}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: options?.signal,
    body: JSON.stringify({ auto_analyze: options?.autoAnalyze ?? true }),
  });

  if (!compRes.ok) {
    let errMsg = `Upload finalization failed (HTTP ${compRes.status})`;
    try {
      const errData = await compRes.json();
      errMsg = errData.detail || errMsg;
    } catch {
      // ignore
    }
    throw new Error(errMsg);
  }

  const finalData = await compRes.json();
  if (onProgress) onProgress(100);
  if (options?.onTelemetry) {
    options.onTelemetry({
      stage: 'COMPLETED',
      progress: 100,
      bytesTransferred: file.size,
      totalBytes: file.size,
      speedBps: 0,
      etaSeconds: 0,
      chunksReceived: totalChunks,
      totalChunks,
      uploadId,
    });
  }

  return {
    id: finalData.id,
    jobId: finalData.job_id,
    title: finalData.title || file.name,
    videoUrl: finalData.video_url || `/api/videos/${finalData.id}/stream`,
    duration: finalData.duration || 60,
    width: finalData.width || 1920,
    height: finalData.height || 1080,
    fps: finalData.fps || 30,
    fileSizeMb: finalData.file_size_mb || Math.round((file.size / (1024 * 1024)) * 10) / 10,
  };
};

export const importFromUrl = async (
  url: string,
  platform: 'youtube' | 'twitch',
  options?: {
    language?: string;
    whisperModel?: string;
    transcriptionProfile?: string;
    geminiApiKey?: string;
    openaiApiKey?: string;
    autoAnalyze?: boolean;
  }
): Promise<{
  id: string;
  jobId: string;
  title: string;
  videoUrl: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  fileSizeMb: number;
  importState?: string;
}> => {
  const res = await fetch(`${API_BASE}/videos/import-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      platform,
      background: true,
      auto_analyze: options?.autoAnalyze ?? true,
      language: options?.language || undefined,
      whisper_model: options?.whisperModel || undefined,
      transcription_profile: options?.transcriptionProfile || undefined,
      gemini_api_key: options?.geminiApiKey || undefined,
      openai_api_key: options?.openaiApiKey || undefined,
    }),
  });

  if (!res.ok) {
    let message = `Failed to import from ${platform.toUpperCase()}`;
    try {
      const err = await res.json();
      message = err.detail || message;
    } catch {
      // ignore
    }
    throw new Error(message);
  }

  const data = await res.json();
  return {
    id: data.id,
    jobId: data.job_id,
    title: data.title,
    videoUrl: data.video_url,
    duration: data.duration,
    width: data.width,
    height: data.height,
    fps: data.fps,
    fileSizeMb: data.file_size_mb,
    importState: data.import_state,
  };
};

export const fetchJobs = async (): Promise<any[]> => {
  const res = await fetch(`${API_BASE}/jobs`);
  if (!res.ok) {
    throw new Error(`Failed to fetch jobs (HTTP ${res.status})`);
  }
  return await res.json();
};

export const fetchJobDetails = async (jobId: string, includeWords: boolean = false): Promise<any> => {
  const q = includeWords ? '?include_words=true' : '';
  const res = await fetch(`${API_BASE}/jobs/${jobId}${q}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch job ${jobId} (HTTP ${res.status})`);
  }
  return await res.json();
};

export const startJob = async (jobId: string): Promise<void> => {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/start`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`Failed to start job ${jobId}`);
  }
};

export const cancelJob = async (jobId: string): Promise<void> => {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' });
  if (!res.ok) {
    throw new Error(`Failed to cancel job ${jobId}`);
  }
};

export const deleteJob = async (jobId: string): Promise<void> => {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(`Failed to delete job ${jobId}`);
  }
};

export const updateClipOnBackend = async (
  clipId: string,
  updates: {
    start_time?: number;
    end_time?: number;
    suggested_title?: string;
    title_suggestions?: string[];
    suggested_description?: string;
    hashtags?: string[];
    thumbnail_text?: string;
    thumbnail_timestamp?: number;
    status?: string;
    layout?: string;
    facecam_crop?: any;
    gameplay_crop?: any;
    subtitle_style?: any;
  }
): Promise<any> => {
  const res = await fetch(`${API_BASE}/clips/${clipId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    let err = 'Failed to update clip';
    try {
      const data = await res.json();
      err = data.detail || err;
    } catch {
      // ignore
    }
    throw new Error(err);
  }
  return await res.json();
};

export const generateClipMetadata = async (
  clipId: string,
  options?: { geminiApiKey?: string; openaiApiKey?: string; useAiApi?: boolean }
): Promise<any> => {
  const res = await fetch(`${API_BASE}/clips/${clipId}/metadata`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      gemini_api_key: options?.geminiApiKey,
      openai_api_key: options?.openaiApiKey,
      use_ai_api: options?.useAiApi ?? true,
    }),
  });
  if (!res.ok) {
    let err = 'Failed to generate metadata';
    try {
      const data = await res.json();
      err = data.detail || err;
    } catch {
      // ignore
    }
    throw new Error(err);
  }
  return await res.json();
};

export const translateClipSubtitles = async (
  clipId: string,
  targetLanguage: string,
  options?: { geminiApiKey?: string; openaiApiKey?: string }
): Promise<{
  clip_id: string;
  source_language?: string;
  target_language: string;
  provider?: string;
  partial?: boolean;
  warnings?: string[];
  translated_segments?: any[];
  translated_words: any[];
  subtitle_style: any;
}> => {
  const res = await fetch(`${API_BASE}/clips/${clipId}/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      target_language: targetLanguage,
      gemini_api_key: options?.geminiApiKey,
      openai_api_key: options?.openaiApiKey,
    }),
  });
  if (!res.ok) {
    let err = 'Subtitle translation failed';
    try {
      const data = await res.json();
      err = data.detail || err;
    } catch {
      // ignore
    }
    throw new Error(err);
  }
  return await res.json();
};

export const fetchSupportedLanguages = async (): Promise<Record<string, string>> => {
  try {
    const res = await fetch(`${API_BASE}/languages`);
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // fallback
  }
  return {
    auto: 'Auto-Detect Language',
    en: 'English',
    ml: 'Malayalam (മലയാളം)',
    hi: 'Hindi (हिन्दी)',
    ta: 'Tamil (தமிழ்)',
    te: 'Telugu (తెలుగు)',
    kn: 'Kannada (ಕನ್ನಡ)',
    ar: 'Arabic (العربية)',
    es: 'Spanish (Español)',
    fr: 'French (Français)',
    de: 'German (Deutsch)',
    ja: 'Japanese (日本語)',
    ko: 'Korean (한국어)',
  };
};

export const exportClipOnBackend = async (
  jobId: string,
  clipId: string,
  settings: {
    title?: string;
    start_time?: number;
    end_time?: number;
    resolution?: string;
    layout?: string;
    facecam_crop?: any;
    gameplay_crop?: any;
    subtitle_style?: any;
    burn_subtitles?: boolean;
    prefer_hardware?: boolean;
    fps?: number;
    bitrate_kbps?: number;
    quality?: string;
  }
): Promise<{
  id: string;
  title: string;
  status: string;
  export_url: string;
  download_url?: string;
  sync_report: any;
  duration: number;
  resolution: string;
  codec?: string;
  audio_codec?: string;
  encoder: string;
  gpu_accelerated?: boolean;
  file_size_mb: number;
  description?: string;
  hashtags?: string[];
  title_suggestions?: string[];
  thumbnail_text?: string;
  thumbnail_timestamp?: number;
}> => {
  const res = await fetch(`${API_BASE}/jobs/${jobId}/clips/${clipId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  });

  if (!res.ok) {
    let err = 'Export failed';
    try {
      const data = await res.json();
      err = data.detail || err;
    } catch {
      // ignore
    }
    throw new Error(err);
  }

  return await res.json();
};

export const updateClipTranscript = async (
  clipId: string,
  segments: Array<{ id?: string; start?: number; end?: number; text: string; words?: any[] }>
): Promise<{ clip_id: string; transcript: any[] }> => {
  const res = await fetch(`${API_BASE}/clips/${clipId}/transcript`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segments }),
  });

  if (!res.ok) {
    let err = 'Failed to update transcript';
    try {
      const data = await res.json();
      err = data.detail || err;
    } catch {
      // ignore
    }
    throw new Error(err);
  }

  return await res.json();
};

export const fetchSyncReport = async (clipId: string): Promise<any> => {
  const res = await fetch(`${API_BASE}/exports/${clipId}/sync-report`);
  if (!res.ok) {
    return null;
  }
  return await res.json();
};

export const connectJobWebSocket = (
  jobId: string,
  onProgress: (data: {
    progress: number;
    stage: string;
    status: string;
    import_state?: string;
    bytes_transferred?: number;
    total_bytes?: number | null;
    speed_bps?: number;
    eta_seconds?: number | null;
    elapsed_seconds?: number;
    can_resume?: boolean;
    transcribed_seconds?: number;
    total_audio_seconds?: number;
    whisper_model?: string;
    whisper_profile?: string;
    whisper_device?: string;
    realtime_factor?: number;
    detected_language?: string;
    detected_language_probability?: number;
  }) => void,
  onError?: (err: any) => void
): WebSocket | null => {
  try {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${API_BASE}/jobs/ws/${jobId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        onProgress(msg);
      } catch {
        // ignore
      }
    };

    ws.onerror = (err) => {
      if (onError) onError(err);
    };

    return ws;
  } catch (err) {
    if (onError) onError(err);
    return null;
  }
};

// Clearly labeled demo template for empty state exploration
export const sampleDemoProject: VideoProject = {
  id: 'demo_sample_project',
  title: 'Demo Stream - 1v3 Clutch Round (Sample Preview)',
  sourceType: 'local',
  duration: 184,
  width: 1920,
  height: 1080,
  fps: 60,
  fileSizeMb: 420,
  status: 'ready',
  progress: 100,
  currentStage: 'Sample Preview (Offline Demo)',
  isDemo: true, // Flagged clearly as demo data
  transcripts: [
    {
      id: 'demo_seg_1',
      start: 2.1,
      end: 6.8,
      text: "Wait, look at this right now! Are you actually seeing what is happening here?!",
      confidence: 0.98,
      words: [
        { word: "Wait,", start: 2.1, end: 2.5, probability: 0.99 },
        { word: "look", start: 2.6, end: 2.8, probability: 0.98 },
        { word: "at", start: 2.9, end: 3.1, probability: 0.97 },
        { word: "this", start: 3.2, end: 3.5, probability: 0.99 },
        { word: "right", start: 3.6, end: 3.9, probability: 0.96 },
        { word: "now!", start: 4.0, end: 4.4, probability: 0.98 },
        { word: "Are", start: 4.6, end: 4.8, probability: 0.97 },
        { word: "you", start: 4.9, end: 5.1, probability: 0.99 },
        { word: "actually", start: 5.2, end: 5.6, probability: 0.98 },
        { word: "seeing", start: 5.7, end: 6.0, probability: 0.96 },
        { word: "what", start: 6.1, end: 6.3, probability: 0.98 },
        { word: "is", start: 6.4, end: 6.5, probability: 0.97 },
        { word: "happening", start: 6.5, end: 6.8, probability: 0.99 },
      ],
    },
    {
      id: 'demo_seg_2',
      start: 7.2,
      end: 12.4,
      text: "There is literally no way this play works out. If we clutch this round, it's over!",
      confidence: 0.96,
      words: [
        { word: "There", start: 7.2, end: 7.4, probability: 0.98 },
        { word: "is", start: 7.5, end: 7.6, probability: 0.97 },
        { word: "literally", start: 7.7, end: 8.2, probability: 0.99 },
        { word: "no", start: 8.3, end: 8.5, probability: 0.98 },
        { word: "way", start: 8.6, end: 8.9, probability: 0.99 },
        { word: "this", start: 9.0, end: 9.2, probability: 0.96 },
        { word: "play", start: 9.3, end: 9.6, probability: 0.98 },
        { word: "works", start: 9.7, end: 10.0, probability: 0.95 },
        { word: "out.", start: 10.1, end: 10.4, probability: 0.97 },
        { word: "If", start: 10.6, end: 10.8, probability: 0.98 },
        { word: "we", start: 10.9, end: 11.1, probability: 0.99 },
        { word: "clutch", start: 11.2, end: 11.6, probability: 0.99 },
        { word: "this", start: 11.7, end: 11.9, probability: 0.97 },
        { word: "round,", start: 12.0, end: 12.2, probability: 0.98 },
        { word: "it's", start: 12.2, end: 12.3, probability: 0.96 },
        { word: "over!", start: 12.3, end: 12.4, probability: 0.99 },
      ],
    },
  ],
  highlights: [
    {
      id: 'demo_hl_1',
      title: '🔥 Insane Impossible 1v3 Clutch Victory (Demo)',
      startTime: 2.0,
      endTime: 12.4,
      duration: 10.4,
      score: 98,
      reason: 'Cadence surge and exclamation detection (Sample Heuristic)',
      category: 'hype',
      tags: ['#clutch', '#insane', '#sample'],
      selected: true,
    },
  ],
  selectedClipIds: ['demo_hl_1'],
  activeClipId: 'demo_hl_1',
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  exportedClips: [],
};
