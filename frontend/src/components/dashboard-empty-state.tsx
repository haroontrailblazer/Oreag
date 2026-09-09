import Link from "next/link"
import { ArrowRightIcon, ChatCircleTextIcon, FileTextIcon, FolderSimplePlusIcon, StackIcon } from "@phosphor-icons/react/dist/ssr"
import { Button } from "@/components/ui/button"

const steps = [
  { icon: FolderSimplePlusIcon, title: "Create a project", description: "Give your knowledge a home with a name and a model." },
  { icon: FileTextIcon, title: "Add your documents", description: "Upload the files you want your project to learn from." },
  { icon: ChatCircleTextIcon, title: "Start asking questions", description: "Try the playground, then connect your app through the API." },
]

export function DashboardEmptyState() {
  return (
    <section aria-labelledby="empty-projects-heading" className="my-auto shrink-0 overflow-hidden rounded-2xl border bg-card shadow-sm">
      <div className="grid items-center gap-8 px-6 py-10 sm:px-10 sm:py-12 lg:grid-cols-[1.25fr_1fr] lg:gap-12">
        <div className="max-w-lg">
          <span className="mb-5 inline-flex items-center gap-2 rounded-full border bg-muted/40 px-3 py-1 text-xs font-medium text-muted-foreground"><StackIcon className="size-3.5" aria-hidden="true" /> Your knowledge workspace</span>
          <h2 id="empty-projects-heading" className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">Your documents.<br /><span className="text-muted-foreground">A new way to find answers.</span></h2>
          <p className="mt-4 max-w-md text-sm leading-7 text-muted-foreground">Bring your knowledge together in your first project. Turn handbooks, research, and notes into answers you can use in your apps and agents.</p>
          <Button asChild className="mt-6 h-10 w-full sm:w-auto"><Link href="/projects/new">Create your first project<ArrowRightIcon className="size-4" /></Link></Button>
          <p className="mt-3 text-xs text-muted-foreground">Start with a name. You can add documents later.</p>
        </div>
        <div aria-hidden="true" className="relative mx-auto hidden w-full max-w-72 py-5 lg:block">
          <div className="absolute inset-4 rounded-full bg-primary/5 blur-2xl" />
          <div className="relative ml-3 mr-8 -rotate-3 rounded-xl border bg-background p-5 shadow-sm">
            <div className="mb-5 flex items-center gap-2.5"><div className="rounded-lg bg-muted p-2"><FileTextIcon className="size-5 text-muted-foreground" /></div><span className="text-xs font-medium">Your knowledge</span></div>
            <div className="space-y-2.5"><div className="h-1.5 w-full rounded bg-muted" /><div className="h-1.5 w-5/6 rounded bg-muted" /><div className="h-1.5 w-2/3 rounded bg-muted" /></div>
          </div>
          <div className="relative ml-10 -mt-1 rotate-3 rounded-xl border bg-card p-4 shadow-md"><div className="flex items-center gap-2 text-xs font-medium"><ChatCircleTextIcon className="size-5 text-primary" /> Answers, connected to your sources</div><div className="mt-3 flex gap-1.5">{["Documents", "Playground", "API"].map(label => <span key={label} className="rounded-md bg-muted px-2 py-1 text-[10px] text-muted-foreground">{label}</span>)}</div></div>
        </div>
      </div>
      <ol className="grid border-t bg-muted/20 sm:grid-cols-3">
        {steps.map(({ icon: Icon, title, description }, index) => <li key={title} className="border-b p-6 last:border-b-0 sm:border-r sm:border-b-0 sm:last:border-r-0 sm:p-7"><div className="mb-4 flex items-center justify-between"><Icon className="size-5 text-muted-foreground" aria-hidden="true" /><span className="font-mono text-xs text-muted-foreground/60">0{index + 1}</span></div><h3 className="text-sm font-semibold">{title}</h3><p className="mt-2 text-xs leading-6 text-muted-foreground">{description}</p></li>)}
      </ol>
    </section>
  )
}
