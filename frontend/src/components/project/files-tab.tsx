"use client"

import { FileUp, RotateCcw, Trash2 } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api, fetcher } from "@/lib/api"
import type { FileRecord, Project } from "@/lib/types"

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—"
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FilesTab({
  project,
  onChanged,
}: {
  project: Project
  onChanged: () => void
}) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const { data: files, mutate } = useSWR<FileRecord[]>(
    `/api/projects/${project.id}/files`,
    fetcher,
    {
      refreshInterval: (latest) =>
        latest?.some((f) => f.status === "pending" || f.status === "processing")
          ? 3000
          : 0,
      onSuccess: () => onChanged(),
    }
  )

  async function handleUpload(list: FileList | null) {
    if (!list || list.length === 0) return
    const form = new FormData()
    for (const file of Array.from(list)) {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        toast.error(`${file.name}: only PDF files are supported`)
        return
      }
      form.append("uploads", file)
    }
    setUploading(true)
    try {
      await api(`/api/projects/${project.id}/files`, {
        method: "POST",
        body: form,
      })
      toast.success("Upload complete — indexing started")
      mutate()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed")
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ""
    }
  }

  async function handleDelete(file: FileRecord) {
    if (!confirm(`Delete ${file.filename}? Its content will be removed from the index.`)) {
      return
    }
    try {
      await api(`/api/projects/${project.id}/files/${file.id}`, {
        method: "DELETE",
      })
      toast.success(`${file.filename} deleted`)
      mutate()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed")
    }
  }

  async function handleRetry(file: FileRecord) {
    try {
      await api(`/api/projects/${project.id}/files/${file.id}/retry`, {
        method: "POST",
      })
      mutate()
      onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Retry failed")
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
        >
          <FileUp className="size-4" />
          {uploading ? "Uploading…" : "Add files"}
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept=".pdf"
          multiple
          hidden
          onChange={(e) => handleUpload(e.target.files)}
        />
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>File</TableHead>
                <TableHead>Size</TableHead>
                <TableHead>Pages</TableHead>
                <TableHead>Chunks</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {!files || files.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={6}
                    className="py-10 text-center text-muted-foreground"
                  >
                    No files yet — add PDFs to build the knowledge base.
                  </TableCell>
                </TableRow>
              ) : (
                files.map((file) => (
                  <TableRow key={file.id}>
                    <TableCell className="max-w-56 truncate font-medium">
                      {file.filename}
                      {file.error && (
                        <p className="truncate text-xs font-normal text-destructive">
                          {file.error}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>{formatSize(file.size_bytes)}</TableCell>
                    <TableCell>{file.page_count ?? "—"}</TableCell>
                    <TableCell>{file.chunk_count}</TableCell>
                    <TableCell>
                      <StatusBadge status={file.status} />
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        {file.status === "failed" && (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            title="Retry indexing"
                            onClick={() => handleRetry(file)}
                          >
                            <RotateCcw className="size-4" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Delete file"
                          onClick={() => handleDelete(file)}
                        >
                          <Trash2 className="size-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
