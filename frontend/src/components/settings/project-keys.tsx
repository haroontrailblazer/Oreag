"use client"

import Link, { useLinkStatus } from "next/link"
import useSWR from "swr"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { fetcher } from "@/lib/api"
import type { Project } from "@/lib/types"

/** "Manage" label that swaps to a spinner (overlaid, no width change) while the
 *  link's navigation is pending. Must live inside the <Link>. */
function ManageButtonLabel() {
  const { pending } = useLinkStatus()
  return (
    <span className="relative inline-flex items-center justify-center">
      <span className={pending ? "opacity-0" : undefined}>Manage</span>
      {pending && (
        <Spinner size={14} className="absolute text-muted-foreground" />
      )}
    </span>
  )
}

export function ProjectKeys() {
  const { data: projects } = useSWR<Project[]>("/api/projects", fetcher)
  const loading = projects === undefined
  const overrides = (projects ?? []).filter(
    (p) => p.embedding_key_last4 || p.llm_key_last4
  )

  return (
    // Sits below the (stretchy) provider card; its own rows scroll past a cap
    // so it can never push the page beyond the viewport.
    <Card className="shrink-0 gap-3 py-4 sm:gap-6 sm:py-6">
      <CardHeader className="gap-1.5 px-4 sm:gap-2 sm:px-6">
        <CardTitle>Project key overrides</CardTitle>
        <CardDescription className="text-xs leading-relaxed sm:text-sm">
          Projects that use their own key for a model instead of the account
          keys above. Manage these in each project&apos;s Settings.
        </CardDescription>
      </CardHeader>
      <CardContent className="max-h-[32dvh] overflow-y-auto p-0 sm:max-h-[28dvh]">
        <div className="sm:hidden">
          {loading ? (
            [0, 1].map((i) => (
              <div key={i} className="space-y-2 border-b px-4 py-3 last:border-b-0">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-8 w-full" />
              </div>
            ))
          ) : overrides.length === 0 ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">
              No project-level keys - every project uses your account keys above.
            </p>
          ) : (
            overrides.map((project) => (
              <div
                key={project.id}
                className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b px-4 py-3 last:border-b-0"
              >
                <div className="min-w-0 space-y-2">
                  <div>
                    <div className="truncate text-sm font-medium">{project.name}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {project.embedding_provider} · {project.llm_provider}
                    </div>
                  </div>
                  <dl className="grid gap-1 text-xs">
                    <div className="flex min-w-0 items-center gap-2">
                      <dt className="shrink-0 text-muted-foreground">Embedding</dt>
                      <dd className="truncate font-mono">
                        {project.embedding_key_last4
                          ? `••••${project.embedding_key_last4}`
                          : "account key"}
                      </dd>
                    </div>
                    <div className="flex min-w-0 items-center gap-2">
                      <dt className="shrink-0 text-muted-foreground">Answer</dt>
                      <dd className="truncate font-mono">
                        {project.llm_key_last4
                          ? `••••${project.llm_key_last4}`
                          : "account key"}
                      </dd>
                    </div>
                  </dl>
                </div>
                <Button asChild variant="outline" size="sm" className="self-start">
                  <Link
                    href={`/projects/${project.id}?tab=settings`}
                    prefetch={false}
                  >
                    <ManageButtonLabel />
                  </Link>
                </Button>
              </div>
            ))
          )}
        </div>

        <div className="hidden sm:block">
          <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow>
              <TableHead className="pl-6">Project</TableHead>
              <TableHead>Embedding key</TableHead>
              <TableHead>Answer (LLM) key</TableHead>
              <TableHead className="w-28 pr-6" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              [0, 1].map((i) => (
                <TableRow key={i}>
                  <TableCell className="pl-6">
                    <Skeleton className="h-4 w-32" />
                  </TableCell>
                  <TableCell>
                    <Skeleton className="h-4 w-24" />
                  </TableCell>
                  <TableCell>
                    <Skeleton className="h-4 w-24" />
                  </TableCell>
                  <TableCell className="pr-6" />
                </TableRow>
              ))
            ) : overrides.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="pl-6 pr-6 text-sm text-muted-foreground"
                >
                  No project-level keys - every project uses your account keys
                  above.
                </TableCell>
              </TableRow>
            ) : (
              overrides.map((project) => (
                <TableRow key={project.id}>
                  <TableCell className="pl-6">
                    <div className="font-medium">{project.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {project.embedding_provider} · {project.llm_provider}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {project.embedding_key_last4 ? (
                      <span>••••••••{project.embedding_key_last4}</span>
                    ) : (
                      <span className="text-muted-foreground">account key</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {project.llm_key_last4 ? (
                      <span>••••••••{project.llm_key_last4}</span>
                    ) : (
                      <span className="text-muted-foreground">account key</span>
                    )}
                  </TableCell>
                  <TableCell className="pr-6 text-right">
                    <Button asChild variant="outline" size="sm">
                      <Link
                        href={`/projects/${project.id}?tab=settings`}
                        prefetch={false}
                      >
                        <ManageButtonLabel />
                      </Link>
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
