import type { Metadata } from "next";
import { Space_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { Sidebar } from "@/components/Sidebar";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-space-grotesk",
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-jetbrains-mono",
});

export const metadata: Metadata = {
  title: "Interview Practice Platform",
  description: "Your interview practice dashboard.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${spaceGrotesk.className} ${jetBrainsMono.variable} antialiased`} data-theme="dark" suppressHydrationWarning>
        <AuthProvider>
          <div className="bg-shape bg-shape-a"></div>
          <div className="bg-shape bg-shape-b"></div>
          
          <div className="app-layout">
            <Sidebar />
            {children}
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
