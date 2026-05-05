import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EduTech PDF Extractor",
  description: "Extract exam questions, choices, and figures from PDFs into Excel",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
