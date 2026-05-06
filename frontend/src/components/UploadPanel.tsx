"use client";

import { useRef, useState } from "react";
import { downloadUrl, JobStatus, pollJob, uploadPdf } from "@/lib/api";

const STAGES: { label: string; keyword: string; tokenKey?: string }[] = [
  { label: "Split Q / A",      keyword: "Stage 1", tokenKey: "Split Q/A"   },
  { label: "Render pages",     keyword: "Stage 2"                           },
  { label: "Match figures",    keyword: "Stage 3"                           },
  { label: "Vision OCR",       keyword: "Stage 4", tokenKey: "Vision OCR"  },
  { label: "LaTeX → Unicode",  keyword: "Stage 5"                          },
  { label: "Verify",           keyword: "Stage 6", tokenKey: "Verify"      },
  { label: "Write Excel",      keyword: "Stage 7"                          },
];

function currentStageIndex(step: string): number {
  const match = step.match(/Stage (\d)/);
  return match ? parseInt(match[1]) - 1 : -1;
}

export default function UploadPanel() {
  const [job, setJob]           = useState<JobStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [fileName, setFileName] = useState("");
  const [error, setError]       = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function reset() {
    setJob(null);
    setError(null);
    setUploading(false);
    setFileName("");
    if (pollRef.current) clearInterval(pollRef.current);
  }

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    reset();
    setFileName(file.name);
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
      } catch { /* transient — keep polling */ }
    }, 2000);
  }

  const pct        = job ? Math.round(job.progress * 100) : 0;
  const stageIdx   = job ? currentStageIndex(job.current_step) : -1;
  const isRunning  = uploading || job?.status === "pending" || job?.status === "running";
  const isDone     = job?.status === "done";
  const isFailed   = job?.status === "failed";

  return (
    <div className="bg-white rounded-2xl shadow-md p-6 w-full max-w-2xl">
      <h2 className="text-lg font-semibold text-gray-800 mb-1">Extract Questions from PDF</h2>
      <p className="text-xs text-gray-400 mb-4">
        Upload an exam PDF — the pipeline splits Q/A, OCRs question images,
        matches figures, and exports to Excel.
      </p>

      {/* File picker */}
      <input
        type="file"
        accept=".pdf"
        onChange={handleFile}
        disabled={isRunning}
        className="block w-full text-sm text-gray-600
          file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0
          file:bg-blue-600 file:text-white file:cursor-pointer
          hover:file:bg-blue-700 disabled:opacity-50"
      />

      {/* Uploading spinner */}
      {uploading && (
        <div className="mt-4 flex items-center gap-2 text-sm text-gray-500">
          <span className="inline-block w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
          Uploading {fileName}…
        </div>
      )}

      {/* Active pipeline view */}
      {job && !isDone && !isFailed && (
        <div className="mt-5 space-y-4">
          {/* Progress bar */}
          <div>
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span className="font-medium text-blue-600">{job.current_step}</span>
              <span>{pct}%</span>
            </div>
            <div className="w-full bg-gray-100 rounded-full h-2">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all duration-700"
                style={{ width: `${pct}%` }}
              />
            </div>
            {job.total_questions > 0 && (
              <p className="text-xs text-gray-400 mt-1">
                {job.questions_done} / {job.total_questions} questions OCR'd
                {job.vision_errors > 0 && (
                  <span className="text-amber-500 ml-2">· {job.vision_errors} failed</span>
                )}
              </p>
            )}
          </div>

          {/* Live warnings */}
          {job.warnings?.length > 0 && (
            <div className="space-y-1">
              {job.warnings.map((w, i) => (
                <div key={i} className="flex gap-2 p-2.5 bg-amber-50 border border-amber-200 rounded-lg">
                  <span className="text-amber-500 text-sm flex-shrink-0">⚠</span>
                  <p className="text-xs text-amber-700 leading-snug">{w}</p>
                </div>
              ))}
            </div>
          )}

          {/* Stage tracker */}
          <div className="border border-gray-100 rounded-xl p-3 space-y-1">
            {STAGES.map((stage, i) => {
              const done    = stageIdx > i || isDone;
              const active  = stageIdx === i;
              const pending = stageIdx < i;
              const stageTokens = stage.tokenKey ? (job.tokens?.[stage.tokenKey] ?? 0) : 0;
              const hasOcrErrors = stage.keyword === "Stage 4" && job.vision_errors > 0 && done;

              return (
                <div key={stage.label} className={`flex items-center gap-3 px-2 py-1.5 rounded-lg text-sm transition-colors ${active ? "bg-blue-50" : ""}`}>
                  {/* Icon */}
                  <span className={`w-5 h-5 flex-shrink-0 flex items-center justify-center rounded-full text-xs font-bold ${hasOcrErrors ? "bg-amber-400 text-white" : done ? "bg-green-500 text-white" : active ? "bg-blue-500 text-white" : "bg-gray-100 text-gray-400"}`}>
                    {done ? (
                      <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none">
                        <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    ) : active ? (
                      <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
                    ) : (
                      <span className="text-gray-300">{i + 1}</span>
                    )}
                  </span>

                  {/* Label */}
                  <span className={`flex-1 ${done ? (hasOcrErrors ? "text-amber-700 line-through decoration-amber-300" : "text-green-700 line-through decoration-green-300") : active ? "text-blue-700 font-medium" : "text-gray-400"}`}>
                    {stage.label}
                  </span>

                  {/* Token count */}
                  {(done || active) && stageTokens > 0 && (
                    <span className="text-xs text-purple-500 font-mono">{stageTokens.toLocaleString()} tok</span>
                  )}

                  {/* Status badge */}
                  {done && !hasOcrErrors && <span className="text-xs text-green-500">done</span>}
                  {done && hasOcrErrors && <span className="text-xs text-amber-500">{job.vision_errors} failed</span>}
                  {active && (
                    <span className="text-xs text-blue-500 flex items-center gap-1">
                      <span className="inline-block w-2.5 h-2.5 border border-blue-400 border-t-transparent rounded-full animate-spin" />
                      running
                    </span>
                  )}
                  {pending && <span className="text-xs text-gray-300">waiting</span>}
                </div>
              );
            })}

            {/* Total tokens row */}
            {job.total_tokens > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-100 flex justify-between items-center px-2">
                <span className="text-xs text-gray-400">Total tokens used</span>
                <span className="text-xs font-semibold text-purple-600 font-mono">{job.total_tokens.toLocaleString()}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Done */}
      {isDone && (
        <div className="mt-5 space-y-3">
          {/* All stages ticked */}
          <div className="border border-green-100 rounded-xl p-3 space-y-1">
            {STAGES.map((stage) => (
              <div key={stage.label} className="flex items-center gap-3 px-2 py-1.5 text-sm">
                <span className="w-5 h-5 flex-shrink-0 flex items-center justify-center rounded-full bg-green-500 text-white">
                  <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </span>
                <span className="flex-1 text-green-700 line-through decoration-green-300">{stage.label}</span>
                <span className="text-xs text-green-500">done</span>
              </div>
            ))}
          </div>

          {/* Warnings summary on done screen */}
          {job!.warnings?.length > 0 && (
            <div className="space-y-1">
              {job!.warnings.map((w, i) => (
                <div key={i} className="flex gap-2 p-2.5 bg-amber-50 border border-amber-200 rounded-lg">
                  <span className="text-amber-500 text-sm flex-shrink-0">⚠</span>
                  <p className="text-xs text-amber-700 leading-snug">{w}</p>
                </div>
              ))}
            </div>
          )}

          {/* Download */}
          <div className="p-4 bg-green-50 rounded-xl flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-green-800">Extraction complete</p>
              <p className="text-xs text-green-600 mt-0.5">
                {job!.total_questions} questions · Excel ready
                {job!.vision_errors > 0 && (
                  <span className="text-amber-600 ml-1">· {job!.vision_errors} OCR failed (LLM fallback used)</span>
                )}
              </p>
              {job!.total_tokens > 0 && (
                <p className="text-xs text-purple-500 mt-0.5 font-mono">
                  {job!.total_tokens.toLocaleString()} tokens used
                </p>
              )}
            </div>
            <a
              href={downloadUrl(job!.job_id)}
              download
              className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
            >
              Download Excel
            </a>
          </div>
        </div>
      )}

      {/* Error */}
      {isFailed && error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-xl">
          <p className="text-sm font-semibold text-red-700 mb-1">Pipeline failed</p>
          <p className="text-xs text-red-500 font-mono break-all">{error}</p>
        </div>
      )}

      {/* Try again */}
      {(isDone || isFailed) && (
        <button onClick={reset} className="mt-3 text-xs text-blue-500 hover:underline">
          Upload another PDF
        </button>
      )}
    </div>
  );
}
