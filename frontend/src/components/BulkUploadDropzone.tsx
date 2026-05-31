import { useCallback, useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { toast } from "sonner";
import { useBulkUpload } from "@/api/hooks";
import { cn } from "@/lib/cn";

export function BulkUploadDropzone() {
  const bulkUpload = useBulkUpload();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [rejected, setRejected] = useState<{ row: number; reason: string }[]>([]);

  const handleFile = useCallback(
    async (file: File) => {
      try {
        const result = await bulkUpload.mutateAsync(file);
        setRejected(result.rejected ?? []);
        toast.success(`Imported ${result.created?.length ?? 0} stories`);
      } catch (err) {
        toast.error(err instanceof Error ? err.message : "Upload failed");
      }
    },
    [bulkUpload],
  );

  return (
    <div className="panel">
      <div className="panel-header">Bulk upload</div>
      <div className="p-4">
        <div
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files[0];
            if (file) void handleFile(file);
          }}
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center border border-dashed border-border py-6 transition-colors",
            dragOver && "border-primary bg-surface-elevated",
          )}
        >
          <FileUp className="mb-2 h-6 w-6 text-muted" strokeWidth={1.75} />
          <p className="text-sm text-muted">Drop CSV / JSON / text or click to upload</p>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.json,.txt"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
        </div>
        {rejected.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-danger">
            {rejected.map((r) => (
              <li key={r.row}>Row {r.row}: {r.reason}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
