import { SiteNav } from "@/components/wedding/site-nav";
import { Hero } from "@/components/wedding/hero";
import { Countdown } from "@/components/wedding/countdown";
import { CoupleStory } from "@/components/wedding/couple-story";
import { LoveStory } from "@/components/wedding/love-story";
import { EventDetails } from "@/components/wedding/event-details";
import { DressPalette } from "@/components/wedding/dress-palette";
import { Schedule } from "@/components/wedding/schedule";
import { Gallery } from "@/components/wedding/gallery";
import { Rsvp } from "@/components/wedding/rsvp";
import { Guestbook } from "@/components/wedding/guestbook";
import { SongRequests } from "@/components/wedding/song-requests";
import { Faq } from "@/components/wedding/faq";
import { LoveLocks } from "@/components/wedding/love-locks";
import { PhotoWall } from "@/components/wedding/photo-wall";
import { GuestPoll } from "@/components/wedding/guest-poll";
import { AmbientAudio } from "@/components/wedding/ambient-audio";
import { Travel } from "@/components/wedding/travel";
import { WeddingParty } from "@/components/wedding/wedding-party";
import { TableFinder } from "@/components/wedding/table-finder";
import { Closing, SiteFooter } from "@/components/wedding/closing";
import { CursorSparkle } from "@/components/wedding/cursor-sparkle";
import { ScrollProgress } from "@/components/wedding/scroll-progress";
import { PetalFall } from "@/components/wedding/petal-fall";
import { Preloader } from "@/components/wedding/preloader";
import { CountdownConfetti } from "@/components/wedding/countdown-confetti";

export default function Home() {
  return (
    <div className="relative flex min-h-screen flex-col bg-night">
      <Preloader />
      <PetalFall />
      <ScrollProgress />
      <CursorSparkle />
      <CountdownConfetti />
      <AmbientAudio />
      <SiteNav />
      <main className="flex-1">
        <Hero />
        <Countdown />
        <LoveStory />
        <CoupleStory />
        <WeddingParty />
        <EventDetails />
        <DressPalette />
        <Travel />
        <Schedule />
        <TableFinder />
        <Gallery />
        <PhotoWall />
        <Rsvp />
        <section className="relative bg-night-soft py-16">
          <div className="absolute inset-0 bg-grain opacity-40" aria-hidden="true" />
          <div className="relative mx-auto max-w-2xl px-6">
            <GuestPoll />
          </div>
        </section>
        <Guestbook />
        <SongRequests />
        <LoveLocks />
        <Faq />
        <Closing />
      </main>
      <SiteFooter />
    </div>
  );
}
