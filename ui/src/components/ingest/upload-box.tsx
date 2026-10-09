import { useRef, useState, useCallback } from "react";
import {
  Upload,
  FileCheck2,
  AlertCircle,
  Loader2,
  FilePlus2,
  ShieldCheck,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn, formatBytes } from "@/lib/utils";

const MAX_SIZE_BYTES = 15 * 1024 * 1024; // 15 MB
const PDF_MAGIC = "%PDF-";

interface UploadBoxProps {
  onUpload: (file: File) => void;
  isProcessing: boolean;
  activeFilename?: string;
  onReset?: () => void;
  statusMessage?: string;
}

export function UploadBox({
  onUpload,
  isProcessing,
  activeFilename,
  onReset,
  statusMessage,
}: UploadBoxProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<{
    name: string;
    size: number;
  } | null>(null);

  // Pre-upload client-side validation
  const validateAndProcessFile = useCallback(
    async (file: File | undefined) => {
      setValidationError(null);
      if (!file) return;

      // 1. Extension check
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setValidationError("Only PDF documents are accepted. Please provide a genuine .pdf file.");
        return;
      }

      // 2. Empty file check
      if (file.size === 0) {
        setValidationError("The selected file is empty (0 bytes). Please upload a valid document.");
        return;
      }

      // 3. Max size check
      if (file.size > MAX_SIZE_BYTES) {
        setValidationError(
          `File size (${formatBytes(file.size)}) exceeds the maximum limit of 15 MB.`
        );
        return;
      }

      // 4. PDF Magic Header check (%PDF-)
      try {
        const headerSlice = file.slice(0, 5);
        const buffer = await headerSlice.arrayBuffer();
        const decoder = new TextDecoder("ascii");
        const headerText = decoder.decode(buffer);
        if (!headerText.startsWith(PDF_MAGIC)) {
          setValidationError(
            "Corrupt or invalid PDF: Document lacks the valid '%PDF-' header signature."
          );
          return;
        }
      } catch (err) {
        setValidationError("Could not verify file integrity header.");
        return;
      }

      // Pre-validation passed
      setSelectedFile({ name: file.name, size: file.size });
      onUpload(file);
    },
    [onUpload]
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!isProcessing) setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (isProcessing) return;
    const file = e.dataTransfer.files?.[0];
    validateAndProcessFile(file);
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    validateAndProcessFile(file);
    e.target.value = "";
  };

  const handleTriggerPicker = () => {
    if (!isProcessing) {
      fileInputRef.current?.click();
    }
  };

  const handleUploadAnother = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedFile(null);
    setValidationError(null);
    if (onReset) onReset();
    fileInputRef.current?.click();
  };

  const displayName = activeFilename || selectedFile?.name;

  return (
    <div className="w-full space-y-3">
      <div
        onClick={handleTriggerPicker}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleTriggerPicker();
          }
        }}
        className={cn(
          "relative flex min-h-[220px] w-full cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed p-8 text-center transition-all duration-200 outline-none",
          isDragOver
            ? "border-primary bg-primary/8 shadow-md scale-[1.008]"
            : validationError
              ? "border-destructive/60 bg-destructive/5"
              : isProcessing
                ? "border-primary/50 bg-surface/80 cursor-wait"
                : displayName
                  ? "border-emerald-500/40 bg-card hover:border-emerald-500/60"
                  : "border-border-strong bg-card hover:border-primary/60 hover:bg-surface/60 hover:shadow-xs"
        )}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={handleFileInputChange}
          disabled={isProcessing}
        />

        {/* State Icon */}
        <div
          className={cn(
            "flex size-14 items-center justify-center rounded-2xl border transition-colors shadow-xs",
            isProcessing
              ? "border-primary/40 bg-primary/10 text-primary"
              : validationError
                ? "border-destructive/40 bg-destructive/10 text-destructive"
                : displayName
                  ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "border-border bg-surface text-muted-foreground"
          )}
        >
          {isProcessing ? (
            <Loader2 className="size-6 animate-spin" />
          ) : validationError ? (
            <AlertCircle className="size-6" />
          ) : displayName ? (
            <FileCheck2 className="size-6" />
          ) : (
            <Upload className="size-6" />
          )}
        </div>

        {/* Central Messaging */}
        <div className="mt-4 max-w-lg space-y-1">
          {displayName ? (
            <>
              <p className="font-display font-bold text-base tracking-tight text-foreground">
                {displayName}
              </p>
              {selectedFile?.size && (
                <p className="font-mono text-xs text-muted-foreground">
                  {formatBytes(selectedFile.size)} · PDF Document Verified
                </p>
              )}
            </>
          ) : (
            <>
              <p className="font-display font-bold text-base tracking-tight text-foreground">
                {isDragOver ? "Drop your invoice PDF to process" : "Upload Invoice Document"}
              </p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Drag and drop your PDF here, or click to browse your local filesystem
              </p>
            </>
          )}
        </div>

        {/* Pre-flight constraints & buttons */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {!isProcessing && !displayName && (
            <Button
              type="button"
              variant="default"
              size="sm"
              className="pointer-events-none gap-1.5 shadow-xs"
            >
              <FilePlus2 className="size-4" />
              Select PDF Document
            </Button>
          )}

          {displayName && !isProcessing && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleUploadAnother}
              className="gap-1.5 shadow-xs"
            >
              <RotateCcw className="size-3.5" />
              Upload Another Document
            </Button>
          )}

          {isProcessing && (
            <div className="inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1 font-mono text-xs font-semibold text-primary">
              <Loader2 className="size-3 animate-spin" />
              <span>{statusMessage || "Processing invoice through 5-stage pipeline…"}</span>
            </div>
          )}
        </div>

        {/* Upload Policy Notice */}
        <div className="mt-4 flex items-center gap-2 text-[11px] text-faint">
          <ShieldCheck className="size-3.5" />
          <span>Accepts genuine PDF documents only (max 15 MB). Integrity header verified before ingestion.</span>
        </div>
      </div>

      {/* Meaningful Validation Error display */}
      {validationError && (
        <div className="flex items-start gap-2.5 rounded-xl border border-destructive/40 bg-destructive/10 p-3.5 text-xs text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <span className="font-semibold">Upload Validation Failed: </span>
            <span>{validationError}</span>
          </div>
          <button
            type="button"
            onClick={() => setValidationError(null)}
            className="cursor-pointer text-xs font-semibold hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
