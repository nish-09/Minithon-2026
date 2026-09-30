import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthProvider } from "@/lib/auth";
import { ToastProvider } from "@/lib/hooks";
import { RealtimeProvider } from "@/lib/realtime";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "NEXA — Your Neighborhood, When You Need It Most", template: "%s · NEXA" },
  description: "AI-powered neighborhood assistance: ask, understand, match, connect, care.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#4f46e5" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <ToastProvider>
          <AuthProvider>
            <RealtimeProvider>{children}</RealtimeProvider>
          </AuthProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
