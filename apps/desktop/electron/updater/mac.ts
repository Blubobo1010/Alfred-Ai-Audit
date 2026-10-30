import type { AppUpdater } from 'electron-updater'

import { applyPackagedHandoff } from './packaged-handoff'
import type { RelaunchRegistration } from './relaunch'

import type { UpdaterApplyResultWire, UpdaterStatusWire, UpdaterStrategy } from './index'

export interface MacStrategyDeps {
  updater: Pick<AppUpdater, 'checkForUpdates' | 'downloadUpdate' | 'quitAndInstall' | 'on' | 'removeListener'>
  channel: string
  expectedVersion?: string
  verifyDownload?: (files: string[]) => Promise<void>
  appVersion: string
  /** Unpacks and verifies the signed app before any backend is stopped. Squirrel.Mac never runs: it reads
   * the whole update zip into memory and crashes past 1 GiB (alfred C0152). */
  prepareInstall: (files: string[], version: string) => Promise<void>
  /** Refuses, before the download, an install this copy cannot finish. */
  preflightInstall: () => Promise<void>
  /** Starts the swap helper; it waits for this process to exit. */
  relaunch: { register: () => Promise<RelaunchRegistration>; onManual: () => void }
  /** Quits so the helper can replace the bundle. */
  install: () => void
  beforeInstall: () => Promise<void>
  onInstallFailure: () => Promise<void>
  emitProgress: (payload: { stage: string; message: string; percent: number | null }) => void
}

export class MacStrategy implements UpdaterStrategy {
  readonly mechanism = 'electron-updater' as const
  private applying = false

  constructor(private readonly deps: MacStrategyDeps) {}

  async check(): Promise<UpdaterStatusWire> {
    if (this.applying) {
      throw new Error('An update is already in progress.')
    }

    return this.checkRelease()
  }

  private async checkRelease(): Promise<UpdaterStatusWire> {
    const result = await this.deps.updater.checkForUpdates()

    if (!result) {
      throw new Error('The macOS updater is not active for this app.')
    }

    if (this.deps.expectedVersion && result.updateInfo.version !== this.deps.expectedVersion) {
      throw new Error('Native macOS feed does not match the pinned channel version')
    }

    return {
      supported: true,
      mechanism: this.mechanism,
      currentVersion: this.deps.appVersion,
      channel: this.deps.channel,
      latestTag: `v${result.updateInfo.version}`,
      updateAvailable: result.isUpdateAvailable,
      fetchedAt: Date.now()
    }
  }

  async apply(): Promise<UpdaterApplyResultWire> {
    if (this.applying) {
      throw new Error('An update is already in progress.')
    }

    this.applying = true

    const progress = ({ percent }: { percent: number }): void => {
      this.deps.emitProgress({ stage: 'fetch', message: 'Downloading the +Human update.', percent })
    }

    this.deps.updater.on('download-progress', progress)

    try {
      return await applyPackagedHandoff(
        {
          teardown: this.deps.beforeInstall,
          restore: this.deps.onInstallFailure,
          emitProgress: this.deps.emitProgress,
          relaunch: this.deps.relaunch
        },
        async (stop: () => Promise<void>): Promise<UpdaterApplyResultWire> => {
          const status = await this.checkRelease()

          if (!status.updateAvailable) {
            return { ok: true, mechanism: this.mechanism }
          }

          await this.deps.preflightInstall()
          const files = await this.deps.updater.downloadUpdate()
          await this.deps.verifyDownload?.(files)
          this.deps.emitProgress({ stage: 'prepare', message: 'Verifying the signed macOS update.', percent: null })
          await this.deps.prepareInstall(files, (status.latestTag ?? '').replace(/^v/, ''))
          await stop()
          this.deps.emitProgress({
            stage: 'restart',
            message: 'Restarting +Human to install the update.',
            percent: 100
          })
          this.deps.install()

          return { ok: true, bundled: true, handedOff: true, mechanism: this.mechanism }
        }
      )
    } finally {
      this.deps.updater.removeListener('download-progress', progress)
      this.applying = false
    }
  }
}

export interface NativeMacUpdater {
  once(event: 'update-downloaded', listener: () => void): unknown
  once(event: 'error', listener: (error: Error) => void): unknown
  removeListener(event: 'update-downloaded', listener: () => void): unknown
  removeListener(event: 'error', listener: (error: Error) => void): unknown
  checkForUpdates(): void
}

/** Download completion alone does not mean Squirrel accepted the signature. */
export function prepareMacInstall(native: NativeMacUpdater, timeoutMs: number = 120_000): Promise<void> {
  return new Promise<void>((resolve: () => void, reject: (error: Error) => void): void => {
    const cleanup = (): void => {
      clearTimeout(timer)
      native.removeListener('error', failed)
      native.removeListener('update-downloaded', ready)
    }

    const failed = (error: Error): void => {
      cleanup()
      reject(error)
    }

    const ready = (): void => {
      cleanup()
      resolve()
    }

    const timer = setTimeout((): void => failed(new Error('macOS update verification timed out.')), timeoutMs)
    native.once('error', failed)
    native.once('update-downloaded', ready)

    try {
      native.checkForUpdates()
    } catch (error) {
      failed(error as Error)
    }
  })
}
