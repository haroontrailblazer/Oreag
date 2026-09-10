import {
  ArrowLeftIcon,
  ArrowUpRightIcon,
  BookOpenIcon,
  SquaresFourIcon,
} from "@phosphor-icons/react/dist/ssr"
import Link from "next/link"

import { BrandMark } from "@/components/ui/brand-mark"
import { Button } from "@/components/ui/button"
import styles from "./not-found.module.css"

export default function NotFound() {
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link href="/" className={styles.brand} aria-label="Oreag home">
          <BrandMark className="size-8" />
          <span>Oreag</span>
        </Link>
        <span className={styles.headerNote}>A little off the map.</span>
      </header>

      <main id="main-content" className={styles.main}>
        <div className={styles.content}>
          <p className={styles.eyebrow}>
            <span aria-hidden="true" />
            404 / Page not found
          </p>
          <h1 className={styles.title}>
            A wrong turn.<br />
            <span>A way forward.</span>
          </h1>
          <p className={styles.description}>
            We couldn’t find the page you’re looking for. The link may be
            outdated, or the address may have a typo.
          </p>
          <Button asChild size="lg" className={styles.homeButton}>
            <Link href="/">
              <ArrowLeftIcon aria-hidden="true" />
              Back to home
            </Link>
          </Button>
        </div>

        <div className={styles.illustration} aria-hidden="true">
          <div className={styles.diagram}>
            <div className={styles.orbit} />
            <div className={styles.innerOrbit} />
            <span className={styles.node} />
            <span className={styles.crosshair}>+</span>
            <span className={styles.crosshairBottom}>+</span>
            <div className={styles.errorCode}>
              <span>4</span><span className={styles.zero}>0</span><span>4</span>
            </div>
            <div className={styles.route}>
              <span className={styles.routeStart} />
              <span className={styles.routeLine} />
              <span className={styles.routeEnd}>?</span>
            </div>
            <span className={styles.diagramLabel}>Destination not found</span>
          </div>
        </div>

        <nav className={styles.destinations} aria-label="Helpful destinations">
          <div className={styles.destinationIntro}>
            <span className={styles.sectionLabel}>PICK UP FROM HERE</span>
            <p>Find your next step.</p>
          </div>
          <Link href="/dashboard" className={styles.destination}>
            <SquaresFourIcon className={styles.destinationIcon} aria-hidden="true" />
            <div>
              <span className={styles.destinationTitle}>Your workspace</span>
              <p>Return to your projects.</p>
            </div>
            <ArrowUpRightIcon className={styles.arrow} aria-hidden="true" />
          </Link>
          <Link href="/docs" className={styles.destination}>
            <BookOpenIcon className={styles.destinationIcon} aria-hidden="true" />
            <div>
              <span className={styles.destinationTitle}>Documentation</span>
              <p>Find a guide. Keep building.</p>
            </div>
            <ArrowUpRightIcon className={styles.arrow} aria-hidden="true" />
          </Link>
        </nav>
      </main>

      <footer className={styles.footer}>
        <span>Oreag</span>
        <span>Knowledge, connected.</span>
      </footer>
    </div>
  )
}
