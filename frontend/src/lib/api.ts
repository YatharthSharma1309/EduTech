const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface JobStatus {
  job_id: string;
  status: "pending" | "running" | "done" | "failed";
  progress: number;           // 0.0 – 1.0
  current_step: string;
  total_questions: number;
  questions_done: number;
  output_path: string;
  error: string;
  created_at: string;
  finished_at: string;
  tokens: Record<string, number>;  // stage label → token count
  total_tokens: number;
  warnings: string[];
  vision_errors: number;
}

export async function uploadPdf(file: File): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/api/extract`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function pollJob(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${BASE}/api/jobs/${jobId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function downloadUrl(jobId: string): string {
  return `${BASE}/api/download/${jobId}`;
}
