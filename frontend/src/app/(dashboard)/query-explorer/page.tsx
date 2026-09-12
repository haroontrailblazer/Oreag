import { QueryExplorer } from "@/components/query-explorer"
import { QueryExplorerLoading } from "@/components/query-explorer-loading"
import { Suspense } from "react"

export default function QueryExplorerPage() { return <Suspense fallback={<QueryExplorerLoading />}><QueryExplorer /></Suspense> }
