/**
 * ImageLightbox -- full-screen overlay for viewing images.
 *
 * Click an image to open the lightbox; click backdrop or press Escape to close.
 * Provides zoom-to-fit and a download link.
 */

import { useEffect, useCallback } from "react";
import { X, Download } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ImageLightboxProps {
  src: string;
  alt?: string;
  open: boolean;
  onClose: () => void;
}

export default function ImageLightbox({ src, alt, open, onClose }: ImageLightboxProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", handleKeyDown);
    // Prevent body scroll while lightbox is open
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Controls */}
      <div className="absolute top-4 right-4 flex items-center gap-2 z-10">
        <a
          href={src}
          download
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9 text-white/80 hover:text-white hover:bg-white/10 rounded-xl"
          >
            <Download className="h-5 w-5" />
          </Button>
        </a>
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 text-white/80 hover:text-white hover:bg-white/10 rounded-xl"
          onClick={onClose}
        >
          <X className="h-5 w-5" />
        </Button>
      </div>

      {/* Image */}
      <img
        src={src}
        alt={alt ?? "Full size image"}
        className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}
