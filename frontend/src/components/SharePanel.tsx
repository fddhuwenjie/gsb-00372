import { useState, useEffect } from 'react';
import { X, Copy, Check, Link2, Clock, Share2 } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { useQueryStore } from '@/store/queryStore';

interface SharePanelProps {
  onClose: () => void;
}

export default function SharePanel({ onClose }: SharePanelProps) {
  const [copied, setCopied] = useState(false);
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [expiresIn, setExpiresIn] = useState(168);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentSavedId = useQueryStore((state) => state.currentSavedId);
  const shareCurrentQuery = useQueryStore((state) => state.shareCurrentQuery);
  const saveQuery = useQueryStore((state) => state.saveQuery);
  const savedQueries = useQueryStore((state) => state.savedQueries);

  const currentSaved = savedQueries.find((q) => q.id === currentSavedId);

  const generateShareLink = async () => {
    setSharing(true);
    setError(null);
    try {
      let savedId = currentSavedId;
      if (!savedId) {
        const saved = await saveQuery('Shared Query', '');
        savedId = saved.id;
      }
      const result = await shareCurrentQuery(expiresIn);
      if (result) {
        const fullUrl = `${window.location.origin}/share/${result.token}`;
        setShareUrl(fullUrl);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate share link');
    } finally {
      setSharing(false);
    }
  };

  const handleCopy = async () => {
    if (shareUrl) {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const formatExpiry = (hours: number) => {
    if (hours < 24) return `${hours} hours`;
    const days = Math.floor(hours / 24);
    return `${days} day${days > 1 ? 's' : ''}`;
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-dark-800 rounded-lg border border-dark-600 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-dark-700">
          <h2 className="text-lg font-semibold text-dark-100 flex items-center gap-2">
            <Share2 className="w-5 h-5 text-primary-400" />
            Share Query
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-dark-400 hover:text-dark-200 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-900/30 border border-red-800 rounded text-sm text-red-300">
              {error}
            </div>
          )}

          {currentSaved && (
            <div className="p-3 bg-dark-700 rounded">
              <div className="text-sm font-medium text-dark-200">
                {currentSaved.name}
              </div>
              {currentSaved.share_token && (
                <div className="text-xs text-primary-400 mt-1">
                  Already shared ({currentSaved.share_access_count} views)
                </div>
              )}
            </div>
          )}

          {!shareUrl ? (
            <>
              <div>
                <label className="block text-sm font-medium text-dark-200 mb-2 flex items-center gap-2">
                  <Clock className="w-4 h-4" />
                  Expires after
                </label>
                <select
                  value={expiresIn}
                  onChange={(e) => setExpiresIn(Number(e.target.value))}
                  className="w-full px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 focus:outline-none focus:border-primary-500"
                >
                  <option value={1}>1 hour</option>
                  <option value={24}>24 hours</option>
                  <option value={72}>3 days</option>
                  <option value={168}>7 days</option>
                  <option value={720}>30 days</option>
                  <option value={0}>Never</option>
                </select>
              </div>

              <button
                onClick={generateShareLink}
                disabled={sharing}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-500 text-white rounded transition-colors disabled:opacity-50"
              >
                {sharing ? (
                  <>Generating...</>
                ) : (
                  <>
                    <Link2 className="w-4 h-4" />
                    Generate Share Link
                  </>
                )}
              </button>
            </>
          ) : (
            <>
              <div className="flex justify-center p-4 bg-white rounded-lg">
                <QRCodeSVG value={shareUrl} size={200} level="H" />
              </div>

              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={shareUrl}
                  readOnly
                  className="flex-1 px-3 py-2 bg-dark-900 border border-dark-600 rounded text-dark-100 text-sm font-mono truncate"
                />
                <button
                  onClick={handleCopy}
                  className="px-3 py-2 bg-dark-700 hover:bg-dark-600 text-dark-200 rounded transition-colors"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Copy className="w-4 h-4" />
                  )}
                </button>
              </div>

              {expiresIn > 0 && (
                <p className="text-xs text-dark-400 text-center">
                  Link expires after {formatExpiry(expiresIn)}
                </p>
              )}

              <button
                onClick={generateShareLink}
                disabled={sharing}
                className="w-full px-4 py-2 text-sm text-dark-300 hover:text-dark-100 transition-colors"
              >
                Regenerate link
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
