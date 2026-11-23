export type ViewMode = 
  | 'dashboard' 
  | 'create' 
  | 'processing' 
  | 'editor' 
  | 'exports' 
  | 'projects' 
  | 'settings';

export type VideoSourceType = 'local' | 'youtube' | 'twitch';

export type JobStatus = 
  | 'idle' 
  | 'uploading' 
  | 'analyzing' 
  | 'transcribing' 
  | 'detecting' 
  | 'ready' 
  | 'composing' 
  | 'exporting' 
  | 'complete' 
  | 'failed'
  | 'cancelled'
  | 'QUEUED'
  | 'INITIALIZING'
  | 'DOWNLOADING'
  | 'UPLOADING'
  | 'VALIDATING'
  | 'EXTRACTING_METADATA'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export interface ImportTelemetry {
  stage: string;
  progress: number;
  bytesTransferred: number;
  totalBytes: number | null;
  speedBps: number;
  etaSeconds: number | null;
  chunksReceived?: number;
  totalChunks?: number;
  resumed?: boolean;
  uploadId?: string;
}

export type LayoutPreset = 
  | 'facecam_gameplay'    // Default: Facecam TOP + Gameplay BOTTOM (~3:4)
  | 'smart_crop'          // 1. Smart vertical crop (dynamic subject tracking)
  | 'fullscreen'          // 2. Full-screen video (16:9 preserved on blurred 9:16 canvas)
  | 'gameplay_pip'        // 3. Facecam picture-in-picture
  | 'custom'              // 4. Custom crop
  | 'center_crop'         // 9:16 static center crop
  | 'split_50_50';        // Equal 50/50 split

export type SubtitlePreset = 
  | 'classic_white'       // 1. Classic White
  | 'yellow_highlight'    // 2. Yellow Highlight (Default viral short-form)
  | 'bold_creator'        // 3. Bold Creator Style
  | 'neon_glow'           // 4. Neon Glow
  | 'minimal_captions'    // 5. Minimal Captions
  | 'beast_yellow' 
  | 'neon_cyan' 
  | 'clean_white' 
  | 'boxed_black' 
  | 'fire_gradient';

export const SUPPORTED_LANGUAGES: Record<string, string> = {
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

export type SubtitleAnimation = 'pop' | 'bounce' | 'scale_glow' | 'fade' | 'none';

export interface TranslatedSubtitleSegment {
  segment_id?: string | null;
  start: number;
  end: number;
  original_text?: string;
  text: string;
  confidence?: number;
  words?: TranscriptWord[];
  language?: string;
}

export interface SubtitleStyle {
  enabled: boolean;
  preset: SubtitlePreset;
  fontSize: 'sm' | 'md' | 'lg' | 'xl';
  fontFamily: 'Montserrat' | 'Inter' | 'Bebas Neue' | 'Impact' | 'Arial' | 'Roboto' | 'Nirmala UI' | 'Segoe UI' | 'Malgun Gothic' | string;
  textColor: string;
  highlightColor: string;
  outlineColor?: string;
  outlineWidth?: number;
  shadowDepth?: number;
  backgroundColor: string;
  hasBackground: boolean;
  positionY: number; // 0 to 100 (% from top)
  isUppercase: boolean;
  animateKaraoke: boolean;
  animation?: SubtitleAnimation;
  maxWordsPerLine: number;
  language?: string;
  subtitleLanguage?: string;
  isTranslated?: boolean;
  translatedWords?: TranscriptWord[];
  translatedSegments?: TranslatedSubtitleSegment[];
  translationProvider?: string;
  translationPartial?: boolean;
  translationWarnings?: string[];
}

export interface LayoutConfig {
  preset: LayoutPreset;
  facecamHeightPercent: number; // Default 25% (480px / 1920px)
  gameplayHeightPercent: number; // Default 75% (1440px / 1920px = 3:4)
  facecamOffsetX?: number;
  facecamOffsetY: number;
  facecamZoom: number;
  gameplayOffsetX?: number;
  gameplayOffsetY: number;
  gameplayZoom: number;
  pipScale: number;
  pipCorner: 'top_left' | 'top_right' | 'bottom_left' | 'bottom_right';
}

export interface TranscriptWord {
  word: string;
  start: number;
  end: number;
  probability: number;
}

export interface TranscriptSegment {
  id: string;
  start: number;
  end: number;
  text: string;
  confidence: number;
  words?: TranscriptWord[];
}

export interface HighlightMoment {
  id: string;
  title: string;
  startTime: number;
  endTime: number;
  duration: number;
  score: number; // 0 to 100
  reason: string;
  category: 'energy' | 'laughter' | 'hype' | 'hook' | 'insight' | string;
  tags: string[];
  selected?: boolean;
  titleSuggestions?: string[];
  suggestedTitle?: string;
  suggestedDescription?: string;
  thumbnailText?: string;
  thumbnailTimestamp?: number;
  subtitleStyle?: Partial<SubtitleStyle> & {
    translated_words?: TranscriptWord[];
    translated_segments?: TranslatedSubtitleSegment[];
    subtitle_language?: string;
    is_translated?: boolean;
    translation_provider?: string;
    translation_partial?: boolean;
    translation_warnings?: string[];
    font?: string;
  };
}

export interface ExportedClip {
  id: string;
  title: string;
  description: string;
  hashtags: string[];
  videoUrl: string;
  thumbnailUrl: string;
  duration: number;
  createdAt: string;
  fileSizeMb: number;
  resolution: string;
  encoderUsed: string;
  syncOffsetMs: number;
  layout: LayoutPreset;
  downloadsCount: number;
  titleSuggestions?: string[];
  thumbnailText?: string;
  thumbnailTimestamp?: number;
  subtitleStyle?: Partial<SubtitleStyle> & {
    translated_words?: TranscriptWord[];
    translated_segments?: TranslatedSubtitleSegment[];
    subtitle_language?: string;
    is_translated?: boolean;
    translation_provider?: string;
    translation_partial?: boolean;
    translation_warnings?: string[];
    font?: string;
  };
}

export interface VideoProject {
  id: string;
  title: string;
  sourceType: VideoSourceType;
  sourceUrl?: string;
  localVideoUrl?: string;
  duration: number;
  width: number;
  height: number;
  fps: number;
  fileSizeMb?: number;
  hasAudio?: boolean;
  status: JobStatus;
  importState?: string;
  progress: number;
  currentStage: string;
  errorMessage?: string;
  activeJobId?: string;
  bytesTransferred?: number;
  totalBytes?: number | null;
  speedBps?: number;
  etaSeconds?: number | null;
  canResume?: boolean;
  transcribedSeconds?: number;
  totalAudioSeconds?: number;
  whisperModel?: string;
  whisperProfile?: string;
  whisperDevice?: string;
  realtimeFactor?: number;
  elapsedSeconds?: number;
  detectedLanguage?: string;
  detectedLanguageProbability?: number;
  sourceLanguage?: string;
  isDemo?: boolean;
  transcripts: TranscriptSegment[];
  highlights: HighlightMoment[];
  selectedClipIds: string[];
  activeClipId?: string;
  createdAt: string;
  updatedAt: string;
  exportedClips: ExportedClip[];
}

export type TranscriptionProfile = 'speed' | 'balanced' | 'accuracy';

export interface AppSettings {
  geminiApiKey: string; // Kept in memory, never in localStorage
  openaiApiKey: string; // Kept in memory, never in localStorage
  whisperModel: 'tiny' | 'base' | 'small' | 'medium' | 'large-v3';
  transcriptionProfile: TranscriptionProfile;
  device: 'cpu' | 'cuda';
  defaultLayout: LayoutPreset;
  defaultSubtitlePreset: SubtitlePreset;
  outputResolution: '1080x1920' | '720x1280';
  targetBitrate: number;
  hardwareAcceleration: boolean;
  autoCleanupHours: number;
}
