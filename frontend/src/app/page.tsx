import { ArrowRight, GithubLogo } from "@phosphor-icons/react/dist/ssr"
import Image from "next/image"
import Link from "next/link"

import { BrandMark } from "@/components/ui/brand-mark"
import { Button } from "@/components/ui/button"
import { createClient } from "@/lib/supabase/server"

export default async function Home() {
  // Show the landing page to everyone, but if the visitor is already signed in
  // (session cookie), swap the sign-in CTAs for a dashboard link.
  const supabase = await createClient()
  const {
    data: { user },
  } = await supabase.auth.getUser()

  return (
    <main className="grid min-h-dvh bg-background lg:grid-cols-2">
      {/* Left — content */}
      <div className="flex flex-col gap-10 p-8 sm:p-12 lg:p-14">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <BrandMark
              className="size-9 shrink-0 rounded-lg"
              imgClassName="scale-150"
            />
            <span className="text-lg font-semibold tracking-tight">Oreag</span>
          </div>
          <nav className="flex items-center gap-4 text-sm font-medium text-muted-foreground sm:gap-5">
            <Link href="/docs" className="transition-colors hover:text-foreground">
              Docs
            </Link>
            <a
              href="https://github.com/your-org/oreag"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
            >
              <GithubLogo className="size-4" />
              <span className="hidden sm:inline">GitHub</span>
            </a>
            <Link
              href="/docs#reference"
              className="hidden transition-colors hover:text-foreground sm:inline"
            >
              API
            </Link>
          </nav>
        </header>

        <div className="flex flex-1 flex-col justify-center gap-6">
          <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">
            Turn your <span className="text-amber-500">documents</span> into a
            queryable <span className="text-sky-500">RAG API</span>
          </h1>
          <p className="max-w-md text-muted-foreground">
            Upload documents, tune chunking and embeddings, bring your own keys
            — and ship a grounded endpoint your apps and agents can call.
          </p>
          <div className="flex items-center gap-5">
            {user ? (
              // Already signed in — go straight to the dashboard, no sign in.
              <Button asChild size="lg" className="group rounded-full px-6">
                <Link href="/dashboard">
                  Go to dashboard
                  <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </Button>
            ) : (
              <>
                <Button asChild size="lg" className="rounded-full px-6">
                  <Link href="/signup">Get started</Link>
                </Button>
                <Link
                  href="/login"
                  className="group inline-flex items-center gap-1.5 text-sm font-medium text-foreground transition-colors hover:text-foreground/70"
                >
                  Sign in
                  <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </>
            )}
          </div>
        </div>

        <footer className="space-y-3">
          <div className="text-xs font-medium tracking-wide text-muted-foreground">
            OpenAI · Gemini · Anthropic · Sarvam · Ollama
          </div>
          <p className="max-w-sm text-[11px] leading-relaxed text-muted-foreground/70">
            Bring your own keys or run local models. Documents are embedded into
            pgvector and served as a grounded /v1 API for your apps and coding
            agents.
          </p>
        </footer>
      </div>

      {/* Right — retro painting, full bleed. Only the sky/clouds swirl: a static
          base keeps the man, desk and documents perfectly still, while a second
          copy is displaced (#starry-motion) and masked to just the sky on top. */}
      <div className="relative hidden overflow-hidden bg-muted lg:block">
        {/* Static base — man, desk and documents never move. */}
        <Image
          src="/hero.jpg"
          alt="Van Gogh Starry Night style painting of a man working through documents at a desk"
          fill
          priority
          draggable={false}
          sizes="(min-width: 1024px) 50vw, 100vw"
          className="pointer-events-none select-none object-cover"
        />
        {/* Swirling layer — same painting, displaced and masked to the sky only. */}
        <Image
          src="/hero.jpg"
          alt=""
          fill
          draggable={false}
          sizes="(min-width: 1024px) 50vw, 100vw"
          className="starry-sky pointer-events-none select-none object-cover"
        />
        {/* Animated displacement field driving the swirl. */}
        <svg aria-hidden="true" className="absolute size-0">
          <filter id="starry-motion" x="-20%" y="-20%" width="140%" height="140%">
            <feTurbulence
              type="turbulence"
              baseFrequency="0.011 0.015"
              numOctaves={2}
              seed={7}
              result="noise"
            >
              <animate
                attributeName="baseFrequency"
                dur="24s"
                values="0.011 0.015;0.014 0.019;0.009 0.013;0.011 0.015"
                repeatCount="indefinite"
              />
            </feTurbulence>
            <feDisplacementMap
              in="SourceGraphic"
              in2="noise"
              scale={12}
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </svg>
      </div>
    </main>
  )
}
