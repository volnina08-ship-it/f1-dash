import type { Metadata, Viewport } from "next";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  title: "APEXODDS — Live F1 Probability Engine",
  description:
    "Monte Carlo race simulator: live win, podium and top-10 probabilities for every driver, recomputed every lap. Replay demo. Unofficial — not associated with Formula 1.",
};

export const viewport: Viewport = {
  themeColor: "#08070c",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
