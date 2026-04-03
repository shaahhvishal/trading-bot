import Navbar from "@/components/Navbar";
import Hero from "@/components/Hero";
import Features from "@/components/Features";
import Strategies from "@/components/Strategies";
import Performance from "@/components/Performance";
import Pricing from "@/components/Pricing";
import Footer from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Navbar />
      <main>
        <Hero />
        <Features />
        <Strategies />
        <Performance />
        <Pricing />
      </main>
      <Footer />
    </>
  );
}
