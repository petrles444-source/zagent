import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";
import { ThemeProvider } from "@/components/theme-provider";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CSSFX — CSS Effect Library with Live Demos & Code",
  description:
    "A curated library of beautiful CSS effects: buttons, loaders, cards, text, backgrounds, and toggles. Every effect ships with a live demo and copy-ready code.",
  keywords: [
    "CSS effects",
    "CSS library",
    "buttons",
    "loaders",
    "animations",
    "glassmorphism",
    "neon",
    "gradient",
    "live demo",
  ],
  authors: [{ name: "CSSFX" }],
  icons: {
    icon: "https://z-cdn.chatglm.cn/z-ai/static/logo.svg",
  },
  openGraph: {
    title: "CSSFX — CSS Effect Library",
    description: "Beautiful CSS effects with live demos and copy-ready code.",
    siteName: "CSSFX",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "CSSFX — CSS Effect Library",
    description: "Beautiful CSS effects with live demos and copy-ready code.",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          {children}
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
