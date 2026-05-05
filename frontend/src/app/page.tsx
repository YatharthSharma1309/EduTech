"use client";

import UploadPanel from "@/components/UploadPanel";

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center py-16 px-4">
      <div className="max-w-2xl w-full mb-10">
        <h1 className="text-3xl font-bold text-gray-900">EduTech PDF Extractor</h1>
        <p className="text-gray-500 mt-1">
          Upload an exam PDF to extract questions, choices, figures, and answers into Excel.
        </p>
      </div>

      <UploadPanel />

      {/* Pipeline overview */}
      <div className="max-w-2xl w-full mt-10 grid grid-cols-2 gap-4 text-sm text-gray-600">
        {[
          { step: "1", label: "Split Q / A", desc: "LLM reads the PDF and separates questions from answers" },
          { step: "2", label: "Crop Images", desc: "Each question is rendered as a PNG for vision OCR" },
          { step: "3", label: "Match Figures", desc: "Diagrams are extracted and linked to their question" },
          { step: "4", label: "OCR + Export", desc: "Vision model reads crops, LaTeX → Unicode, saved to Excel" },
        ].map(({ step, label, desc }) => (
          <div key={step} className="bg-white rounded-xl p-4 shadow-sm">
            <span className="text-xs font-bold text-blue-500 uppercase tracking-wide">Step {step}</span>
            <p className="font-semibold text-gray-800 mt-0.5">{label}</p>
            <p className="text-xs text-gray-400 mt-1">{desc}</p>
          </div>
        ))}
      </div>
    </main>
  );
}
