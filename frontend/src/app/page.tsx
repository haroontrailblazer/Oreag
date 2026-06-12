import Link from "next/link"

import { Button } from "@/components/ui/button"

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 text-center">
      <h1 className="text-5xl font-bold tracking-tight">Oreag</h1>
      <p className="max-w-md text-lg text-muted-foreground">
        Turn your PDFs into a queryable RAG API. Upload documents, tune
        chunking and embeddings, and get an endpoint your apps can call.
      </p>
      <div className="flex gap-3">
        <Button asChild size="lg">
          <Link href="/signup">Get started</Link>
        </Button>
        <Button asChild size="lg" variant="outline">
          <Link href="/login">Sign in</Link>
        </Button>
      </div>
    </div>
  )
}
