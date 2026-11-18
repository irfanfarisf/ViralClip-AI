import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Check,
  Copy,
  Hash,
  Image as ImageIcon,
  RotateCcw,
  CheckCircle2,
  FileText,
  Type,
} from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { updateClipOnBackend, generateClipMetadata } from '../../services/api';

interface MetadataControlsProps {
  currentTime?: number;
  onSeek?: (time: number) => void;
}

export const MetadataControls: React.FC<MetadataControlsProps> = ({
  currentTime = 0,
  onSeek,
}) => {
  const {
    activeProject,
    activeHighlight,
    setActiveHighlight,
    settings,
    showToast,
  } = useApp();

  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [copiedField, setCopiedField] = useState<string | null>(null);

  // Local state for metadata
  const [selectedTitle, setSelectedTitle] = useState('');
  const [titleSuggestions, setTitleSuggestions] = useState<string[]>([]);
  const [description, setDescription] = useState('');
  const [hashtags, setHashtags] = useState<string[]>([]);
  const [newTagInput, setNewTagInput] = useState('');
  const [thumbnailText, setThumbnailText] = useState('');
  const [thumbnailTimestamp, setThumbnailTimestamp] = useState(0);

  // Synchronize from activeHighlight
  useEffect(() => {
    if (activeHighlight) {
      setSelectedTitle(activeHighlight.title || activeHighlight.suggestedTitle || '');
      setTitleSuggestions(
        activeHighlight.titleSuggestions && activeHighlight.titleSuggestions.length > 0
          ? activeHighlight.titleSuggestions
          : [activeHighlight.title || 'Viral Short Highlight']
      );
      setDescription(activeHighlight.suggestedDescription || activeHighlight.reason || '');
      setHashtags(activeHighlight.tags || ['#shorts', '#viral']);
      setThumbnailText(activeHighlight.thumbnailText || 'INSANE MOMENT!');
      const defaultTs = activeHighlight.thumbnailTimestamp
        ? activeHighlight.thumbnailTimestamp
        : Number((activeHighlight.startTime + activeHighlight.duration * 0.42).toFixed(2));
      setThumbnailTimestamp(defaultTs);
    }
  }, [activeHighlight]);

  if (!activeHighlight || !activeProject) {
    return null;
  }

  const handleCopy = (text: string, fieldId: string) => {
    navigator.clipboard.writeText(text);
    setCopiedField(fieldId);
    showToast('Copied to clipboard!');
    setTimeout(() => {
      setCopiedField((prev) => (prev === fieldId ? null : prev));
    }, 2000);
  };

  const handleSelectTitle = async (title: string) => {
    setSelectedTitle(title);
    const updated = { ...activeHighlight, title, suggestedTitle: title };
    setActiveHighlight(updated);
    if (!activeProject.isDemo) {
      try {
        await updateClipOnBackend(activeHighlight.id, { suggested_title: title });
      } catch {
        // silently handled
      }
    }
  };

  const handleSaveAll = async () => {
    setIsSaving(true);
    try {
      const updated = {
        ...activeHighlight,
        title: selectedTitle,
        suggestedTitle: selectedTitle,
        suggestedDescription: description,
        tags: hashtags,
        thumbnailText,
        thumbnailTimestamp,
      };
      setActiveHighlight(updated);

      if (!activeProject.isDemo) {
        await updateClipOnBackend(activeHighlight.id, {
          suggested_title: selectedTitle,
          title_suggestions: titleSuggestions,
          suggested_description: description,
          hashtags,
          thumbnail_text: thumbnailText,
          thumbnail_timestamp: thumbnailTimestamp,
        });
      }
      showToast('Metadata successfully saved with clip!');
    } catch (err: any) {
      showToast(err?.message || 'Failed to save metadata');
    } finally {
      setIsSaving(false);
    }
  };

  const handleRegenerateMetadata = async () => {
    if (activeProject.isDemo) {
      showToast('Demo sample project cannot call backend AI generator.');
      return;
    }
    setIsRegenerating(true);
    try {
      const res = await generateClipMetadata(activeHighlight.id, {
        geminiApiKey: settings.geminiApiKey,
        openaiApiKey: settings.openaiApiKey,
        useAiApi: true,
      });

      if (res) {
        const newTitles = res.title_suggestions || [res.title];
        const newRecTitle = res.title || newTitles[0];
        const newDesc = res.suggested_description || res.description || '';
        const newTags = res.tags || res.hashtags || ['#shorts', '#viral'];
        const newThumbText = res.thumbnail_text || 'INSANE MOMENT!';
        const newThumbTs = res.thumbnail_timestamp || Number((activeHighlight.startTime + activeHighlight.duration * 0.42).toFixed(2));

        setSelectedTitle(newRecTitle);
        setTitleSuggestions(newTitles);
        setDescription(newDesc);
        setHashtags(newTags);
        setThumbnailText(newThumbText);
        setThumbnailTimestamp(newThumbTs);

        setActiveHighlight({
          ...activeHighlight,
          title: newRecTitle,
          suggestedTitle: newRecTitle,
          titleSuggestions: newTitles,
          suggestedDescription: newDesc,
          tags: newTags,
          thumbnailText: newThumbText,
          thumbnailTimestamp: newThumbTs,
        });

        showToast('Generated fresh metadata from real transcript!');
      }
    } catch (err: any) {
      showToast(err?.message || 'Failed to regenerate metadata');
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleAddTag = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && newTagInput.trim()) {
      e.preventDefault();
      let tag = newTagInput.trim();
      if (!tag.startsWith('#')) tag = `#${tag}`;
      if (!hashtags.includes(tag)) {
        const updatedTags = [...hashtags, tag];
        setHashtags(updatedTags);
        setActiveHighlight({ ...activeHighlight, tags: updatedTags });
        if (!activeProject.isDemo) {
          updateClipOnBackend(activeHighlight.id, { hashtags: updatedTags }).catch(() => {});
        }
      }
      setNewTagInput('');
    }
  };

  const handleRemoveTag = (tagToRemove: string) => {
    const updatedTags = hashtags.filter((t) => t !== tagToRemove);
    setHashtags(updatedTags);
    setActiveHighlight({ ...activeHighlight, tags: updatedTags });
    if (!activeProject.isDemo) {
      updateClipOnBackend(activeHighlight.id, { hashtags: updatedTags }).catch(() => {});
    }
  };

  const handleCaptureCurrentFrame = () => {
    const clamped = Number(Math.max(activeHighlight.startTime, Math.min(activeHighlight.endTime, currentTime)).toFixed(2));
    setThumbnailTimestamp(clamped);
    setActiveHighlight({ ...activeHighlight, thumbnailTimestamp: clamped });
    if (!activeProject.isDemo) {
      updateClipOnBackend(activeHighlight.id, { thumbnail_timestamp: clamped }).catch(() => {});
    }
    showToast(`Thumbnail timestamp set to ${clamped.toFixed(2)}s`);
  };

  return (
    <div className="space-y-6">
      {/* Banner / Header */}
      <div className="p-4 rounded-2xl bg-gradient-to-r from-purple-950/40 via-[#161a29] to-cyan-950/30 border border-purple-500/30 flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 text-[10px] font-bold border border-purple-500/30">
              <Sparkles className="w-3 h-3 text-cyan-400" />
              AI Shorts Metadata Generation
            </span>
            <span className="text-[11px] text-emerald-400 font-medium flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              Real Transcript Grounded
            </span>
          </div>
          <p className="text-xs text-slate-300">
            Generate 3 engaging titles, 1 recommended title, YouTube Shorts description, tags, and thumbnail suggestions.
          </p>
        </div>

        <button
          onClick={handleRegenerateMetadata}
          disabled={isRegenerating}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-purple-600/80 hover:bg-purple-600 disabled:opacity-50 text-white text-xs font-bold border border-purple-400/30 transition-all shadow-md active:scale-95 shrink-0"
        >
          <RotateCcw className={`w-3.5 h-3.5 ${isRegenerating ? 'animate-spin' : ''}`} />
          <span>{isRegenerating ? 'Generating...' : 'Regenerate AI'}</span>
        </button>
      </div>

      {/* 1. Three Engaging Title Suggestions */}
      <div className="p-5 rounded-2xl bg-[#12141c] border border-[#212638] space-y-4">
        <div className="flex items-center justify-between">
          <label className="text-xs font-bold text-slate-200 flex items-center gap-2">
            <Type className="w-4 h-4 text-purple-400" />
            <span>Title Suggestions (Choose 1 or Fine-tune)</span>
          </label>
          <span className="text-[11px] text-slate-400">Click to select active title</span>
        </div>

        <div className="space-y-2.5">
          {titleSuggestions.map((titleOption, idx) => {
            const isSelected = selectedTitle === titleOption;
            const isRecommended = idx === 0;

            return (
              <div
                key={idx}
                onClick={() => handleSelectTitle(titleOption)}
                className={`p-3.5 rounded-xl border transition-all cursor-pointer flex items-center justify-between gap-3 ${
                  isSelected
                    ? 'bg-purple-950/40 border-purple-500 shadow-md shadow-purple-950/30'
                    : 'bg-[#161a29] border-[#262c3f] hover:border-slate-600'
                }`}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 border ${
                      isSelected
                        ? 'border-purple-400 bg-purple-600 text-white'
                        : 'border-slate-600 bg-transparent'
                    }`}
                  >
                    {isSelected && <Check className="w-3 h-3" />}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-white truncate">
                        {titleOption}
                      </span>
                      {isRecommended && (
                        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[10px] font-bold uppercase tracking-wider shrink-0">
                          Recommended
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopy(titleOption, `title_option_${idx}`);
                  }}
                  className="p-1.5 rounded-lg bg-[#1f2438] hover:bg-[#2a314d] text-slate-300 text-xs shrink-0 transition-colors"
                  title="Copy title"
                >
                  {copiedField === `title_option_${idx}` ? (
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            );
          })}
        </div>

        {/* Editable active title input */}
        <div className="pt-2">
          <label className="text-[11px] text-slate-400 block mb-1.5 font-medium">
            Active Video Title (Editable, max 60 chars recommended)
          </label>
          <input
            type="text"
            value={selectedTitle}
            onChange={(e) => handleSelectTitle(e.target.value)}
            className="w-full px-3.5 py-2.5 rounded-xl bg-[#161a29] border border-[#2a3044] text-white text-xs font-medium focus:border-purple-500 focus:outline-none transition-colors"
            placeholder="Enter title..."
          />
        </div>
      </div>

      {/* 2. YouTube Shorts Description */}
      <div className="p-5 rounded-2xl bg-[#12141c] border border-[#212638] space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-bold text-slate-200 flex items-center gap-2">
            <FileText className="w-4 h-4 text-cyan-400" />
            <span>Short YouTube Shorts Description</span>
          </label>
          <button
            onClick={() => handleCopy(description, 'desc_field')}
            className="text-[11px] text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
          >
            {copiedField === 'desc_field' ? (
              <Check className="w-3 h-3 text-emerald-400" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
            <span>Copy Description</span>
          </button>
        </div>

        <textarea
          rows={3}
          value={description}
          onChange={(e) => {
            setDescription(e.target.value);
            setActiveHighlight({ ...activeHighlight, suggestedDescription: e.target.value });
          }}
          className="w-full p-3.5 rounded-xl bg-[#161a29] border border-[#2a3044] text-slate-200 text-xs leading-relaxed focus:border-purple-500 focus:outline-none transition-colors resize-none"
          placeholder="Brief description grounded in spoken excerpt..."
        />
        <div className="flex justify-between text-[11px] text-slate-500">
          <span>Derived from Whisper transcript with timecode references</span>
          <span>{description.length} chars</span>
        </div>
      </div>

      {/* 3. Relevant Hashtags */}
      <div className="p-5 rounded-2xl bg-[#12141c] border border-[#212638] space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-bold text-slate-200 flex items-center gap-2">
            <Hash className="w-4 h-4 text-purple-400" />
            <span>Relevant Hashtags (Derived from Keywords)</span>
          </label>
          <button
            onClick={() => handleCopy(hashtags.join(' '), 'tags_field')}
            className="text-[11px] text-purple-400 hover:text-purple-300 flex items-center gap-1 transition-colors"
          >
            {copiedField === 'tags_field' ? (
              <Check className="w-3 h-3 text-emerald-400" />
            ) : (
              <Copy className="w-3 h-3" />
            )}
            <span>Copy All Tags</span>
          </button>
        </div>

        <div className="flex flex-wrap gap-2 items-center">
          {hashtags.map((tag, tIdx) => (
            <span
              key={tIdx}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-xl bg-[#181d2d] text-cyan-300 border border-[#2a334d] text-xs font-medium"
            >
              <span>{tag}</span>
              <button
                type="button"
                onClick={() => handleRemoveTag(tag)}
                className="hover:text-red-400 text-slate-400 transition-colors ml-1 font-bold text-xs"
              >
                ×
              </button>
            </span>
          ))}
          <input
            type="text"
            value={newTagInput}
            onChange={(e) => setNewTagInput(e.target.value)}
            onKeyDown={handleAddTag}
            placeholder="+ Add tag (Enter)"
            className="px-3 py-1 rounded-xl bg-[#141724] border border-dashed border-[#2d344a] text-slate-300 text-xs focus:border-cyan-400 focus:outline-none w-32"
          />
        </div>
      </div>

      {/* 4. Thumbnail Text & Timestamp */}
      <div className="p-5 rounded-2xl bg-[#12141c] border border-[#212638] space-y-4">
        <label className="text-xs font-bold text-slate-200 flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-amber-400" />
          <span>Thumbnail Optimization & Best Frame</span>
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Thumbnail Text Suggestion */}
          <div className="space-y-1.5">
            <span className="text-[11px] text-slate-400 font-medium">
              Suggested Thumbnail Text Overlay (2-4 Uppercase Words)
            </span>
            <input
              type="text"
              value={thumbnailText}
              onChange={(e) => {
                setThumbnailText(e.target.value);
                setActiveHighlight({ ...activeHighlight, thumbnailText: e.target.value });
              }}
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#161a29] border border-[#2a3044] text-amber-300 font-extrabold text-xs tracking-wider uppercase focus:border-amber-400 focus:outline-none transition-colors"
              placeholder="e.g. INSANE MOMENT!"
            />
          </div>

          {/* Suggested Thumbnail Timestamp */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[11px] text-slate-400 font-medium">
              <span>Suggested Frame Timestamp</span>
              <span className="font-mono text-cyan-300">{thumbnailTimestamp.toFixed(2)}s</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="0.1"
                min={activeHighlight.startTime}
                max={activeHighlight.endTime}
                value={thumbnailTimestamp}
                onChange={(e) => {
                  const val = parseFloat(e.target.value) || activeHighlight.startTime;
                  setThumbnailTimestamp(val);
                  setActiveHighlight({ ...activeHighlight, thumbnailTimestamp: val });
                }}
                className="w-24 px-3 py-2 rounded-xl bg-[#161a29] border border-[#2a3044] text-white text-xs font-mono focus:border-cyan-400 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => onSeek && onSeek(thumbnailTimestamp)}
                className="px-3 py-2 rounded-xl bg-[#1b2031] hover:bg-[#252c44] text-slate-200 text-xs font-semibold border border-[#2c344d] transition-colors"
              >
                Seek Frame
              </button>
              <button
                type="button"
                onClick={handleCaptureCurrentFrame}
                className="px-3 py-2 rounded-xl bg-purple-950/60 hover:bg-purple-900/80 text-purple-200 text-xs font-semibold border border-purple-500/30 transition-colors"
                title="Use current playback scrubber time"
              >
                Use Current
              </button>
            </div>
          </div>
        </div>

        {/* Thumbnail Preview Badge */}
        <div className="p-3 rounded-xl bg-[#0e1017] border border-[#1f2437] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="px-3 py-1.5 rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-300 font-extrabold text-xs tracking-wider uppercase">
              {thumbnailText || 'THUMBNAIL TEXT'}
            </div>
            <span className="text-xs text-slate-400">
              Optimal frame at <strong className="text-slate-200">{thumbnailTimestamp.toFixed(2)}s</strong> (offset: +{(thumbnailTimestamp - activeHighlight.startTime).toFixed(1)}s)
            </span>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex items-center justify-end gap-3 pt-2">
        <button
          onClick={handleSaveAll}
          disabled={isSaving}
          className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 disabled:opacity-50 text-white text-xs font-bold shadow-lg shadow-emerald-600/30 transition-all active:scale-95"
        >
          <Check className="w-4 h-4" />
          <span>{isSaving ? 'Saving to Database...' : 'Save Metadata to Clip'}</span>
        </button>
      </div>
    </div>
  );
};
