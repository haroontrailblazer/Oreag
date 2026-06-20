import { useEffect, useId, useSyncExternalStore } from "react"

/**
 * Shared "is this project navigating?" store.
 *
 * A project is reachable from more than one place at once — its sidebar row and
 * its dashboard card. Each link reports its own pending state (from
 * `useLinkStatus`) here, and every link reads back whether ANY link to that
 * project is in flight. So clicking the sidebar row lights up the card's spinner
 * too, and vice versa.
 */

const pendingInstances = new Map<string, Set<string>>()
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function isProjectPending(projectId: string): boolean {
  return (pendingInstances.get(projectId)?.size ?? 0) > 0
}

function report(projectId: string, instanceId: string, pending: boolean) {
  let set = pendingInstances.get(projectId)
  if (pending) {
    if (!set) {
      set = new Set()
      pendingInstances.set(projectId, set)
    }
    if (!set.has(instanceId)) {
      set.add(instanceId)
      emit()
    }
  } else if (set?.has(instanceId)) {
    set.delete(instanceId)
    if (set.size === 0) pendingInstances.delete(projectId)
    emit()
  }
}

/**
 * Feed this link's own `ownPending` into the shared store and read back whether
 * any link to `projectId` is currently navigating.
 */
export function useProjectNavPending(
  projectId: string,
  ownPending: boolean
): boolean {
  const instanceId = useId()

  useEffect(() => {
    report(projectId, instanceId, ownPending)
    return () => report(projectId, instanceId, false)
  }, [projectId, instanceId, ownPending])

  return useSyncExternalStore(
    subscribe,
    () => isProjectPending(projectId),
    () => false
  )
}
