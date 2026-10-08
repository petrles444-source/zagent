import type { Metadata } from "next";
import { Playfair_Display, Cormorant_Garamond, Marck_Script, Cormorant } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";
import { wedding } from "@/lib/wedding-config";
import { Providers } from "@/components/providers";

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700", "800", "900"],
  display: "swap",
});

const cormorant = Cormorant_Garamond({
  variable: "--font-cormorant",
  subsets: ["latin", "cyrillic"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const cormorantUpright = Cormorant({
  variable: "--font-cormorant-up",
  subsets: ["latin", "cyrillic"],
  weight: ["300", "400", "500", "600", "700"],
  style: ["normal", "italic"],
  display: "swap",
});

const marckScript = Marck_Script({
  variable: "--font-script",
  subsets: ["latin", "cyrillic"],
  weight: ["400"],
  display: "swap",
});

const SITE_URL = "https://sofia-alexander.ru";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "София & Александр — 22 октября 2026 · День свадьбы",
  description:
    "День свадьбы. 22 октября 2026 года, в полночь. Свечи, пионы и полуночный шёпот. Приглашаем вас разделить с нами этот вечер.",
  keywords: ["свадьба", "приглашение", "София", "Александр", "22 октября 2026", "RSVP"],
  authors: [{ name: "София & Александр" }],
  alternates: { canonical: SITE_URL },
  openGraph: {
    title: "София & Александр — 22 октября 2026",
    description: "День свадьбы. Полночь, свечи, пионы. Приглашаем вас разделить с нами этот вечер.",
    type: "website",
    url: SITE_URL,
    siteName: "София & Александр — свадьба",
    locale: "ru_RU",
    images: [
      {
        url: "/wedding/bride-portrait.png",
        width: 768,
        height: 1344,
        alt: "Портрет невесты в день свадьбы",
      },
      {
        url: "/wedding/original-cover.png",
        width: 1024,
        height: 1024,
        alt: "Приглашение на свадьбу — 22 октября 2026",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "София & Александр — 22 октября 2026",
    description: "День свадьбы. Полночь, свечи, пионы.",
    images: ["/wedding/bride-portrait.png"],
  },
  robots: { index: true, follow: true },
};

/**
 * JSON-LD Event structured data — lets search engines & calendar apps
 * understand the wedding as a real event (rich results, smart importing).
 */
const eventData = {
  "@context": "https://schema.org",
  "@type": "Event",
  name: `Свадьба Софии & Александра`,
  description: wedding.concept,
  startDate: wedding.dateISO,
  endDate: new Date(
    new Date(wedding.dateISO).getTime() + 7 * 60 * 60 * 1000
  ).toISOString(),
  eventStatus: "https://schema.org/EventScheduled",
  eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
  location: {
    "@type": "Place",
    name: wedding.venueName,
    address: {
      "@type": "PostalAddress",
      addressLocality: wedding.venueCity,
      streetAddress: wedding.venueAddress,
      addressCountry: "RU",
    },
  },
  organizer: {
    "@type": "Person",
    name: `${wedding.bride} & ${wedding.groom}`,
  },
  image: [`${SITE_URL}/wedding/bride-portrait.png`, `${SITE_URL}/wedding/original-cover.png`],
  url: SITE_URL,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(eventData) }}
        />
      </head>
      <body
        className={`${playfair.variable} ${cormorant.variable} ${cormorantUpright.variable} ${marckScript.variable} antialiased bg-night text-ivory`}
      >
        <Providers>
          {children}
        </Providers>
        <Toaster />
      </body>
    </html>
  );
}
