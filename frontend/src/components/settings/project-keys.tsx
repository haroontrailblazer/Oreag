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
    <Card>
      <CardHeader>
        <CardTitle>Project key overrides</CardTitle>
        <CardDescription>
          Projects that use their own key for a model instead of the account
          keys above. Manage these in each project&apos;s Settings.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
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
      </CardContent>
    </Card>
  )
}
