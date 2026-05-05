"use client";

import { useRef, useState } from "react";
import { downloadUrl, JobStatus, pollJob, uploadPdf } from "@/lib/api";

export default function UploadPanel() {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function reset() {
    setJob(null);
    setError(null);
    setUploading(false);
    if (pollRef.current) clearInterval(pollRef.current);
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    reset();
    setUploading(true);

    let jobId: string;
    try {
      const data = await uploadPdf(file);
      jobId = data.job_id;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setUploading(false);
      return;
    }

    setUploading(false);

    pollRef.current = setInterval(async () => {
      try {
        const status = await pollJob(jobId);
        setJob(status);
        if (status.status === "done" || status.status === "failed") {
          clearInterval(pollRef.current!);
          if (status.status === "failed") setError(status.error || "Extraction failed");
        }
      } catch { /* transient network error — keep polling */ }
    }, 3000);
  }

  const pct = job ? Math.round(job.progress * 100) : 0;
  const isProcessing = uploading || job?.status === "pending" || job?.status === "running";

  return (
    <div className="bg-white rounded-2xl shadow-md p-6 w-full max-w-2xl">
      <h2 className="text-lg font-semibold text-gray-800 mb-1">Extract Questions from PDF</h2>
      <p className="text-xs text-gray-400 mb-4">
        Upload an exam PDF — the pipeline will split Q/A, OCR question images, match figures,
        and export everything to an Excel file.
      </p>

      {/* File picker */}
      <input
        type="file"
        accept=".pdf"
        onChange={handleFile}
        disabled={isProcessing}
        className="block w-full text-sm text-gray-600
          file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0
          file:bg-blue-600 file:text-white file:cursor-pointer
          hover:file:bg-blue-700 disabled:opacity-50"
      />

      {uploading && (
        <p className="mt-3 text-sm text-gray-400 animate-pulse">Uploading…</p>
      )}

      {/* Progress bar */}
      {job && job.status !== "done" && job.status !== "failed" && (
        <div className="mt-4">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>{job.current_step}</span>
            <span>{pct}%</span>
          </div>
          <div className="w-full bg-gray-100 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${pct}%` }}
            />
          </div>
          {job.total_questions > 0 && (
            <p className="text-xs text-gray-400 mt-1">
              {job.questions_done} / {job.total_questions} questions processed
            </p>
          )}
        </div>
      )}

      {/* Done — download button */}
      {job?.status === "done" && (
        <div className="mt-4 p-4 bg-green-50 rounded-xl flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold text-green-800">Extraction complete</p>
            <p className="text-xs text-green-600 mt-0.5">
              {job.total_questions} questions · Excel ready
            </p>
          </div>
          <a
            href={downloadUrl(job.job_id)}
            download
            className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
          >
            Download Excel
          </a>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mt-3 p-3 bg-red-50 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {/* New upload button after done/failed */}
      {(job?.status === "done" || job?.status === "failed") && (
        <button
          onClick={reset}
          className="mt-3 text-xs text-blue-500 hover:underline"
        >
          Upload another PDF
        </button>
      )}
    </div>
  );
}
