"use client"

import Link from "next/link"
import useSWR from "swr"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
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

export function ProjectKeys() {
  const { data: projects } = useSWR<Project[]>("/api/projects", fetcher)
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
            {overrides.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="pl-6 pr-6 text-sm text-muted-foreground"
                >
                  No project-level keys — every project uses your account keys
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
                      <Link href={`/projects/${project.id}`}>Manage</Link>
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
